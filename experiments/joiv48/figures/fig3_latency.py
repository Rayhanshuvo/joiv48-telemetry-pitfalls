#!/usr/bin/env python3
"""
Fig. 3 (revised): client-side vs server-side p99 latency against target rate.
Fix requested by Reviewer 1 (criterion 9, item 3): the legend is placed BELOW the
axes so it cannot cover the one-pod 200 RPS points.

Usage:
  python fig3_latency.py                     # original single-run values (Tables III-IV, v2)
  python fig3_latency.py summary_long.csv    # repeated runs: means with 95% CI error bars
"""
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ORIGINAL = {  # target: (k6 p99, server p99) in ms, from the submitted Tables III and IV
    1: {50: (5.69, 5.58), 100: (10.02, 10.30), 150: (114.46, 97.30), 200: (3310, 3460)},
    2: {50: (6.46, 5.58), 100: (6.29, 5.59), 150: (18.62, 6.08), 200: (20.70, 16.3),
        250: (95.32, 5.57), 300: (192.29, 5.70), 350: (468.88, 343)},
}
FIRST_FAIL = {1: 200, 2: 350}
COL = {1: "#1f4e79", 2: "#c45a12"}

plt.rcParams.update({"font.family": "serif", "font.size": 8, "axes.linewidth": 0.6})
fig, ax = plt.subplots(figsize=(3.4, 2.9))

if len(sys.argv) > 1:
    L = pd.read_csv(sys.argv[1])
    for rep in (1, 2):
        t = L[L.replicas == rep].sort_values("target")
        ax.errorbar(t.target, t.p99_ms_mean, yerr=t.p99_ms_ci95.fillna(0), color=COL[rep], marker="o",
                    ms=3, lw=1.1, capsize=2, label=f"{rep} pod{'s' if rep == 2 else ''}, client (k6)")
        ax.errorbar(t.target, t.srv_p99_ms_mean, yerr=t.srv_p99_ms_ci95.fillna(0), color=COL[rep], marker="s",
                    ms=3, lw=1.1, ls="--", capsize=2, label=f"{rep} pod{'s' if rep == 2 else ''}, server (Prometheus)")
else:
    for rep in (1, 2):
        x = sorted(ORIGINAL[rep])
        ax.plot(x, [ORIGINAL[rep][r][0] for r in x], color=COL[rep], marker="o", ms=3, lw=1.1,
                label=f"{rep} pod{'s' if rep == 2 else ''}, client (k6)")
        ax.plot(x, [ORIGINAL[rep][r][1] for r in x], color=COL[rep], marker="s", ms=3, lw=1.1, ls="--",
                mfc="white", label=f"{rep} pod{'s' if rep == 2 else ''}, server (Prometheus)")

for rep, r in FIRST_FAIL.items():
    ax.axvspan(r - 20, r + 20, color=COL[rep], alpha=0.08, lw=0)
ax.axhline(200, color="#666", lw=0.7, ls=":")
ax.text(52, 230, "SLO 200 ms", fontsize=6.5, color="#555")
ax.set_yscale("log")
ax.set_xlabel("Target request rate (RPS)")
ax.set_ylabel("p99 latency (ms, log scale)")
ax.set_xticks([50, 100, 150, 200, 250, 300, 350])
ax.grid(alpha=0.25, lw=0.4)
ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=2, frameon=False, fontsize=6.5,
          handlelength=2.4, columnspacing=1.0)
fig.tight_layout()
dst = "fig3.png"
fig.savefig(dst, dpi=600, bbox_inches="tight")
fig.savefig("fig3.pdf", bbox_inches="tight")
print("wrote", dst)
