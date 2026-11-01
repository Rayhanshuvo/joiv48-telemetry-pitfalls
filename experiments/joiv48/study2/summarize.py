#!/usr/bin/env python3
"""
Summarise repeated load-test runs into Tables III/IV (mean +/- 95% CI, t-distribution).

Usage: python summarize.py results/runs.jsonl  [--slo-ms 200]
Writes results/table3_one_pod.csv, results/table4_two_pods.csv, results/summary_long.csv
and prints the rows ready to paste into the manuscript.

Columns per (replicas, target rate):
  achieved RPS, k6 p95, k6 p99, Srv p95, Srv p99, access-log p99, error %, dropped iterations,
  gap ratio G = k6_p99 / Srv_p99 (computed per run, then averaged), CPU throttled %,
  SLO = Pass only if ALL repetitions pass (k6 p99 <= SLO and error rate == 0).
"""
import argparse
import json
import os

import numpy as np
import pandas as pd
from scipy import stats


def ci(x):
    x = np.asarray([v for v in x if v is not None and not np.isnan(v)], float)
    n = len(x)
    if n == 0:
        return np.nan, np.nan, 0
    m = x.mean()
    if n == 1:
        return m, np.nan, 1
    h = stats.t.ppf(0.975, n - 1) * x.std(ddof=1) / np.sqrt(n)
    return m, h, n


def fmt(m, h, digits=2):
    if np.isnan(m):
        return "n/a"
    return f"{m:,.{digits}f}" if np.isnan(h) else f"{m:,.{digits}f} ± {h:,.{digits}f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs")
    ap.add_argument("--slo-ms", type=float, default=200.0)
    a = ap.parse_args()
    rows = [json.loads(l) for l in open(a.runs) if l.strip()]
    df = pd.DataFrame(rows)
    df["G"] = df["p99_ms"] / df["srv_p99_ms"]
    df["G_alog"] = df["p99_ms"] / df["alog_p99_ms"]
    df["err_pct"] = 100 * df["error_rate"]
    df["pass"] = (df["p99_ms"] <= a.slo_ms) & (df["error_rate"] == 0)
    outdir = os.path.dirname(os.path.abspath(a.runs))

    long = []
    for (rep, rate), g in df.groupby(["replicas", "rate_target"]):
        rec = {"replicas": rep, "target": rate, "n_runs": len(g)}
        for col in ["achieved_rps", "p95_ms", "p99_ms", "srv_p95_ms", "srv_p99_ms",
                    "alog_p99_ms", "err_pct", "dropped_iterations_measure", "G", "G_alog",
                    "cpu_throttled_ratio"]:
            m, h, n = ci(g[col].tolist())
            rec[col + "_mean"], rec[col + "_ci95"] = m, h
        rec["SLO"] = "Pass" if g["pass"].all() else ("Fail" if not g["pass"].any() else f"Mixed ({g['pass'].sum()}/{len(g)})")
        long.append(rec)
    L = pd.DataFrame(long).sort_values(["replicas", "target"])
    L.to_csv(os.path.join(outdir, "summary_long.csv"), index=False)

    for rep, name in [(1, "table3_one_pod.csv"), (2, "table4_two_pods.csv")]:
        t = L[L.replicas == rep]
        pretty = pd.DataFrame({
            "Target": t.target,
            "Actual": [fmt(m, h) for m, h in zip(t.achieved_rps_mean, t.achieved_rps_ci95)],
            "k6 p95": [fmt(m, h) for m, h in zip(t.p95_ms_mean, t.p95_ms_ci95)],
            "k6 p99": [fmt(m, h) for m, h in zip(t.p99_ms_mean, t.p99_ms_ci95)],
            "Srv. p95": [fmt(m, h) for m, h in zip(t.srv_p95_ms_mean, t.srv_p95_ms_ci95)],
            "Srv. p99": [fmt(m, h) for m, h in zip(t.srv_p99_ms_mean, t.srv_p99_ms_ci95)],
            "Log p99": [fmt(m, h) for m, h in zip(t.alog_p99_ms_mean, t.alog_p99_ms_ci95)],
            "Err. (%)": [fmt(m, h) for m, h in zip(t.err_pct_mean, t.err_pct_ci95)],
            "Dropped": [fmt(m, h, 0) for m, h in zip(t.dropped_iterations_measure_mean, t.dropped_iterations_measure_ci95)],
            "G": [fmt(m, h, 1) for m, h in zip(t.G_mean, t.G_ci95)],
            "Throttled (%)": [fmt(100 * m, 100 * h, 1) for m, h in zip(t.cpu_throttled_ratio_mean, t.cpu_throttled_ratio_ci95)],
            "SLO": t.SLO,
        })
        pretty.to_csv(os.path.join(outdir, name), index=False)
        print(f"\n=== {rep} replica(s) ===")
        print(pretty.to_string(index=False))

    # SLO capacity bounds
    for rep in (1, 2):
        t = L[L.replicas == rep]
        failed = t[t.SLO != "Pass"].target
        hi = failed.min() if len(failed) else None          # first step that did not pass in all runs
        passed = t[(t.SLO == "Pass") & ((t.target < hi) if hi is not None else True)].target
        lo = passed.max() if len(passed) else None
        print(f"\nSLO capacity, {rep} pod(s): last passing step {lo} RPS, first failing step {hi} RPS")


if __name__ == "__main__":
    main()
