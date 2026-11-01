#!/usr/bin/env python3
"""Fig. 1 (revised): research workflow, wording aligned with the revised title/objectives."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

BLUE, ORANGE, GREY = "#1f4e79", "#c45a12", "#333333"
FILL = {BLUE: "#e9f0f8", ORANGE: "#fbece3"}

plt.rcParams.update({"font.family": "serif", "font.size": 9})
fig, ax = plt.subplots(figsize=(6.4, 5.6))
ax.set_xlim(0, 100); ax.set_ylim(0, 108); ax.axis("off")


def box(x, y, w, h, text, ec, fill=True, fs=7.4):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.4,rounding_size=1.2",
                                ec=ec, fc=FILL.get(ec, "#f2f2f2") if fill else "white", lw=1.2))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, linespacing=1.25)


def arrow(x0, y0, x1, y1):
    ax.annotate("", xy=(x1, y1), xytext=(x0, y0),
                arrowprops=dict(arrowstyle="-|>", color=GREY, lw=1.0, mutation_scale=9))


def study(y0, title, color, src, top, bot, out_top, out_bot):
    ax.text(1, y0 + 41, title, color=color, fontsize=8.6, fontweight="bold")
    box(1, y0, 25, 36, src, color)
    box(34, y0 + 20, 32, 15, top, color)
    box(34, y0 + 1, 32, 15, bot, color)
    box(73, y0 + 20, 26, 15, out_top, color, fill=False)
    box(73, y0 + 1, 26, 15, out_bot, color, fill=False)
    arrow(27, y0 + 19, 33.5, y0 + 27); arrow(27, y0 + 17, 33.5, y0 + 9)
    arrow(67, y0 + 27.5, 72.5, y0 + 27.5); arrow(67, y0 + 8.5, 72.5, y0 + 8.5)


study(60, "Study 1: production telemetry (Alibaba cluster-trace-v2018)", BLUE,
      "Container usage\nrecords: CPU,\nnet_in, net_out;\napp_du group;\ninvalid values\nremoved",
      "Pearson r, Spearman ρ,\nper-container and\nlagged r; top 20\napp groups (Eq. 1)",
      "1000-s buckets:\nU(b), N$_{rec}$, N$_{cont}$, N$_{app}$\n(Eq. 2)",
      "CPU–network\ncoupling", "Burst: real event\nor reporting\nartifact?")
study(12, "Study 2: controlled experiment (Kubernetes)", ORANGE,
      "Service with\n1 and 2 pods;\nk6 open-loop load,\n50-RPS steps;\nwarm-up + repeated\nruns",
      "Client view (k6):\np95, p99, errors,\nachieved RPS, dropped",
      "Server view (Prometheus\nhistogram, access log):\np95, p99",
      "SLO capacity range\nper configuration", "Latency gap\nratio G (Eq. 3)")
arrow(50, 12.5, 50, 9.5)
box(1, 0.5, 98, 8, "Implications for automated operations (autoscalers, AIOps agents):\n"
    "check population counts; combine several signals; judge SLOs from the client side",
    GREY, fill=True, fs=7.4)
fig.savefig("fig1.png", dpi=600, bbox_inches="tight")
fig.savefig("fig1.pdf", bbox_inches="tight")
print("wrote fig1.png")
