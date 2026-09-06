"""Train per-repo skill notes, repo-by-repo, for one (agent, train_size).

For a given configuration:

  - call ``utils.split.split`` with mode=repo_disjoint (zero leakage)
    and the requested train_size to obtain the per-repo partition.
  - for each repo in train_repos:
      - clone the repo into a scratch workspace
      - materialise all the repo's issues (train ∪ test) as
        issue.json / patch.diff / f2p.txt bundles
      - invoke the chosen agent wrapper (``agent/run_<agent>.sh``)
        with the prompt from ``utils.train.prompts``; the agent
        writes ``repos/<owner>__<name>.md`` into the skill dir.
  - finalise SKILL.md (from the template) and write manifest.json.

Usage::

    python utils/train/train_skill.py \\
        --agent mini-swe-agent \\
        --train-size 40 \\
        --mode repo_disjoint \\
        --seed 42 \\
        --out agent/skills

    python utils/train/train_skill.py --dry-run --agent openhands \\
        --train-size 20   # print prompts, no agent calls.

The output of a full run for one (agent, train_size) is::

    agent/skills/<agent>/<train_size>/
        SKILL.md                       # the skill itself
        fallback_generic_fix.md        # generated from template
        repos/
            <owner>__<name>.md         # one per trained repo
        manifest.json                  # provenance

Six full runs (2 agents × 3 sizes) populate the whole ``agent/skills/``
tree.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable

# Re-use the split module as a library.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))            # utils/
sys.path.insert(0, str(HERE.parent.parent))     # repo root (for `from utils...`)
from utils.split import run as split_mod         # noqa: E402
from utils.train import prompts as prompt_mod    # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Data plumbing: gather every issue of a repo (train ∪ test) into a scratch
# workspace under issues/<id>/.
# ---------------------------------------------------------------------------
def _issue_dirs_for_repo(index: list[dict], repo: str) -> list[Path]:
    """Return the absolute paths of all issue directories belonging to ``repo``."""
    return [Path(r["path"]) for r in index if r["repo"] == repo]


def _materialise_issues(
    src_dirs: Iterable[Path], dest_root: Path
) -> list[tuple[str, Path]]:
    """Copy each issue dir's payload into ``dest_root/issues/<id>/``.

    Returns a list of ``(issue_id, dest_dir)`` for the prompts to reference.
    """
    out: list[tuple[str, Path]] = []
    for src in src_dirs:
        iid = prompt_mod.issue_id_from_path(src)
        dest = dest_root / "issues" / iid
        dest.mkdir(parents=True, exist_ok=True)
        for fname, newname in [
            ("issue.json", None),
            ("generated_patch.diff", "patch.diff"),
            ("f2p.txt", None),
            ("summary.json", None),
            ("issue_*.json", None),     # some repos store extra metadata
        ]:
            for f in src.glob(fname):
                target = dest / (newname or f.name)
                if f.resolve() == target.resolve():
                    continue
                shutil.copy2(f, target)
        out.append((iid, dest))
    return out


def _setup_scratch(
    repo: str, issue_dirs: list[Path], scratch_root: Path
) -> Path:
    """Clone the repo and lay out its issues. Returns the scratch dir."""
    scratch = scratch_root / prompt_mod.safe_repo_name(repo)
    scratch.mkdir(parents=True, exist_ok=True)
    clone_target = scratch / "src"
    if not clone_target.exists():
        subprocess.run(
            ["git", "clone", "--depth=1", f"https://github.com/{repo}.git",
             str(clone_target)],
            check=True,
        )
    _materialise_issues(issue_dirs, scratch)
    # README to orient the agent.
    (scratch / "README.txt").write_text(
        f"Scratch workspace for skill-training run on repo {repo}.\n"
        f"Issues are under issues/<id>/; source tree is under src/.\n",
        encoding="utf-8",
    )
    return scratch


# ---------------------------------------------------------------------------
# Agent invocation — wraps the existing agent/run_<agent>.sh.
# ---------------------------------------------------------------------------
def _agent_run_script(agent: str) -> Path:
    """Return absolute path to the agent's wrapper script."""
    name = "mini" if agent == "mini-swe-agent" else agent
    return REPO_ROOT / "agent" / f"run_{name}.sh"


def _invoke_agent(
    agent: str,
    task: str,
    cwd: Path,
    cost_limit: float = 3.0,
) -> subprocess.CompletedProcess:
    """Run the agent wrapper with the given task in ``cwd``."""
    script = _agent_run_script(agent)
    env = os.environ.copy()
    env["COST_LIMIT"] = str(cost_limit)
    return subprocess.run(
        ["bash", str(script), "-t", task],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# Skill finalisation — assemble SKILL.md, fallback, manifest.
# ---------------------------------------------------------------------------
def _write_skill_md(
    skill_dir: Path, agent: str, train_size: int, repos: list[str]
) -> None:
    template = (HERE / "templates" / "SKILL.template.md").read_text(
        encoding="utf-8")
    repo_bullets = "\n".join(f"- `{r}`" for r in sorted(repos))
    body = template.replace("N training issues across R repos",
                            f"{train_size} training issues across "
                            f"{len(repos)} repos")
    body = body.replace("- `strands-agents`", repo_bullets)
    (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")


def _write_fallback(skill_dir: Path) -> None:
    src = HERE / "templates" / "fallback_generic_fix.template.md"
    (skill_dir / "fallback_generic_fix.md").write_text(
        src.read_text(encoding="utf-8"), encoding="utf-8")


def _write_manifest(
    skill_dir: Path,
    *,
    agent: str,
    train_size: int,
    mode: str,
    seed: int,
    actual_train_size: int,
    repos: list[str],
    issues_per_repo: dict[str, int],
) -> None:
    rel_skill_dir = (
        str(skill_dir.relative_to(REPO_ROOT))
        if str(skill_dir).startswith(str(REPO_ROOT))
        else str(skill_dir)
    )
    manifest = {
        "agent": agent,
        "train_size_requested": train_size,
        "train_size_actual": actual_train_size,
        "split_mode": mode,
        "seed": seed,
        "repos_trained": sorted(repos),
        "issues_per_repo": issues_per_repo,
        "total_issues_for_skill": sum(issues_per_repo.values()),
        "skill_dir": rel_skill_dir,
    }
    (skill_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Top-level orchestration.
# ---------------------------------------------------------------------------
def train_one_repo(
    *,
    agent: str,
    repo: str,
    issue_dirs: list[Path],
    skill_dir: Path,
    scratch_root: Path,
    cost_limit: float,
    dry_run: bool,
) -> bool:
    """Train the per-repo notes for one repo. Returns True on success."""
    safe = prompt_mod.safe_repo_name(repo)
    out_path = skill_dir / "repos" / f"{safe}.md"
    if out_path.exists() and out_path.stat().st_size > 0:
        print(f"  [skip] {safe}.md already exists")
        return True

    scratch = _setup_scratch(repo, issue_dirs, scratch_root)
    task = prompt_mod.repo_lessons_prompt(
        repo=repo,
        description=f"see {scratch}/src/README.md",
        scratch_dir=str(scratch),
        out_path=str(out_path),
    )

    if dry_run:
        print(f"--- prompt for {repo} ---")
        print(task[:400] + "\n... [truncated]\n")
        # Still write a stub so the manifest can list this repo.
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            f"# {repo} (stub, dry-run)\n\nTraining not run.\n",
            encoding="utf-8",
        )
        return True

    print(f"  [run] {agent} on {repo}  →  {out_path}")
    result = _invoke_agent(agent, task, cwd=scratch, cost_limit=cost_limit)
    if result.returncode != 0:
        print(f"  [err ] {repo} agent exited {result.returncode}")
        print(result.stderr[-400:])
        return False
    if not out_path.exists() or out_path.stat().st_size < 200:
        print(f"  [err ] {repo} produced no usable notes file")
        return False
    print(f"  [ok  ] {repo}: {out_path.stat().st_size} bytes")
    return True


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--agent", required=True,
                   choices=["mini-swe-agent", "openhands"])
    p.add_argument("--train-size", type=int, required=True,
                   help="Requested train size (will be rounded up by split)")
    p.add_argument("--mode", default="repo_disjoint",
                   choices=["default", "repo_disjoint", "greedy_issue"])
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--index", type=Path, default=REPO_ROOT / "data" / "index.jsonl")
    p.add_argument("--out", type=Path,
                   default=REPO_ROOT / "agent" / "skills",
                   help="Root directory for trained skills")
    p.add_argument("--scratch-root", type=Path,
                   default=Path(tempfile.gettempdir()) / "rq4-skill-train")
    p.add_argument("--cost-limit", type=float, default=3.0,
                   help="USD per per-repo agent call")
    p.add_argument("--dry-run", action="store_true",
                   help="Print prompts only; don't invoke the agent")
    p.add_argument("--repos", nargs="*", default=None,
                   help="Restrict to a subset of repos (for debugging)")
    args = p.parse_args()

    index = [json.loads(l) for l in args.index.read_text().splitlines() if l.strip()]
    print(f"[idx] {len(index)} issues loaded")

    _, _, summary = split_mod.split(
        index, args.train_size, seed=args.seed, mode=args.mode,
    )
    train_repos = summary["train_repos"]
    print(f"[spl] mode={args.mode} req={args.train_size} "
          f"actual={summary['train_size']} repos={len(train_repos)}")

    if args.repos:
        train_repos = [r for r in train_repos if r in set(args.repos)]
        print(f"[spl] restricted to {len(train_repos)} repos via --repos")

    skill_dir = args.out / args.agent / str(args.train_size)
    (skill_dir / "repos").mkdir(parents=True, exist_ok=True)

    issues_per_repo: dict[str, int] = {}
    for repo in sorted(train_repos):
        ids = _issue_dirs_for_repo(index, repo)
        issues_per_repo[repo] = len(ids)
        ok = train_one_repo(
            agent=args.agent,
            repo=repo,
            issue_dirs=ids,
            skill_dir=skill_dir,
            scratch_root=args.scratch_root,
            cost_limit=args.cost_limit,
            dry_run=args.dry_run,
        )
        if not ok and not args.dry_run:
            print(f"[warn] {repo} failed; continuing with remaining repos")

    _write_skill_md(skill_dir, args.agent, args.train_size, train_repos)
    _write_fallback(skill_dir)
    _write_manifest(
        skill_dir,
        agent=args.agent,
        train_size=args.train_size,
        mode=args.mode,
        seed=args.seed,
        actual_train_size=summary["train_size"],
        repos=train_repos,
        issues_per_repo=issues_per_repo,
    )
    print(f"[done] skill at {skill_dir}")


if __name__ == "__main__":
    main()
