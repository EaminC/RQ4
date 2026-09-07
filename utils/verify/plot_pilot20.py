#!/usr/bin/env python3
"""Plot pass@1 by agent × skill_mode from pilot_20_scores.csv.

Generates:
  - results/rq4/figures/pilot20_passrate.png  — bar chart
  - results/rq4/figures/pilot20_outcomes.png  — grouped outcomes
  - results/rq4/figures/pilot20_breakdown.txt  — text summary

Reads:
  - results/rq4/pilot_20_scores.csv
"""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CSV_PATH = REPO_ROOT / "results" / "rq4" / "pilot_20_scores.csv"
OUT_DIR  = REPO_ROOT / "results" / "rq4" / "figures"


def load_rows() -> list[dict]:
    return list(csv.DictReader(CSV_PATH.open()))


def main() -> int:
    rows = load_rows()
    if not rows:
        print(f"no rows in {CSV_PATH}")
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Aggregate by (agent, skill_mode), excluding issues where the
    # rollout never produced a patch (most often: docker build failure
    # on the issue's repo). We want a fair comparison between the
    # agents, not a comparison that includes 67 "no build" entries.
    by_combo = {}
    n_total = 0
    n_buildable = 0
    for r in rows:
        key = (r["agent"], r["skill_mode"])
        c = by_combo.setdefault(key, Counter())
        n_total += 1
        if r["has_patch"] == "True":
            n_buildable += 1
            c[r["outcome"] or "no_patch"] += 1
        else:
            # Don't include no-patch (build failed) in the chart so we
            # can see the actual agent-vs-agent signal.
            pass

    combos = sorted(by_combo.keys())
    # Stable outcome order
    outcomes_order = ["f2p", "p2p", "p2f", "f2f", "error", "no_patch"]
    outcome_colors = {
        "f2p":     "#2ecc71",  # green
        "p2p":     "#3498db",  # blue
        "p2f":     "#e74c3c",  # red
        "f2f":     "#f39c12",  # orange
        "error":   "#7f8c8d",  # gray
        "no_patch":"#bdc3c7",  # light gray
    }

    # Plot
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    fig, ax = plt.subplots(figsize=(9, 5))
    width = 0.18
    x = np.arange(len(combos))
    bottoms = np.zeros(len(combos))

    for outcome in outcomes_order:
        vals = np.array([by_combo[c].get(outcome, 0) for c in combos])
        ax.bar(x, vals, width, bottom=bottoms,
               label=outcome,
               color=outcome_colors[outcome],
               edgecolor="black", linewidth=0.4)
        bottoms = bottoms + vals

    ax.set_xticks(x)
    ax.set_xticklabels([f"{a}\n{s}" for (a, s) in combos],
                       fontsize=10)
    ax.set_ylabel("count")
    ax.set_title("RQ4 pilot-20: rollout outcomes\n(20 issues × 2 skill modes per agent)")
    ax.legend(loc="upper right", fontsize=9, framealpha=0.95)
    ax.set_ylim(0, max(bottoms) + 2)
    for i, c in enumerate(combos):
        n = sum(by_combo[c].values())
        ax.text(i, n + 0.3, f"n={n}", ha="center", fontsize=9)

    plt.tight_layout()
    out1 = OUT_DIR / "pilot20_outcomes.png"
    fig.savefig(out1, dpi=140)
    plt.close(fig)
    print(f"wrote {out1}")

    # Pass@1 bar chart — focus on outcomes distribution among
    # buildable rollouts (no docker-build failures).
    fig2, ax2 = plt.subplots(figsize=(8, 5))
    useful_outcomes = ["f2p", "p2p", "p2f", "f2f", "error"]
    useful_colors = {
        "f2p":     "#2ecc71",  # green
        "p2p":     "#3498db",  # blue
        "p2f":     "#e74c3c",  # red
        "f2f":     "#f39c12",  # orange
        "error":   "#7f8c8d",  # gray
    }
    width = 0.16
    x = np.arange(len(combos))
    bottoms = np.zeros(len(combos))
    for oc in useful_outcomes:
        vals = np.array([by_combo[c].get(oc, 0) for c in combos])
        ax2.bar(x, vals, width, bottom=bottoms,
                label=oc, color=useful_colors[oc],
                edgecolor="black", linewidth=0.4)
        for i, v in enumerate(vals):
            if v > 0:
                ax2.text(i, bottoms[i] + v/2, str(v),
                         ha="center", va="center", fontsize=10,
                         fontweight="bold", color="white")
        bottoms = bottoms + vals
    ax2.set_xticks(x)
    ax2.set_xticklabels([f"{a[:5]}\n{s}" for (a, s) in combos], fontsize=10)
    ax2.set_ylabel("count")
    ax2.set_title("RQ4 pilot-20: outcomes on buildable rollouts only\n"
                  "(excluded 67 docker-build failures on strands-agents/harness-sdk)")
    ax2.legend(loc="upper right", fontsize=10, framealpha=0.95)
    plt.tight_layout()
    out2 = OUT_DIR / "pilot20_passrate.png"
    fig2.savefig(out2, dpi=140)
    plt.close(fig2)
    print(f"wrote {out2}")

    # Text breakdown
    out3 = OUT_DIR / "pilot20_breakdown.txt"
    with out3.open("w") as f:
        f.write("RQ4 pilot-20 breakdown\n")
        f.write("======================\n\n")
        f.write(f"Total rollouts: {n_total}\n")
        f.write(f"Buildable rollouts (docker image OK + patch produced): "
                f"{n_buildable} ({100*n_buildable/max(n_total,1):.1f}%)\n")
        f.write(f"  - skipped reasons are mostly docker build failures on\n")
        f.write(f"    strands-agents/harness-sdk (hatch-vcs missing git tag).\n\n")
        for (a, s), c in sorted(by_combo.items()):
            n = sum(c.values())
            f.write(f"{a}  {s}_skill  (n={n}, buildable)\n")
            for outcome in outcomes_order:
                v = c.get(outcome, 0)
                if v:
                    f.write(f"   {outcome:9s}: {v}\n")
            f2p = c.get("f2p", 0)
            f.write(f"   pass@1   = {100*f2p/max(n,1):.1f}%\n\n")
    print(f"wrote {out3}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
