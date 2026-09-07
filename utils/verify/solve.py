#!/usr/bin/env python3
"""solve.py — drive the agent over the verify pool.

This is the **rollout** driver for Component 6 of RQ4.

Iterate ``split=1`` rows of a per-skill index file, build (or re-use)
a Docker image with the issue's repo at the base SHA, run the agent
against the resulting container *twice* per issue (with and without
the matching ``SKILL.md`` injected), and capture the trajectory and
patch as an artifact bundle that
``AgentBug-Smith/exp/evaluate_f2p.py --patch-mode issue_json`` can
score.

Sub-commands
------------
``solve.py dry-run``
    Walk every targeted row and print what *would* happen: verify
    the index fields, the pool dir, the resolved SKILL.md (if any),
    and the prompt. No LLM is called, no Docker image is built.
    Use this for the pilot when you want to verify the data flow
    without spending cost.

``solve.py rollout``   (a.k.a. the production run)
    Build Docker images, invoke the agent, save trajectories +
    patches + agent logs into
    ``data/verify/runs/<agent>_<train_size>/<repo>__<id>/{with,without}_skill/``.
    Idempotent — already-done (id, skill_mode) runs are skipped.
    Supports ``--resume`` and ``--max-rows N`` for controlled
    progress.

``solve.py status``
    Print per-(key, skill_mode) completion stats: n_total, n_done,
    n_failed, latest mtime. No side effects.

``solve.py score``
    Apply each captured trajectory's patch to a fresh container,
    run the f2p test, record pass/fail. Thin wrapper over
    AgentSmith's ``evaluate_f2p.py``; not implemented in this
    commit (the eval driver lives in ``exp/evaluate_f2p.py``).

Output layout
-------------
::

    data/verify/runs/<agent>_<train_size>/<repo>__<id>/
        image_meta.json                  # {tag, built_at, build_log_tail}
        with_skill/
            prompt.txt                   # what we passed to -t
            trajectory.json              # mini-swe-agent --output
            patch.txt                    # the agent's git diff
            agent.json                   # {cost, exit_code, stdout_tail, ran_at}
            eval_in.json                 # passed to evaluate_f2p.py later
        without_skill/
            ...

Wiring into the pool
--------------------
The verify pool at ``data/verify/_pool/<owner>__<name>__<id>/``
contains exactly three files (``env.dockerfile``, ``issue.json``,
``agentsmith_fail2pass_<NNN>.py``). To produce a working Docker
build context the solver *also* needs the repo's source tree at
the right base SHA. By convention we expect the upstream
``AgentBug-Smith`` checkout at ``~/AgentBug-Smith`` (it already
hosts a handful of repo clones and the build pipeline). The
solver looks for ``$AGENTSMITH_ROOT/<owner>_<name>`` and aborts
with a clear error if not present.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(REPO_ROOT / "utils"))

# Reuse the pool-dir helper + audit from build_verify so solver and
# pool can't drift on the (repo, id) → pool-dir mapping.
from verify.build_verify import pool_dir_for  # noqa: E402

VERIFY_ROOT = REPO_ROOT / "data" / "verify"
POOL_DIR = VERIFY_ROOT / "_pool"
RUNS_ROOT = VERIFY_ROOT / "runs"

AGENTSMITH_ROOT = Path(
    os.environ.get("AGENTSMITH_ROOT", str(Path.home() / "AgentBug-Smith"))
)

SKILL_ROOT = REPO_ROOT / "agent" / "skills"
VENV_BIN = REPO_ROOT / "agent" / "venv" / "bin"
MINI_VENV_BIN = REPO_ROOT / "agent" / ".venv" / "bin"

DEFAULT_MODEL = "openai/gpt-4.1-mini"      # served by tu-zi gateway
DEFAULT_COST_LIMIT = 3.0
DEFAULT_WALL_TIMEOUT = 1800       # 30 min per agent run
DEFAULT_DOCKER_BUILD_TIMEOUT = 900 # 15 min per image build

SUPPORTED_AGENTS = ("mini-swe-agent", "openhands")
SUPPORTED_TRAIN_SIZES = (40, 60, 80)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Row:
    """A single line of an issue_index JSONL file."""
    index_path: Path
    line_no: int
    raw: dict[str, Any]

    @property
    def id(self) -> str:
        return self.raw["id"]

    @property
    def repo(self) -> str:
        return self.raw["repo"]

    @property
    def category(self) -> str:
        return self.raw.get("category", "?")

    @property
    def split(self) -> int:
        return int(self.raw["split"])

    @property
    def verify_dir(self) -> Path:
        p = self.raw["verify_dir"]
        return (REPO_ROOT / p).resolve() if not Path(p).is_absolute() else Path(p)

    @property
    def test_relpath(self) -> str | None:
        return self.raw.get("test_relpath")

    @property
    def base_sha(self) -> str | None:
        return self.raw.get("base_sha")

    @property
    def skill_key(self) -> str:
        """`mini-swe-agent_40` etc., from source_split."""
        ss = self.raw.get("source_split", {})
        return f"{ss.get('agent')}_{ss.get('train_size_requested')}"


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------

def load_rows(index_path: Path, only_test: bool = True) -> list[Row]:
    """Load rows from an issue_index_*.jsonl file.

    With ``only_test=True`` (default) keep only ``split=1`` rows.
    """
    rows: list[Row] = []
    with index_path.open() as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if only_test and int(obj.get("split", -1)) != 1:
                continue
            rows.append(Row(index_path=index_path, line_no=n, raw=obj))
    return rows


def agent_repo_path(repo: str) -> Path:
    """Map ``strands-agents/harness-sdk`` → ``<agentsmith>/data/<owner>_<name>``."""
    if "/" not in repo:
        raise ValueError(f"repo not in owner/name form: {repo!r}")
    owner, name = repo.split("/", 1)
    for base in (AGENTSMITH_ROOT / "data", AGENTSMITH_ROOT):
        p = base / f"{owner}_{name}"
        if p.exists():
            return p
    raise FileNotFoundError(
        f"repo clone not found at {AGENTSMITH_ROOT}/data/{owner}_{name} "
        f"(or {AGENTSMITH_ROOT}/{owner}_{name}). Clone {repo} into "
        f"$AGENTSMITH_ROOT/data/ or set AGENTSMITH_ROOT."
    )


def skill_path(agent: str, train_size: int, *, with_skill: bool) -> Path:
    """Return the SKILL.md (or the generic fallback for the no-skill baseline)."""
    skill_dir = SKILL_ROOT / agent / str(train_size)
    if with_skill:
        p = skill_dir / "SKILL.md"
    else:
        p = skill_dir / "fallback_generic_fix.md"
    if not p.exists():
        raise FileNotFoundError(p)
    return p


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------

ISSUE_PROMPT_TEMPLATE = """\
You are a software engineer. A GitHub issue from the repo **{repo}*
has been reproduced in your working tree at `/testbed`. Your task is to
make the **minimum source-code change** that fixes the issue, **without
modifying any test file**.

## Issue

**Title:** {title}

**Body:**

```
{body}
```

## Test

The fail-to-pass test that must pass after your fix is:

```
{test_relpath}
```

A copy of that test has already been installed at `tests/{test_filename}`
for you — do **not** edit it.

## Submission

When you are done, run `git diff > /testbed/patch.txt` and verify that
`patch.txt` contains only the source files you intended to change.

Then submit with EXACTLY this command (must be its own step, no `&&`):

```
echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && cat /testbed/patch.txt
```

## Tools preference (CRITICAL — read first)

Your working directory IS the testbed repo (a git checkout of the upstream
project at the bug's base commit). Edit source files in place; do not
clone, copy, or re-init a fresh git repo.

**Use the bash tool for ALL edits.** Example workflows:

```bash
# View the file with line numbers
nl -ba src/foo/bar.py | sed -n '40,60p'

# Edit a Python function (safer than file_editor)
python3 - <<'PY'
import re, pathlib
p = pathlib.Path('src/foo/bar.py')
src = p.read_text()
src = src.replace('old_block', 'new_block', 1)
p.write_text(src)
PY

# Verify the change
git diff --stat
git diff src/foo/bar.py | head -80
```

Do NOT use the `file_editor` / `str_replace_editor` tool — its
`security_risk` schema is missing from the runtime you're running on and
will reject every call. Bash is fully equivalent and works.

When all edits are in place, capture the diff and submit:

```bash
git diff > patch.txt
echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && cat patch.txt
```

(Note: `patch.txt` is the relative path — the cwd is the repo root.)
"""


def build_prompt(row: Row, *, with_skill: bool) -> tuple[str, Path]:
    """Return ``(prompt_text, skill_path_resolved)``.

    ``with_skill=False`` returns the generic fallback so the prompt
    is still intelligible without per-repo guidance.
    """
    ss = row.raw.get("source_split", {})
    agent = ss.get("agent") or "mini-swe-agent"
    train_size = int(ss.get("train_size_requested") or 40)
    skill = skill_path(agent, train_size, with_skill=with_skill)

    issue = json.loads((row.verify_dir / "issue.json").read_text())
    title = issue.get("title", row.id)
    body = issue.get("body") or ""
    test_filename = Path(row.test_relpath or f"tests/agentsmith_fail2pass_{row.id.split('-')[1]}.py").name

    prompt = ISSUE_PROMPT_TEMPLATE.format(
        repo=row.repo,
        title=title,
        body=body,
        test_relpath=row.test_relpath or "(not provided)",
        test_filename=test_filename,
    )

    if with_skill:
        skill_text = skill.read_text()
        prompt = f"<skill>\n{skill_text}\n</skill>\n\n{prompt}"

    return prompt, skill


# ---------------------------------------------------------------------------
# Old helper stubs removed in favor of build_one_image / run_one_agent /
# extract_patch below (see rollout section). Keeping nothing here.
# ---------------------------------------------------------------------------


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Pilot driver
# ---------------------------------------------------------------------------

def dry_run_row(row: Row, *, with_skill: bool) -> dict[str, Any]:
    """Print every input the solver has for a single (row, skill_mode).

    No Docker, no agent — purely a data-flow sanity check.
    """
    prompt, skill = build_prompt(row, with_skill=with_skill)
    v = row.verify_dir
    return {
        "id": row.id,
        "repo": row.repo,
        "category": row.category,
        "split": row.split,
        "skill_key": row.skill_key,
        "with_skill": with_skill,
        "skill_path": str(skill.relative_to(REPO_ROOT)),
        "skill_chars": len(skill.read_text()),
        "verify_dir": str(v.relative_to(REPO_ROOT)),
        "pool_files": sorted(p.name for p in v.iterdir() if p.is_file()),
        "test_relpath": row.test_relpath,
        "base_sha": row.base_sha,
        "issue_title": json.loads((v / "issue.json").read_text()).get("title"),
        "prompt_chars": len(prompt),
        "prompt_head": prompt[:240].replace("\n", " ⏎ "),
    }


def fmt_dry(out: dict[str, Any]) -> str:
    lines = [
        f"  ┌─ pilot ───────────────────────────────────────────────────────",
        f"  │ id           : {out['id']}",
        f"  │ repo         : {out['repo']}",
        f"  │ category     : {out['category']}",
        f"  │ skill        : {out['skill_key']}  with_skill={out['with_skill']}",
        f"  │ SKILL.md     : {out['skill_path']} ({out['skill_chars']} chars)",
        f"  │ verify_dir   : {out['verify_dir']}",
        f"  │ pool files   : {out['pool_files']}",
        f"  │ base_sha     : {out['base_sha']}",
        f"  │ test         : {out['test_relpath']}",
        f"  │ issue_title  : {out['issue_title']!r}",
        f"  │ prompt_chars : {out['prompt_chars']}",
        f"  │ prompt head  : {out['prompt_head']}",
        f"  └──────────────────────────────────────────────────────────────",
    ]
    return "\n".join(lines)


def cmd_dry_run(rows: Iterable[Row]) -> int:
    for row in rows:
        for with_skill in (True, False):
            out = dry_run_row(row, with_skill=with_skill)
            print(fmt_dry(out))
    return 0


# ---------------------------------------------------------------------------
# Rollout orchestration (real runs)
# ---------------------------------------------------------------------------

@dataclass
class RunSpec:
    """A single unit of work: one row × one skill_mode."""
    row: Row
    with_skill: bool
    out_dir: Path            # data/verify/runs/<key>/<id>/{with,without}_skill/
    image_tag: str
    is_done: bool = False
    is_failed: bool = False


def spec_for_row(row: Row, *, with_skill: bool) -> RunSpec:
    ss = row.raw.get("source_split", {})
    agent = ss.get("agent") or "mini-swe-agent"
    train_size = ss.get("train_size_requested") or "?"
    safe_repo = row.repo.replace("/", "__")
    key = f"{agent}_{train_size}"
    # Both skill modes share ONE image (image is the repo+test at base
    # SHA; the skill only changes the prompt). Single tag → single
    # build, reused by both with/without runs.
    # Docker tag must be lowercase; repo names like ``crewAIInc/crewAI``
    # contain upper-case chars that the daemon rejects.
    tag = f"rq4-{safe_repo.lower()}-{row.id}-{train_size}"
    out_dir = (
        RUNS_ROOT / key / f"{safe_repo}__{row.id}"
        / ("with_skill" if with_skill else "without_skill")
    )
    return RunSpec(row=row, with_skill=with_skill, out_dir=out_dir, image_tag=tag)


def spec_is_done(spec: RunSpec) -> bool:
    """A spec is done iff patch.txt exists and agent.json says exit_code==0.

    Note: a cost-1+ step_limit-or-time exceeded exit is also considered
    done if patch.txt is non-empty (the agent did finish; we still score
    whatever patch it produced).
    """
    patch = spec.out_dir / "patch.txt"
    agent_log = spec.out_dir / "agent.json"
    return patch.exists() and patch.stat().st_size > 0 and agent_log.exists()


def spec_is_failed(spec: RunSpec) -> bool:
    sentinel = spec.out_dir / "_failed.json"
    return sentinel.exists()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_lock_path(repo: str) -> Path:
    """Per-repo lock file to serialize concurrent builds.

    Multiple solve.py workers may target the same upstream repo clone
    (e.g. when running a batch over many issues in one repo). Without
    serialization, ``git checkout`` races on ``.git/index.lock`` and
    the build fails. The lock is held only during the ``build_one_image``
    step; agents themselves do not need it because each agent invocation
    is independent of git state once the image is built.
    """
    safe = repo.replace("/", "__").replace(" ", "_")
    return Path("/tmp") / f"rq4_build_lock_{safe}.lock"


def build_one_image(spec: RunSpec) -> tuple[bool, str]:
    """Build a Docker image for a single row, install pool files into the
    upstream repo clone, and tag it.

    The upstream repo at ``$AGENTSMITH_ROOT/<owner>_<name>`` is checked
    out at the row's base SHA first. If the clone is dirty (e.g. a
    previous run left state), we force a clean working tree by
    ``git reset --hard`` after the checkout.
    """
    repo_dir = agent_repo_path(spec.row.repo)
    if not spec.row.base_sha:
        return False, f"row {spec.row.id} has no base_sha"

    lock = _build_lock_path(spec.row.repo)
    lock_fd = open(lock, "w")
    try:
        # Block until no other worker is building against this repo.
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)

        # Clean up any stale lock file the previous worker may have left.
        stale_lock = repo_dir / ".git" / "index.lock"
        if stale_lock.exists():
            try:
                stale_lock.unlink()
            except OSError:
                pass

        # Always start from a clean working tree — the dockerfile install
        # step and the previous run may have left unstaged changes, and
        # ``git checkout <base_sha>`` will refuse to proceed otherwise.
        subprocess.run(
            ["git", "-C", str(repo_dir), "reset", "--hard", "HEAD"],
            capture_output=True, text=True, timeout=60,
        )
        subprocess.run(
            ["git", "-C", str(repo_dir), "clean", "-fd"],
            capture_output=True, text=True, timeout=60,
        )
        rc = subprocess.run(
            ["git", "-C", str(repo_dir), "checkout", spec.row.base_sha],
            capture_output=True, text=True, timeout=60,
        )
        if rc.returncode != 0:
            return False, f"git checkout {spec.row.base_sha} failed: {rc.stderr[:500]}"
        rc = subprocess.run(
            ["git", "-C", str(repo_dir), "reset", "--hard", spec.row.base_sha],
            capture_output=True, text=True, timeout=60,
        )
        if rc.returncode != 0:
            return False, f"git reset --hard failed: {rc.stderr[:500]}"

        # Install the pool's dockerfile + f2p test.
        pool_dockerfile = spec.row.verify_dir / "env.dockerfile"
        if pool_dockerfile.exists():
            shutil.copy2(pool_dockerfile, repo_dir / "env.dockerfile")
        if spec.row.test_relpath:
            test_filename = Path(spec.row.test_relpath).name
            src_test = next(spec.row.verify_dir.glob("agentsmith_fail2pass_*.py"), None)
            if src_test:
                (repo_dir / "tests").mkdir(exist_ok=True)
                shutil.copy2(src_test, repo_dir / "tests" / test_filename)

        # Build.
        rc = subprocess.run(
            ["docker", "build", "-t", spec.image_tag, "-f", "env.dockerfile", "."],
            cwd=repo_dir, capture_output=True, text=True,
            timeout=DEFAULT_DOCKER_BUILD_TIMEOUT,
        )
        ok = rc.returncode == 0
        log = (rc.stdout + "\n" + rc.stderr)[-3000:]
        return ok, log
    finally:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        lock_fd.close()


def run_one_agent(spec: RunSpec, prompt: str, *,
                  model: str, cost_limit: float) -> dict[str, Any]:
    """Invoke the agent against the built image.

    Returns a dict with ``exit_code``, ``cost``, ``stdout_tail``,
    ``stderr_tail``, ``ran_at``. Saves prompt + trajectory + agent log
    to ``spec.out_dir``.
    """
    spec.out_dir.mkdir(parents=True, exist_ok=True)
    (spec.out_dir / "prompt.txt").write_text(prompt, encoding="utf-8")

    agent_name = spec.row.raw.get("source_split", {}).get("agent") or "mini-swe-agent"
    env = {
        **os.environ,
        "OPENAI_API_BASE": os.environ.get("TUZI_BASE_URL", ""),
        "OPENAI_API_KEY":  os.environ.get("TUZI_API_KEY", ""),
    }

    if agent_name == "mini-swe-agent":
        traj_path = spec.out_dir / "trajectory.json"
        proc = subprocess.run(
            [
                str(MINI_VENV_BIN / "mini"),
                "-c", str(REPO_ROOT / "agent" / "mini-swe-agent" / "src"
                          / "minisweagent" / "config" / "benchmarks" / "swebench.yaml"),
                "-c", str(REPO_ROOT / "agent" / "config" / "mini.yaml"),
                "--model", model,
                "--cost-limit", str(cost_limit),
                "--exit-immediately",
                "--yolo",
                "--environment-class", "docker",
                "-c", f"environment.image={spec.image_tag}",
                "--output", str(traj_path),
                "-t", prompt,
            ],
            cwd=str(REPO_ROOT / "agent" / "mini-swe-agent"),
            capture_output=True, text=True, timeout=DEFAULT_WALL_TIMEOUT,
            env=env,
        )
        result = {
            "agent": agent_name,
            "exit_code": proc.returncode,
            "stdout_tail": proc.stdout[-2000:],
            "stderr_tail": proc.stderr[-2000:],
            "ran_at": _now(),
            "trajectory_path": str(traj_path.relative_to(REPO_ROOT))
                                if traj_path.exists() else None,
        }
    elif agent_name == "openhands":
        # OpenHands uses its own CLI; we rely on $OPENHANDS_CONFIG_DIR
        # (configured in agent/openhands-config/.env) and just run the
        # -t task. Trajectory location is engine-specific.
        #
        # CRITICAL: openhands' default sandbox is the cwd at invocation.
        # The agent's prompt tells it to run ``git diff > /testbed/patch.txt``
        # but openhands doesn't know about /testbed — it just diffs cwd.
        # We pre-cd into the testbed clone so the agent's ``git diff``
        # captures the actual repo changes, and we read ``patch.txt``
        # back from there afterwards (the agent writes it to its cwd).
        repo_dir = str(agent_repo_path(spec.row.repo))
        oh_proc = subprocess.run(
            [str(REPO_ROOT / "agent" / "openhands-config" / ".venv" / "bin"
                 if (REPO_ROOT / "agent" / "openhands-config" / ".venv").exists()
                 else shutil.which("openhands") or "openhands"),
             "--headless", "--override-with-envs", "--yolo",
             "-t", prompt],
            cwd=repo_dir,
            capture_output=True, text=True, timeout=DEFAULT_WALL_TIMEOUT,
            env=env,
        )
        # If the agent wrote patch.txt in its cwd (= testbed), copy it
        # into the spec out_dir and rewrite it to a git-format diff.
        host_patch = Path(repo_dir) / "patch.txt"
        if host_patch.exists():
            content = host_patch.read_text()
            # The agent's `git diff` against cwd is already git-format,
            # so we can use it directly. No _submission_to_git_diff rewrite.
            (spec.out_dir / "patch.txt").write_text(content)
        result = {
            "agent": agent_name,
            "exit_code": oh_proc.returncode,
            "stdout_tail": oh_proc.stdout[-2000:],
            "stderr_tail": oh_proc.stderr[-2000:],
            "ran_at": _now(),
            "trajectory_path": None,
        }
    else:
        return {"agent": agent_name, "exit_code": -1,
                "stderr_tail": f"unknown agent {agent_name!r}", "ran_at": _now()}

    (spec.out_dir / "agent.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def _strip_app_prefix(path: str) -> str:
    """Strip ``/app/`` from a path. Mini operates on the repo mounted
    at ``/app``; ``git apply`` against the host repo needs repo-relative
    paths. Also strips ``b/`` from diff-style paths (``b/X → X``).
    """
    p = path.strip()
    if p.startswith("/app/"):
        p = p[len("/app/"):]
    # Strip leading "b/" from diff-style paths (e.g. "b/A2A/wrapper.py → A2A/wrapper.py")
    if p.startswith("b/"):
        p = p[2:]
    return p


def _normalize_diff_line(line: str) -> str:
    """Normalize a single diff header line for git-format output.

    - ``--- /app/.../X.py.bak`` → ``--- a/<stripped>/X.py``
    - ``+++ /app/.../X.py``     → ``+++ b/<stripped>/X.py``
    """
    if line.startswith("--- "):
        rest = line[4:].split("\t", 1)[0]
        rest = _strip_app_prefix(rest)
        rest = rest.removesuffix(".bak")
        return f"--- a/{rest}"
    if line.startswith("+++ "):
        rest = line[4:].split("\t", 1)[0]
        rest = _strip_app_prefix(rest)
        return f"+++ b/{rest}"
    return line


def _submission_to_git_diff(submission: str) -> str | None:
    """Convert mini's ``--- file.bak / +++ file`` submission to git format.

    mini's last assistant message contains a unified diff against a
    ``.bak`` snapshot the agent made at task start — not a ``git diff``
    header. ``git apply`` rejects this because:

      * the file path is absolute (``/app/src/...``) instead of
        repo-relative (``src/...``),
      * there's no ``diff --git a/X b/X`` header,
      * the ``---`` side references ``X.py.bak``.

    We rewrite each ``+++ path`` header into a git-format block::

        diff --git a/<path> b/<path>
        --- a/<path>
        +++ b/<path>
        <body unchanged>

    where ``<path>`` has had ``/app/`` stripped and ``.bak`` removed.
    Hunk body (``@@ ... @@`` and below) is preserved verbatim.

    Returns None if the submission has no ``+++ path`` header (so
    callers can fall through to other extractors).
    """
    if not submission:
        return None
    if "diff --git " in submission and "/app/" not in submission and " a/b/" not in submission:
        # Already in git format; nothing to do.
        return submission

    lines = submission.split("\n")
    # Detect whether at least one "+++" path exists.
    paths = [ln[4:].strip().split("\t", 1)[0]
             for ln in lines if ln.startswith("+++ ")]
    paths = [p for p in paths if p]
    if not paths:
        return None

    # Walk lines, flushing a git-format block each time we hit "+++ ".
    out_chunks: list[str] = []
    cur_path = None
    cur_lines: list[str] = []
    for ln in lines:
        if ln.startswith("+++ "):
            if cur_path is not None:
                stripped = _strip_app_prefix(cur_path)
                out_chunks.append(f"diff --git a/{stripped} b/{stripped}")
                out_chunks.append(f"--- a/{stripped}")
                for cl in cur_lines:
                    out_chunks.append(_normalize_diff_line(cl))
            cur_path = ln[4:].strip().split("\t", 1)[0]
            cur_lines = [ln]
        else:
            cur_lines.append(ln)
    if cur_path is not None:
        stripped = _strip_app_prefix(cur_path)
        out_chunks.append(f"diff --git a/{stripped} b/{stripped}")
        out_chunks.append(f"--- a/{stripped}")
        for cl in cur_lines:
            out_chunks.append(_normalize_diff_line(cl))
    return "\n".join(out_chunks)


def extract_patch(spec: RunSpec) -> bool:
    """Pull the agent's git diff out of the trajectory / agent.json and
    save it as ``patch.txt``.

    For mini-swe-agent: read ``info.submission`` from trajectory.json
    (the agent's last assistant message — a unified diff against a
    ``.bak`` snapshot), rewrite it to git format, and save as
    ``patch.txt``.

    For openhands: read stdout_tail from agent.json for the patch.

    Returns True on success.
    """
    if spec.row.raw.get("source_split", {}).get("agent") == "mini-swe-agent":
        traj_path = spec.out_dir / "trajectory.json"
        if not traj_path.exists():
            return False
        try:
            traj = json.loads(traj_path.read_text())
        except Exception:
            return False
        # 1) Prefer info.submission — this is the agent's final unified
        #    diff and is what the agent meant to submit.
        submission = (traj.get("info") or {}).get("submission") or ""
        if submission.strip():
            rewritten = _submission_to_git_diff(submission)
            if rewritten and rewritten.strip():
                (spec.out_dir / "patch.txt").write_text(rewritten)
                return True
        # 2) Fallback: search the entire blob for ``diff --git`` text.
        blob = json.dumps(traj)
        if "diff --git " in blob:
            i = blob.find("diff --git ")
            end = blob.rfind("```", 0, len(blob))
            chunk = blob[i:end] if end > i else blob[i:]
            (spec.out_dir / "patch.txt").write_text(chunk)
            return True
        return False

    # openhands: the host patch was already copied to patch.txt by
    # run_one_agent (when the agent ran in the testbed cwd). If that
    # didn't happen (e.g. the agent failed), fall back to stdout_tail.
    if (spec.out_dir / "patch.txt").exists():
        # Already produced by run_one_agent; only accept it if non-empty.
        return (spec.out_dir / "patch.txt").stat().st_size > 0
    agent_log = spec.out_dir / "agent.json"
    if not agent_log.exists():
        return False
    log = json.loads(agent_log.read_text())
    out = (log.get("stdout_tail") or "") + "\n" + (log.get("stderr_tail") or "")
    if "+++ " in out or "diff --git " in out:
        i = out.find("+++ ") if "+++ " in out else out.find("diff --git ")
        (spec.out_dir / "patch.txt").write_text(out[i:])
        return True
    return False


def rollout_rows(rows: list[Row], *,
                 skill_modes: list[bool],
                 model: str,
                 cost_limit: float,
                 max_rows: int | None = None,
                 skip_done: bool = True,
                 dry_build_only: bool = False) -> dict[str, int]:
    """Top-level orchestration loop.

    Steps per (row, skill_mode):
        1. Resolve spec + skip if done (unless ``skip_done=False``).
        2. Build docker image (only once per row, regardless of skill_mode).
        3. If ``dry_build_only``, stop here.
        4. For each skill_mode: build prompt, invoke agent, extract patch.

    Returns a stats dict ``{built, skipped, ok, failed, error}``.
    """
    stats = {"planned": 0, "built": 0, "skipped": 0, "ok": 0, "failed": 0,
             "build_fail": 0, "agent_fail": 0, "patch_missing": 0,
             "rows_seen": 0, "rows_done": 0}

    if max_rows is not None:
        rows = rows[:max_rows]

    for r_idx, row in enumerate(rows, 1):
        specs = [spec_for_row(row, with_skill=m) for m in skill_modes]
        stats["rows_seen"] += 1

        # Skip whole row if all skill_modes already done.
        if skip_done and all(spec_is_done(s) for s in specs):
            stats["rows_done"] += 1
            stats["skipped"] += len(specs)
            print(f"[{r_idx}/{len(rows)}] {row.id}  SKIP (all done)")
            continue

        print(f"[{r_idx}/{len(rows)}] {row.id}  repo={row.repo}  base={row.base_sha[:8] if row.base_sha else '?'}")

        # Build image (once per row). Both skill modes share this
        # image, so the meta lives at the row level (not under
        # with_skill/ or without_skill/) and the tag is skill-mode-
        # agnostic.
        build_tag = specs[0].image_tag
        key = f"{specs[0].row.raw.get('source_split', {}).get('agent') or 'mini-swe-agent'}_{specs[0].row.raw.get('source_split', {}).get('train_size_requested') or '?'}"
        safe_repo = row.repo.replace("/", "__")
        image_meta_path = RUNS_ROOT / key / f"{safe_repo}__{row.id}" / "image_meta.json"
        if not image_meta_path.exists():
            ok, log = build_one_image(specs[0])
            image_meta_path.parent.mkdir(parents=True, exist_ok=True)
            image_meta = {
                "tag": build_tag,
                "built_at": _now(),
                "ok": ok,
                "log_tail": log[-3000:],
            }
            image_meta_path.write_text(json.dumps(image_meta, indent=2))
            if not ok:
                for s in specs:
                    (s.out_dir).mkdir(parents=True, exist_ok=True)
                    (s.out_dir / "_build_failed.json").write_text(
                        json.dumps({"image_tag": build_tag, "log_tail": log[-3000:]}, indent=2))
                stats["build_fail"] += 1
                print(f"  ✗ docker build failed (see image_meta.json)")
                continue
            stats["built"] += 1
            print(f"  ✓ docker build → {build_tag}")
        else:
            meta = json.loads(image_meta_path.read_text())
            if not meta.get("ok"):
                stats["build_fail"] += 1
                print(f"  ✗ prior build failed (cached) — skipping row")
                continue
            print(f"  ↻ docker build cached → {build_tag}")

        if dry_build_only:
            continue

        # Run agent for each skill_mode.
        for spec in specs:
            stats["planned"] += 1
            if skip_done and spec_is_done(spec):
                stats["skipped"] += 1
                stats["ok"] += 1
                print(f"  · {spec.out_dir.name}  SKIP (already done)")
                continue
            prompt, skill = build_prompt(spec.row, with_skill=spec.with_skill)
            print(f"  · {spec.out_dir.name}  prompt={len(prompt)}c  skill={'on' if spec.with_skill else 'off'}")
            t0 = time.time()
            try:
                run_one_agent(spec, prompt, model=model, cost_limit=cost_limit)
            except subprocess.TimeoutExpired:
                stats["agent_fail"] += 1
                (spec.out_dir / "_timeout.json").write_text(json.dumps(
                    {"wall_seconds": time.time() - t0, "ran_at": _now()}, indent=2))
                print(f"    ✗ timeout after {DEFAULT_WALL_TIMEOUT}s")
                continue
            except Exception as e:
                stats["agent_fail"] += 1
                (spec.out_dir / "_agent_error.json").write_text(json.dumps(
                    {"error": repr(e), "ran_at": _now()}, indent=2))
                print(f"    ✗ agent error: {e!r}")
                continue
            if extract_patch(spec):
                stats["ok"] += 1
                print(f"    ✓ patch extracted ({time.time()-t0:.1f}s)")
            else:
                stats["patch_missing"] += 1
                (spec.out_dir / "_no_patch.json").write_text(json.dumps(
                    {"ran_at": _now()}, indent=2))
                print(f"    ✗ no patch extracted")

    return stats


def cmd_status(rows: Iterable[Row], *, skill_modes: list[bool]) -> int:
    counts = {"done": 0, "failed": 0, "missing": 0, "build_failed": 0}
    for row in rows:
        for with_skill in skill_modes:
            spec = spec_for_row(row, with_skill=with_skill)
            if spec_is_done(spec):
                counts["done"] += 1
            elif spec_is_failed(spec):
                counts["failed"] += 1
            elif (spec.out_dir.parent / "image_meta.json").exists():
                counts["missing"] += 1
            else:
                counts["build_failed"] += 1
    print(json.dumps(counts, indent=2))
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _resolve_skill_modes(arg: str) -> list[bool]:
    if arg == "all":
        return [True, False]
    if arg == "with":
        return [True]
    if arg == "without":
        return [False]
    raise ValueError(arg)


def _load_index_rows(index_path: Path, only_test: bool) -> list[Row]:
    rows = load_rows(index_path, only_test=only_test)
    if not rows:
        sys.exit(f"no rows in {index_path} (only_test={only_test})")
    return rows


def main() -> None:
    p = argparse.ArgumentParser(description="Drive the agent over the verify pool.")
    sub = p.add_subparsers(dest="mode", required=True)

    def add_io(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--index", type=Path, required=True,
                        help="issue_index_*.jsonl")
        sp.add_argument("--pilot-id", type=str, default=None,
                        help="Limit to one issue id (e.g. issue-1077).")
        sp.add_argument("--skill-mode",
                        choices=["with", "without", "all"],
                        default="all",
                        help="with_skill only / without_skill only / both.")

    add_io(sub.add_parser("dry-run",
                          help="Print what would happen, no LLM/docker."))
    add_io(sub.add_parser("status",
                          help="Count done/missing/failed runs (no side effects)."))

    ro = sub.add_parser("rollout",
                        help="Build image + invoke agent (idempotent).")
    add_io(ro)
    ro.add_argument("--model", default=DEFAULT_MODEL)
    ro.add_argument("--cost-limit", type=float, default=DEFAULT_COST_LIMIT)
    ro.add_argument("--max-rows", type=int, default=None,
                    help="Limit to first N rows (for staged rollout).")
    ro.add_argument("--no-skip-done", action="store_true",
                    help="Re-run even if patch.txt exists.")
    ro.add_argument("--build-only", action="store_true",
                    help="Only build docker images, skip agent runs.")

    score = sub.add_parser("score",
                           help="Apply patch + run test for prior runs.")
    add_io(score)

    args = p.parse_args()
    if not args.index.exists():
        sys.exit(f"--index {args.index} does not exist")

    only_test = args.mode != "dry-run"
    rows = _load_index_rows(args.index, only_test=only_test)
    if args.pilot_id:
        rows = [r for r in rows if r.id == args.pilot_id]
        if not rows:
            sys.exit(f"--pilot-id {args.pilot_id!r} not in {args.index.name}")

    skill_modes = _resolve_skill_modes(args.skill_mode)

    if args.mode == "dry-run":
        if args.skill_mode == "all":
            return cmd_dry_run(rows)
        out = dry_run_row(rows[0], with_skill=skill_modes[0])
        print(fmt_dry(out))
        return 0

    if args.mode == "status":
        return cmd_status(rows, skill_modes=skill_modes)

    if args.mode == "rollout":
        stats = rollout_rows(
            rows, skill_modes=skill_modes,
            model=args.model, cost_limit=args.cost_limit,
            max_rows=args.max_rows,
            skip_done=not args.no_skip_done,
            dry_build_only=args.build_only,
        )
        print()
        print(json.dumps(stats, indent=2))
        return 0

    if args.mode == "score":
        sys.exit("score not implemented in this commit; see TODO in solve.py")

    return 0


if __name__ == "__main__":
    sys.exit(main())
