#!/usr/bin/env python3
"""Plot cumulative pass@1 rate as a function of rollout count.

Shows how the estimated pass@1 rate evolves as each new rollout is added,
with 95% confidence intervals (Clopper-Pearson). Also shows per-issue
outcome as a heatmap.

Usage:
    python utils/verify/plot_pilot20.py
"""
from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
CSV_PATH   = REPO_ROOT / "results" / "rq4" / "pilot_20_scores.csv"
OUT_DIR    = REPO_ROOT / "results" / "rq4" / "figures"


def clopper_pearson(k: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    """Wilson score interval (more stable than Clopper-Pearson for small n)."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    z = 1.96  # 95% CI
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    margin = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return max(0, center - margin), min(1, center + margin)


def load_rows():
    return list(csv.DictReader(CSV_PATH.open()))


def main() -> int:
    rows = load_rows()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # --- Figure 1: cumulative pass@1 with CI ----------------------------
    # For each (agent, skill) combo, sort by issue order and accumulate
    combos = {}
    for r in rows:
        key = (r["agent"], r["skill_mode"])
        combos.setdefault(key, []).append(r)

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # Left: cumulative f2p rate (all combos on one plot)
    ax = axes[0]
    colors = {"mini-swe-agent": "#3498db", "openhands": "#e74c3c"}
    linestyles = {"with": "-", "without": "--"}
    markers = {"with": "o", "without": "s"}

    for (agent, skill), rlist in sorted(combos.items()):
        # Only plot combos that have at least some patches
        buildable = [r for r in rlist if r["has_patch"] == "True"]
        if not buildable:
            continue
        n = len(buildable)
        cum_f2p = []
        lower, upper = [], []
        for i, r in enumerate(buildable, 1):
            k = sum(1 for r2 in buildable[:i] if r2["outcome"] == "f2p")
            rate = k / i
            lo, hi = clopper_pearson(k, i)
            cum_f2p.append(rate)
            lower.append(lo)
            upper.append(hi)

        x = np.arange(1, n + 1)
        c = colors.get(agent, "#7f8c8d")
        ls = linestyles.get(skill, "-")
        mk = markers.get(skill, "o")
        label = f"{agent[:5]}-{skill}"
        ax.plot(x, [v * 100 for v in cum_f2p], marker=mk, linestyle=ls,
                 color=c, label=label, linewidth=2, markersize=6)
        ax.fill_between(x,
                       [lo * 100 for lo in lower],
                       [hi * 100 for hi in upper],
                       color=c, alpha=0.15)
        ax.axhline(0, color="gray", linewidth=0.5, linestyle=":")

    ax.set_xlabel("rollout count (buildable issues)")
    ax.set_ylabel("cumulative f2p rate (%)")
    ax.set_title("Cumulative pass@1 as rollout count grows\n"
                 "(shaded = 95% CI; buildable rollouts only)")
    ax.legend(fontsize=9, framealpha=0.95)
    ax.set_ylim(-5, 60)
    ax.grid(True, alpha=0.3)

    # Right: stacked outcome bars per combo
    ax2 = axes[1]
    sorted_combos = sorted(combos.keys())
    outcomes_order = ["f2p", "p2p", "p2f", "f2f", "error"]
    oc = {"f2p": "#2ecc71", "p2p": "#3498db", "p2f": "#e74c3c",
          "f2f": "#f39c12", "error": "#7f8c8d"}
    x = np.arange(len(sorted_combos))
    width = 0.55
    bottom = np.zeros(len(sorted_combos))
    for oc_name in outcomes_order:
        vals = np.array([
            sum(1 for r in combos[c] if r["has_patch"] == "True" and r["outcome"] == oc_name)
            for c in sorted_combos
        ])
        ax2.bar(x, vals, width, bottom=bottom,
                 label=oc_name, color=oc[oc_name], edgecolor="black", linewidth=0.4)
        for i, v in enumerate(vals):
            if v > 0:
                ax2.text(i, bottom[i] + v / 2, str(v),
                         ha="center", va="center", fontsize=9,
                         fontweight="bold", color="white")
        bottom += vals
    ax2.set_xticks(x)
    ax2.set_xticklabels([f"{a[:5]}\n{s}" for a, s in sorted_combos], fontsize=9)
    ax2.set_ylabel("count")
    ax2.set_title("Outcome breakdown (buildable rollouts)")
    ax2.legend(fontsize=9, framealpha=0.95, loc="upper right")
    plt.tight_layout()
    out1 = OUT_DIR / "pilot20_cumulative_pass1.png"
    fig.savefig(out1, dpi=150)
    plt.close(fig)
    print(f"wrote {out1}")

    # --- Figure 2: per-issue heatmap ---------------------------------
    # Which issues were fixed by which (agent, skill)?
    # Rows = issues, Cols = (agent, skill), Cell = outcome
    issues = sorted(set(r["issue"] for r in rows if r["has_patch"] == "True"))
    if not issues:
        print("no buildable issues — skipping heatmap")
        return 0

    # Group by repo for row ordering
    issue_repo = {r["issue"]: r["repo"].split("/")[-1] for r in rows}
    issues.sort(key=lambda i: (issue_repo[i], i))

    combo_labels = sorted(combos.keys())
    n_issues = len(issues)

    fig2, ax3 = plt.subplots(figsize=(max(8, len(combo_labels) * 1.2 + 2), max(4, n_issues * 0.5 + 1)))
    # outcome → numeric for color
    val_map = {"f2p": 4, "p2p": 3, "p2f": 2, "f2f": 1, "error": 0, "": -1}
    cmap = matplotlib.colors.ListedColormap(
        ["#bdc3c7", "#e74c3c", "#f39c12", "#3498db", "#2ecc71"][::-1])
    data = np.full((n_issues, len(combo_labels)), -1)
    for j, combo in enumerate(combo_labels):
        for i, issue in enumerate(issues):
            for r in combos[combo]:
                if r["issue"] == issue:
                    data[i, j] = val_map.get(r["outcome"] or "", -1)
                    break

    im = ax3.imshow(data, aspect="auto", cmap=cmap, vmin=-1, vmax=4)
    ax3.set_xticks(np.arange(len(combo_labels)))
    ax3.set_xticklabels([f"{a[:5]}\n{s}" for a, s in combo_labels], fontsize=9)
    ax3.set_yticks(np.arange(n_issues))
    repo_labels = [f"{issue_repo[i]}/{i.split('-')[1]}" for i in issues]
    ax3.set_yticklabels(repo_labels, fontsize=8)
    ax3.set_title("Per-issue outcome heatmap (buildable rollouts only)\n"
                   "green=f2p, blue=p2p, orange=f2f, red=error/no_patch")
    # Legend
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor="#2ecc71", label="f2p (fixed)"),
        Patch(facecolor="#3498db", label="p2p (already passed)"),
        Patch(facecolor="#f39c12", label="f2f (still failing)"),
        Patch(facecolor="#e74c3c", label="error / no fix"),
        Patch(facecolor="#bdc3c7", label="no patch"),
    ]
    ax3.legend(handles=legend_elements, loc="upper left", fontsize=8,
               bbox_to_anchor=(1.01, 1), framealpha=0.95)
    plt.tight_layout()
    out2 = OUT_DIR / "pilot20_heatmap.png"
    fig2.savefig(out2, dpi=150)
    plt.close(fig2)
    print(f"wrote {out2}")

    # --- Update breakdown text ----------------------------------------
    out3 = OUT_DIR / "pilot20_breakdown.txt"
    with out3.open("w") as f:
        f.write("RQ4 pilot-20 breakdown\n")
        f.write("=" * 50 + "\n\n")
        total = len(rows)
        buildable_total = sum(1 for r in rows if r["has_patch"] == "True")
        f.write(f"Total rollouts: {total}\n")
        f.write(f"Buildable (docker OK + patch produced): {buildable_total} "
                f"({100*buildable_total/max(total,1):.1f}%)\n\n")
        for (agent, skill), rlist in sorted(combos.items()):
            n_all = len(rlist)
            n_build = sum(1 for r in rlist if r["has_patch"] == "True")
            f.write(f"{agent}  {skill}_skill  (n={n_all} total, {n_build} buildable)\n")
            c = Counter(r["outcome"] for r in rlist if r["has_patch"] == "True")
            for oc in ["f2p", "p2p", "p2f", "f2f", "error"]:
                v = c.get(oc, 0)
                if v:
                    f.write(f"   {oc:9s}: {v}\n")
            f2p = c.get("f2p", 0)
            f.write(f"   pass@1   = {100*f2p/max(n_build,1):.1f}%\n\n")
    print(f"wrote {out3}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
