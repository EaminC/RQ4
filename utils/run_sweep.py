"""Sweep split/train-size combinations and report results.

For each (train_size, seed) pair, call ``utils.split.split`` and record:
- requested train_size
- actual train_size and test_size after the algorithm
- per-category counts in train
- test_repo_leakage_pct (the unavoidable cost on small datasets)
- train_unique_repos

Writes a JSONL ``results/sweep.jsonl`` and a human-readable
``results/sweep.md`` table.

Usage::

    python utils/run_sweep.py \
        --index data/index.jsonl \
        --train-sizes 20 40 60 80 100 120 140 160 180 \
        --repeats 3 \
        --out results
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make the split module importable as a library.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from split import run as split_mod  # type: ignore  # noqa: E402


def run_sweep(index: list[dict], train_sizes: list[int], repeats: int
              ) -> list[dict]:
    rows = []
    for ts in train_sizes:
        for rep in range(repeats):
            seed = 1000 * rep + ts  # deterministic per (ts, rep)
            # default (bounded cap) mode
            train, test, summary = split_mod.split(index, ts, seed=seed,
                                                   mode="default")
            row_default = {
                "mode": "default",
                "train_size_requested": ts,
                "repeat": rep,
                "seed": seed,
                **summary,
            }
            # repo_disjoint (strict) mode
            train, test, summary_rd = split_mod.split(index, ts, seed=seed,
                                                      mode="repo_disjoint")
            row_rd = {
                "mode": "repo_disjoint",
                "train_size_requested": ts,
                "repeat": rep,
                "seed": seed,
                **summary_rd,
            }
            rows.append(row_default)
            rows.append(row_rd)
    return rows


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def write_markdown(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    n_total = rows[0]["train_size"] + rows[0]["test_size"] if rows else 0
    lines: list[str] = []
    lines.append("# Split sweep — train_size sweep × repeats × mode\n")
    lines.append(f"Usable issues (with valid A–F category): **{n_total}**\n")
    lines.append("Two modes per (train_size, repeat):\n"
                 "- **default** = bounded per-repo cap (best-effort low leakage)\n"
                 "- **repo_disjoint** = strict, whole repos moved between "
                 "train/test → guarantees `leakage == 0`\n")
    lines.append("| mode | req | rep | train | test | train % | "
                 "unique repos | leakage % | cats covered |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---|")
    for r in rows:
        cats = r["train_category_counts"]
        covered = sum(1 for c in "ABCDEF" if c in cats)
        total_cats = 6
        cats_str = f"{covered}/{total_cats}"
        train_pct = round(100.0 * r["train_size"] / n_total, 1)
        lines.append(
            f"| {r['mode']} | {r['train_size_requested']} | {r['repeat']} | "
            f"{r['train_size']} | {r['test_size']} | "
            f"{train_pct} | {r['train_unique_repos']} | "
            f"{r['test_repo_leakage_pct']} | {cats_str} |"
        )
    # Per-(mode, train_size) average row.
    lines.append("")
    lines.append("## Averages over the 3 repeats\n")
    lines.append("| mode | req | train (mean) | test (mean) | "
                 "leakage % (mean) | repos (mean) | cats covered |")
    lines.append("|---|---:|---:|---:|---:|---:|---|")
    by_key: dict[tuple[str, int], list[dict]] = {}
    for r in rows:
        by_key.setdefault((r["mode"], r["train_size_requested"]), []).append(r)
    for mode in ["default", "repo_disjoint"]:
        for ts in sorted({k[1] for k in by_key if k[0] == mode}):
            rep_rows = by_key[(mode, ts)]
            n = len(rep_rows)
            avg_train = sum(x["train_size"] for x in rep_rows) / n
            avg_test = sum(x["test_size"] for x in rep_rows) / n
            avg_leak = sum(x["test_repo_leakage_pct"] for x in rep_rows) / n
            avg_repos = sum(x["train_unique_repos"] for x in rep_rows) / n
            covered = sum(
                1 for c in "ABCDEF"
                if all(c in x["train_category_counts"] for x in rep_rows)
            )
            lines.append(
                f"| {mode} | {ts} | {avg_train:.1f} | {avg_test:.1f} | "
                f"{avg_leak:.1f} | {avg_repos:.1f} | {covered}/6 |"
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--index", type=Path, default=Path("data/index.jsonl"))
    p.add_argument("--train-sizes", type=int, nargs="+",
                   default=[20, 40, 60, 80, 100, 120, 140, 160, 180])
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--out", type=Path, default=Path("results"),
                   help="Directory for sweep.jsonl and sweep.md")
    args = p.parse_args()

    rows = [json.loads(l) for l in args.index.read_text().splitlines() if l.strip()]
    print(f"Loaded {len(rows)} index rows from {args.index}")

    results = run_sweep(rows, args.train_sizes, args.repeats)
    write_jsonl(args.out / "sweep.jsonl", results)
    write_markdown(args.out / "sweep.md", results)
    print(f"Wrote {args.out / 'sweep.jsonl'} and {args.out / 'sweep.md'}")


if __name__ == "__main__":
    main()
