#!/usr/bin/env python3
"""
Server-side measurements for one load step, aligned to the k6 measurement window.

1. Prometheus histogram quantiles over EXACTLY the k6 window
   (fixes the truncated query and the window-misalignment issue):
     histogram_quantile(Q, sum by (le) (
         increase(http_server_requests_seconds_bucket{uri="/work"}[<W>s])))
   evaluated at the window end. `sum by (le)` merges the buckets of all pods first.
2. Tomcat access-log percentiles for the same window (independent server-side check).
   Enable in application.properties:
     server.tomcat.accesslog.enabled=true
     server.tomcat.accesslog.directory=/dev
     server.tomcat.accesslog.prefix=stdout
     server.tomcat.accesslog.suffix=
     server.tomcat.accesslog.file-date-format=
     server.tomcat.accesslog.pattern=%{yyyy-MM-dd'T'HH:mm:ss.SSSZ}t "%r" %s %D
   %D = processing time: microseconds on Tomcat 10+/Spring Boot 3, milliseconds on Tomcat 9.
3. CPU throttling ratio of the service container(s) during the window (cAdvisor metrics).
4. Request rate per pod (load-balance check for the 2-replica runs).
Prints one JSON line.
"""
import argparse
import datetime as dt
import json
import re
import subprocess

import numpy as np
import requests

URI = '/work'   # Spring MVC uri tag (query string is not part of the tag)


def prom(base, q, t):
    r = requests.get(f"{base}/api/v1/query", params={"query": q, "time": t}, timeout=30)
    r.raise_for_status()
    res = r.json()["data"]["result"]
    return res


def scalar(res):
    if not res:
        return None
    v = float(res[0]["value"][1])
    return None if np.isnan(v) else v


def access_log_percentiles(ns, selector, t_start, t_end, uri, unit_us=True):
    since = dt.datetime.fromtimestamp(t_start - 5, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    pods = subprocess.check_output(
        ["kubectl", "-n", ns, "get", "pods", "-l", selector, "-o", "jsonpath={.items[*].metadata.name}"],
        text=True).split()
    pat = re.compile(r'^(\S+) "[A-Z]+ ' + re.escape(uri) + r'[^"]*" (\d{3}) (\d+)')
    vals = []
    for p in pods:
        log = subprocess.check_output(["kubectl", "-n", ns, "logs", p, f"--since-time={since}"], text=True)
        for line in log.splitlines():
            m = pat.match(line.strip())
            if not m:
                continue
            ts = dt.datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S.%f%z").timestamp()
            if t_start <= ts <= t_end:
                d = float(m.group(3))
                vals.append(d / 1000.0 if unit_us else d)  # -> ms
    if not vals:
        return None, None, 0
    a = np.array(vals)
    return float(np.percentile(a, 95)), float(np.percentile(a, 99)), len(a)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k6", required=True)
    ap.add_argument("--prom", required=True)
    ap.add_argument("--ns", default="default")
    ap.add_argument("--selector", default="app=autoscale-demo")
    ap.add_argument("--container", default="autoscale-demo")
    ap.add_argument("--uri", default=URI)
    ap.add_argument("--replicas", type=int, required=True)
    ap.add_argument("--rep", type=int, required=True)
    ap.add_argument("--tomcat9", action="store_true", help="%%D in ms (Tomcat 9)")
    a = ap.parse_args()

    k6 = json.load(open(a.k6))
    t_start, t_end = k6["window_start_ms"] / 1000.0, k6["window_end_ms"] / 1000.0
    w = int(round(t_end - t_start))
    uri = a.uri
    sel = f'uri="{uri}"'

    out = dict(replicas=a.replicas, rep=a.rep, **k6)
    for q in (0.95, 0.99):
        query = (f'histogram_quantile({q}, sum by (le) '
                 f'(increase(http_server_requests_seconds_bucket{{{sel}}}[{w}s])))')
        v = scalar(prom(a.prom, query, t_end))
        out[f"srv_p{int(q*100)}_ms"] = None if v is None else v * 1000.0
    out["srv_query_p99"] = (f'histogram_quantile(0.99, sum by (le) '
                            f'(increase(http_server_requests_seconds_bucket{{{sel}}}[{w}s])))')

    # bucket boundaries actually exported (for the paper's Methods section)
    les = prom(a.prom, f'count by (le) (http_server_requests_seconds_bucket{{{sel}}})', t_end)
    out["histogram_le"] = sorted({r["metric"]["le"] for r in les}, key=lambda s: float("inf") if s == "+Inf" else float(s))

    # server request count in window (sanity check vs k6)
    out["srv_count"] = scalar(prom(a.prom, f'sum(increase(http_server_requests_seconds_count{{{sel}}}[{w}s]))', t_end))
    # per-pod rate (load balancing)
    per_pod = prom(a.prom, f'sum by (pod) (rate(http_server_requests_seconds_count{{{sel}}}[{w}s]))', t_end)
    out["per_pod_rps"] = {r["metric"].get("pod", "?"): float(r["value"][1]) for r in per_pod}
    # CFS throttling ratio during the window
    thr = prom(a.prom,
               f'sum(increase(container_cpu_cfs_throttled_periods_total{{namespace="{a.ns}",container="{a.container}"}}[{w}s]))'
               f' / sum(increase(container_cpu_cfs_periods_total{{namespace="{a.ns}",container="{a.container}"}}[{w}s]))',
               t_end)
    out["cpu_throttled_ratio"] = scalar(thr)

    p95, p99, n = access_log_percentiles(a.ns, a.selector, t_start, t_end, uri, unit_us=not a.tomcat9)
    out.update(alog_p95_ms=p95, alog_p99_ms=p99, alog_n=n)
    print(json.dumps(out))


if __name__ == "__main__":
    main()
