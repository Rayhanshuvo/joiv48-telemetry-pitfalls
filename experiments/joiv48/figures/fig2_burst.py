#!/usr/bin/env python3
"""
Fig. 2 (revised) - population-aware validation of the apparent burst.
Fixes requested by Reviewer 1 (criterion 9, item 2):
  * no title inside the plot (the caption carries it)
  * lines are BROKEN where buckets have no records (156,000-159,000 s),
    so the plot no longer implies data exist there
  * 600 dpi PNG + vector PDF

Usage: python fig2_burst.py ../study1/results/buckets_100k_180k.csv fig2.png
"""
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import LogLocator, NullFormatter

src = sys.argv[1] if len(sys.argv) > 1 else "buckets_100k_180k.csv"
dst = sys.argv[2] if len(sys.argv) > 2 else "fig2.png"
STEP, T0, T1 = 1000, 100_000, 180_000

df = pd.read_csv(src).set_index("bucket_start")
full = pd.DataFrame(index=np.arange(T0, T1 + STEP, STEP))
df = full.join(df)  # missing buckets -> NaN -> matplotlib breaks the line

plt.rcParams.update({"font.family": "serif", "font.size": 8, "axes.linewidth": 0.6})
fig, axes = plt.subplots(4, 1, figsize=(3.4, 4.6), sharex=True, constrained_layout=True)
panels = [("n_records", "Records", True, "#1f4e79"),
          ("n_containers", "Active\ncontainers", True, "#b5531a"),
          ("n_apps", "Active\napplications", True, "#2e7d32"),
          ("avg_cpu", "Avg. CPU (%)", False, "#6a1b9a")]
x = df.index / 1000.0
for ax, (col, lab, log, c) in zip(axes, panels):
    ax.plot(x, df[col], color=c, lw=0.9, marker="o", ms=1.6)
    if log:
        ax.set_yscale("log")
        ax.yaxis.set_major_locator(LogLocator(base=10, numticks=10))
        ax.yaxis.set_minor_formatter(NullFormatter())
    ax.set_ylabel(lab)
    ax.axvspan(142, 161, color="#d62728", alpha=0.10, lw=0)       # collapse window
    ax.axvspan(156, 160, facecolor="none", hatch="////", edgecolor="#888888", lw=0)  # no data
    ax.grid(alpha=0.25, lw=0.4)
axes[-1].set_xlabel("Trace time (×10$^3$ s)")
axes[0].text(158, axes[0].get_ylim()[1], "no data", ha="center", va="bottom", fontsize=6, color="#555")
fig.savefig(dst, dpi=600)
fig.savefig(dst.rsplit(".", 1)[0] + ".pdf")
print("wrote", dst)
