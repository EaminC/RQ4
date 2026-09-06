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
            train, test, summary = split_mod.split(index, ts, seed=seed)
            row = {
                "train_size_requested": ts,
                "repeat": rep,
                "seed": seed,
                **summary,
            }
            rows.append(row)
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
    lines.append("# Split sweep — train_size sweep × repeats\n")
    lines.append(f"Usable issues (with valid A–F category): **{n_total}**\n")
    lines.append("Each row is one (train_size, repeat) run.\n")
    lines.append("| req | rep | train | test | train % | unique repos | leakage % | cats covered |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---|")
    for r in rows:
        cats = r["train_category_counts"]
        covered = sum(1 for c in "ABCDEF" if c in cats)
        total_cats = 6
        cats_str = f"{covered}/{total_cats}"
        train_pct = round(100.0 * r["train_size"] / n_total, 1)
        lines.append(
            f"| {r['train_size_requested']} | {r['repeat']} | "
            f"{r['train_size']} | {r['test_size']} | "
            f"{train_pct} | {r['train_unique_repos']} | "
            f"{r['test_repo_leakage_pct']} | {cats_str} |"
        )
    # Per-train_size average row.
    lines.append("")
    lines.append("## Averages over the 3 repeats\n")
    lines.append("| req | train (mean) | test (mean) | leakage % (mean) | repos (mean) | cats covered |")
    lines.append("|---:|---:|---:|---:|---:|---|")
    by_ts: dict[int, list[dict]] = {}
    for r in rows:
        by_ts.setdefault(r["train_size_requested"], []).append(r)
    for ts in sorted(by_ts):
        rep_rows = by_ts[ts]
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
            f"| {ts} | {avg_train:.1f} | {avg_test:.1f} | "
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
