#!/usr/bin/env python3
"""
Study 1 re-analysis for the JOIV48 revision (Alibaba cluster-trace-v2018).

Addresses Reviewer 1, criterion 4 (items 1-2):
  * removes invalid values (trace docs: invalid values are coded -1 or 101;
    net_in/net_out are normalised to [0, 100])
  * pooled Pearson r per application group (app_du)          -> Table I, existing columns
  * Spearman rho per application group (average ranks for ties)
  * median (IQR) of per-container Pearson r (containers with >= MIN_REC records)
  * within-container (demeaned) correlation at lags -K..+K samples
  * 1000-s bucket aggregation with population counts          -> Table II, Fig. 2

Input files (no header, as distributed by Alibaba):
  container_usage.csv : container_id, machine_id, time_stamp, cpu_util_percent,
                        mem_util_percent, cpi, mem_gps, mpki, net_in, net_out, disk_io_percent
  container_meta.csv  : container_id, machine_id, time_stamp, app_du, status,
                        cpu_request, cpu_limit, mem_size

Usage:
  pip install duckdb pandas
  python trace_analysis.py --usage container_usage.csv --meta container_meta.csv --out results/
  (add --top 20 --min-rec 100 --max-lag 6 --mem 24GB --threads 8 as needed)

Outputs (CSV) in --out:
  table1_correlations.csv  app, records, r_in, r_out, rho_in, rho_out,
                           med_rc_in, q1_rc_in, q3_rc_in, n_containers,
                           r_within_in, best_lag, r_best_lag
  lagged_within_r.csv      app, lag, r_within_in, r_within_out
  buckets_100k_180k.csv    bucket_start, n_records, n_containers, n_apps, avg_cpu
  invalid_counts.csv       how many records were removed and why
"""
import argparse
import os

import duckdb

USAGE_COLS = ["container_id", "machine_id", "time_stamp", "cpu", "mem", "cpi",
              "mem_gps", "mpki", "net_in", "net_out", "disk_io"]
META_COLS = ["container_id", "machine_id", "time_stamp", "app_du", "status",
             "cpu_request", "cpu_limit", "mem_size"]


def cols_sql(cols, types):
    return "{" + ", ".join(f"'{c}': '{t}'" for c, t in zip(cols, types)) + "}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--usage", required=True)
    ap.add_argument("--meta", required=True)
    ap.add_argument("--out", default="results")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--min-rec", type=int, default=100)
    ap.add_argument("--max-lag", type=int, default=6)
    ap.add_argument("--bucket", type=int, default=1000)
    ap.add_argument("--t0", type=int, default=100_000)
    ap.add_argument("--t1", type=int, default=180_000)
    ap.add_argument("--mem", default="16GB")
    ap.add_argument("--threads", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--db", default="trace.duckdb", help="on-disk DB so work can spill")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    con = duckdb.connect(a.db)
    con.execute(f"SET memory_limit='{a.mem}'; SET threads={a.threads}; SET preserve_insertion_order=false;")

    utypes = ["VARCHAR", "VARCHAR", "DOUBLE", "DOUBLE", "DOUBLE", "DOUBLE",
              "DOUBLE", "DOUBLE", "DOUBLE", "DOUBLE", "DOUBLE"]
    mtypes = ["VARCHAR", "VARCHAR", "DOUBLE", "VARCHAR", "VARCHAR", "DOUBLE", "DOUBLE", "DOUBLE"]

    print("[1/6] loading usage + meta ...")
    con.execute(f"""
        CREATE OR REPLACE TABLE usage_raw AS
        SELECT * FROM read_csv('{a.usage}', header=false, columns={cols_sql(USAGE_COLS, utypes)},
                               nullstr='', ignore_errors=true)
    """)
    con.execute(f"""
        CREATE OR REPLACE TABLE meta AS
        SELECT container_id, any_value(app_du) AS app
        FROM read_csv('{a.meta}', header=false, columns={cols_sql(META_COLS, mtypes)}, nullstr='')
        WHERE app_du IS NOT NULL
        GROUP BY container_id
    """)

    print("[2/6] removing invalid values (-1 / 101 / NULL / outside [0,100]) ...")
    con.execute("""
        CREATE OR REPLACE TABLE invalid_counts AS
        SELECT count(*) AS total_records,
               count(*) FILTER (WHERE cpu IS NULL OR cpu < 0 OR cpu > 100) AS bad_cpu,
               count(*) FILTER (WHERE net_in IS NULL OR net_in < 0 OR net_in > 100) AS bad_net_in,
               count(*) FILTER (WHERE net_out IS NULL OR net_out < 0 OR net_out > 100) AS bad_net_out
        FROM usage_raw
    """)
    con.execute("""
        CREATE OR REPLACE TABLE u AS
        SELECT r.container_id, m.app, r.time_stamp AS ts, r.cpu, r.net_in, r.net_out
        FROM usage_raw r JOIN meta m USING (container_id)
        WHERE r.cpu BETWEEN 0 AND 100
          AND r.net_in BETWEEN 0 AND 100
          AND r.net_out BETWEEN 0 AND 100
    """)
    con.execute("COPY invalid_counts TO '{}' (HEADER)".format(os.path.join(a.out, "invalid_counts.csv")))

    # NOTE: Table II / Fig. 2 must use the SAME population definition as before.
    # Buckets are computed on all valid-CPU records (network validity not required).
    print("[3/6] 1000-s buckets with population counts ...")
    con.execute(f"""
        COPY (
          SELECT CAST(floor(r.time_stamp / {a.bucket}) * {a.bucket} AS BIGINT) AS bucket_start,
                 count(*) AS n_records,
                 count(DISTINCT r.container_id) AS n_containers,
                 count(DISTINCT m.app) AS n_apps,
                 round(avg(r.cpu), 2) AS avg_cpu
          FROM usage_raw r LEFT JOIN meta m USING (container_id)
          WHERE r.time_stamp >= {a.t0} AND r.time_stamp < {a.t1 + a.bucket}
            AND r.cpu BETWEEN 0 AND 100
          GROUP BY 1 ORDER BY 1
        ) TO '{os.path.join(a.out, "buckets_100k_180k.csv")}' (HEADER)
    """)

    print("[4/6] top application groups + pooled Pearson ...")
    con.execute(f"""
        CREATE OR REPLACE TABLE top AS
        SELECT app, count(*) AS records,
               corr(cpu, net_in) AS r_in, corr(cpu, net_out) AS r_out
        FROM u GROUP BY app ORDER BY records DESC LIMIT {a.top}
    """)
    con.execute("CREATE OR REPLACE TABLE ut AS SELECT u.* FROM u JOIN top USING (app)")

    print("[5/6] Spearman (average ranks) + per-container r ...")

    def avg_rank_table(col):
        # average rank for ties: rank of a value = cum_count - (n_tied - 1)/2
        return f"""
          SELECT app, {col} AS v,
                 sum(n) OVER (PARTITION BY app ORDER BY {col}) - (n - 1) / 2.0 AS rk
          FROM (SELECT app, {col}, count(*) AS n FROM ut GROUP BY app, {col})
        """
    con.execute(f"""
        CREATE OR REPLACE TABLE rho AS
        WITH rc AS ({avg_rank_table('cpu')}),
             ri AS ({avg_rank_table('net_in')}),
             ro AS ({avg_rank_table('net_out')})
        SELECT ut.app,
               corr(rc.rk, ri.rk) AS rho_in,
               corr(rc.rk, ro.rk) AS rho_out
        FROM ut
        JOIN rc ON rc.app = ut.app AND rc.v = ut.cpu
        JOIN ri ON ri.app = ut.app AND ri.v = ut.net_in
        JOIN ro ON ro.app = ut.app AND ro.v = ut.net_out
        GROUP BY ut.app
    """)
    con.execute(f"""
        CREATE OR REPLACE TABLE percont AS
        WITH c AS (
          SELECT app, container_id, count(*) AS n, corr(cpu, net_in) AS rc_in, corr(cpu, net_out) AS rc_out
          FROM ut GROUP BY app, container_id
          HAVING count(*) >= {a.min_rec}
        )
        SELECT app, count(*) FILTER (WHERE rc_in IS NOT NULL) AS n_containers,
               quantile_cont(rc_in, 0.5)  AS med_rc_in,
               quantile_cont(rc_in, 0.25) AS q1_rc_in,
               quantile_cont(rc_in, 0.75) AS q3_rc_in,
               quantile_cont(rc_out, 0.5) AS med_rc_out
        FROM c WHERE rc_in IS NOT NULL GROUP BY app
    """)

    print("[6/6] within-container lagged correlations ...")
    # demean within container, then lag inside each container ordered by time
    con.execute("""
        CREATE OR REPLACE TABLE dm AS
        SELECT app, container_id, ts,
               cpu - avg(cpu) OVER w AS x,
               net_in - avg(net_in) OVER w AS yi,
               net_out - avg(net_out) OVER w AS yo
        FROM ut WINDOW w AS (PARTITION BY container_id)
    """)
    rows = []
    for k in range(-a.max_lag, a.max_lag + 1):
        # positive k: network leads CPU by k samples (CPU at t vs network at t-k)
        fn = "lag" if k >= 0 else "lead"
        kk = abs(k)
        q = f"""
          SELECT app, {k} AS lag,
                 corr(x, yi_l) AS r_within_in, corr(x, yo_l) AS r_within_out
          FROM (SELECT app, x,
                       {fn}(yi, {kk}) OVER (PARTITION BY container_id ORDER BY ts) AS yi_l,
                       {fn}(yo, {kk}) OVER (PARTITION BY container_id ORDER BY ts) AS yo_l
                FROM dm)
          GROUP BY app
        """
        rows.append(con.execute(q).df())
        print(f"   lag {k:+d} done")
    import pandas as pd
    lag = pd.concat(rows, ignore_index=True).sort_values(["app", "lag"])
    lag.to_csv(os.path.join(a.out, "lagged_within_r.csv"), index=False)

    best = (lag.assign(absr=lag.r_within_in.abs())
               .sort_values("absr", ascending=False)
               .groupby("app").head(1)[["app", "lag", "r_within_in"]]
               .rename(columns={"lag": "best_lag", "r_within_in": "r_best_lag"}))
    lag0 = lag[lag.lag == 0][["app", "r_within_in"]]

    t1 = (con.execute("SELECT * FROM top").df()
            .merge(con.execute("SELECT * FROM rho").df(), on="app", how="left")
            .merge(con.execute("SELECT * FROM percont").df(), on="app", how="left")
            .merge(lag0, on="app", how="left")
            .merge(best, on="app", how="left")
            .sort_values("records", ascending=False))
    t1.round(3).to_csv(os.path.join(a.out, "table1_correlations.csv"), index=False)
    print(t1.round(3).to_string(index=False))
    print("\nDone. Compare r_in/r_out with the published Table I; if the invalid-value filter changes them, update Table I.")


if __name__ == "__main__":
    main()
