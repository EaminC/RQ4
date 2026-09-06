"""Prompts assembled by utils.train.train_skill.

These strings are sent to the per-repo agent (mini-swe-agent or
openhands) as the task description. They tell the agent exactly:

- which repo to clone, where to put it
- which issues to read, where the patches are
- what to write, where to write it, in what shape
- how to make the output composable with other repos' notes

Keep prompts deterministic (no f-string time / randomness) so they
re-render identically across runs.
"""
from __future__ import annotations

from pathlib import Path


REPO_NOTES_INSTRUCTIONS = """\
You are writing one file of a multi-file Cursor Agent Skill called
`rq4-issue-fixer`. The skill teaches an agent how to fix issues in
the repository **{repo}* ({description}).

Your output is a single markdown notes file. It will be loaded by the
agent on demand (via `@repos/{safe_repo}.md`) when a new issue in
this repo needs fixing. Treat this as **training data for a
downstream agent**, not as a human report.

## Input you will receive

The orchestrator has already cloned `{repo}` into a scratch
workspace at `{scratch_dir}`. Inside that workspace you will find:

- The full upstream source tree of `{repo}` — read it freely.
- One folder per closed issue:
  `{scratch_dir}/issues/<issue_id>/`
  containing (some of which may be absent):
    - `issue.json`         — original GitHub issue body, labels,
                             linked PRs.
    - `patch.diff`         — the f2p-tested golden patch that fixed
                             the issue. **May be absent** — the
                             dataset does not always carry it. If you
                             see `PATCH_MISSING.txt` instead, distill
                             the fix from the issue body + failing
                             test + surrounding code.
    - `fail2pass_test.py`  — the test that was failing before the
                             patch and passing after. Read this to
                             understand the contract the fix has to
                             satisfy.
    - `f2p.txt`            — the fail-to-pass test trace / stdout.
    - `summary.json`       — provenance and pass/fail status.
    - `run.log`            — full agent run log (if present).
    - `env.dockerfile`     — the test environment (if present).
    - `agentsmith_stat.json` — token / cost / time stats for the
                             original run (if present).

These issues span the **whole** repo (train + test split from the
research perspective — that doesn't matter for you, you are
distilling the repo's fix idioms, not learning the split).

## What to write

Write exactly one file at:

  {out_path}

The file should be **markdown, 80-300 lines**, with these sections:

1. **Repo identity** — one paragraph: what the repo does, the
   language/framework, who maintains it.

2. **Typical issue shape** — 3-5 bullets. What kinds of issues
   appear here (bug reports, feature requests, regressions)?
   How well-specified are they? Is there a "bug template" that
   gives reproduction steps?

3. **Recurring fix patterns** — 3-7 bullets, each in the form
       "When you see X, the fix is usually Y in <module>".
   Concrete module paths, function names, class names. These are
   the highest-leverage lines — they let the downstream agent
   pattern-match new issues quickly.

4. **Files / modules that change most often** — table of
       `<path> | <why it gets touched>`.

5. **Pitfalls** — 3-5 bullets. Things that look like a fix but
   aren't (e.g. forgetting to update a registry, async/sync
   mismatch, breaking the tool-call schema).

6. **Test conventions** — 1 paragraph. Where tests live, how they
   are invoked, naming conventions (e.g. `test_<issue_number>.py`).

7. **One concrete worked example** — pick one issue from the
   inputs (any one), summarise it in 4-6 lines, link to the issue
   id and the PR if the issue JSON gives one.

## Style

- Use backticks for all file paths, function names, class names.
- Prefer concrete over abstract. "Edit `src/strands/agent/agent.py`
  line 612 to pass `messages` to the hook" beats "the agent
  invocation flow needs improvement".
- Quote 1-2 short snippets (3-10 lines) from a real patch.diff if
  they illustrate a recurring pattern.
- Do not invent behaviour you didn't observe in the inputs.

## What NOT to do

- Don't write code in the notes file — only describe patterns.
- Don't paste full patch.diff bodies — distill them.
- Don't add sections like "Conclusion" or "Further work" — this
  is a reference doc, not an essay.
- Don't reference the orchestrator, the scratch dir, or the
  training pipeline by name. The downstream agent should treat
  this as if it were written by hand.

When the file is written, print `OK <path>` and exit. Do not run
any other commands after writing.
"""


def repo_lessons_prompt(
    repo: str,
    description: str,
    scratch_dir: str,
    out_path: str,
) -> str:
    """Build the per-repo training prompt."""
    safe_repo = repo.replace("/", "__")
    return REPO_NOTES_INSTRUCTIONS.format(
        repo=repo,
        description=description,
        safe_repo=safe_repo,
        scratch_dir=scratch_dir,
        out_path=out_path,
    )


def safe_repo_name(repo: str) -> str:
    """Map 'owner/name' to a filename-safe slug."""
    return repo.replace("/", "__").replace(" ", "_")


def issue_id_from_path(p: Path) -> str:
    """Extract the issue id from a data/raw/... issue directory.

    Directory layout: ``issue_<id>_<timestamp>`` → returns ``<id>``.
    """
    name = p.name
    if name.startswith("issue_"):
        parts = name.split("_")
        # 'issue_<digits>_<timestamp>' → take parts[1]
        return parts[1] if len(parts) >= 2 and parts[1].isdigit() else name
    return name
