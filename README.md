

## Contents

```
autoscale-demo/
├── src/                       Spring Boot application (endpoint /work)
├── Dockerfile                 multi-stage build (Maven 3.9 + Eclipse Temurin 17 JRE)
├── k8s/                       Deployment, Service, HPA manifests
└── experiments/joiv48/        everything needed to reproduce the paper
    ├── study1/                Alibaba cluster-trace-v2018 analysis (DuckDB)
    │   ├── trace_analysis.py
    │   └── buckets_100k_180k.csv
    ├── study2/                load-test protocol and analysis
    │   ├── workload.js        k6 script (warm-up + measurement phase)
    │   ├── run_steps.sh       repeated fixed-replica step-load runs
    │   ├── server_side.py     aligned Prometheus query + access log + CPU throttling
    │   ├── summarize.py       mean ± 95% CI tables
    │   └── results_v3/        raw results of the 33 runs reported in the paper
    └── figures/               scripts for Figs. 1–3
```

---

## The service

| Endpoint | Purpose |
|---|---|
| `GET /work?ms=5` | Keeps one CPU core busy computing `sqrt(random)` until `ms` milliseconds of **wall-clock** time have passed, then returns `ok:<value>`. |
| `GET /health` | Readiness/liveness probe. |
| `GET /actuator/prometheus` | Prometheus metrics: `http_server_requests_seconds_count` / `_bucket` (Micrometer), with percentile histograms enabled. |

**Important property of `/work`.** The loop is bounded by elapsed time, not by a fixed amount of work. When threads
compete for the pod's CPU quota, each request still takes about `ms` inside the handler, but does *less* CPU work.
Consequences, both discussed in the paper:

- the server-side latency timer stays close to `ms` by construction, while waiting *before* the handler grows with load;
- at 5 ms of CPU per request the offered demand is **0.005 cores per RPS**, so a pod limited to 500m CPU saturates at
  about **100 RPS**.

### Configuration (`src/main/resources/application.properties`)

```properties
server.port=8080
management.endpoints.web.exposure.include=health,prometheus
management.metrics.export.prometheus.enabled=true
management.metrics.distribution.percentiles-histogram.http.server.requests=true

# Tomcat access log to stdout: independent server-side latency (%D = microseconds on Tomcat 10.1)
server.tomcat.accesslog.enabled=true
server.tomcat.accesslog.directory=/dev
server.tomcat.accesslog.prefix=stdout
server.tomcat.accesslog.suffix=
server.tomcat.accesslog.file-date-format=
server.tomcat.accesslog.pattern=%{yyyy-MM-dd'T'HH:mm:ss.SSSZ}t "%r" %s %D
```

Tomcat runs with its defaults (200 worker threads, accept queue 100). Pods request 250m CPU / 512 MiB and are limited
to 500m CPU / 768 MiB.

---

## Testbed used in the paper

| Component | Version / setting |
|---|---|
| Host | Apple MacBook Air, M2 (8 cores), 16 GB |
| Cluster | Minikube v1.39.0, single node, Docker driver, containerd runtime, 8 CPUs |
| Kubernetes | v1.37.0 |
| Application | Spring Boot 3.3.2, embedded Apache Tomcat 10.1, Java 17 (Eclipse Temurin 17 JRE, default JVM options) |
| Monitoring | kube-prometheus-stack (Prometheus scrape interval 5 s) |
| Load generator | Grafana k6 v0.54.0, in-cluster pod, no resource limits, `constant-arrival-rate` (open loop), 300 pre-allocated VUs |

---

## Reproducing Study 2 (capacity and server–client latency)

### 1. Start the cluster and monitoring

```bash
minikube start
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
kubectl create namespace monitoring
helm install prometheus prometheus-community/kube-prometheus-stack -n monitoring
```

### 2. Build and deploy the service

```bash
minikube image build -t autoscale-demo:v2 .
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl patch deploy autoscale-demo --type=json -p='[{"op":"replace","path":"/spec/template/spec/containers/0/image","value":"autoscale-demo:v2"},{"op":"replace","path":"/spec/template/spec/containers/0/imagePullPolicy","value":"Never"}]'
kubectl rollout status deploy/autoscale-demo
```

> If `docker build` fails with a `moby/buildkit` error after `eval $(minikube docker-env)`, use
> `minikube image build` as above.

### 3. Remove the HPA (fixed-replica runs only)

```bash
kubectl get hpa -A
kubectl delete hpa autoscale-demo
```

### 4. Make Prometheus reachable (keep this terminal open)

```bash
while true; do kubectl -n monitoring port-forward svc/prometheus-kube-prometheus-prometheus 9090:9090; sleep 2; done
```

### 5. Run the repeated step-load profile (~2.5 h)

```bash
python3 -m venv ~/joiv-venv && source ~/joiv-venv/bin/activate
pip install requests numpy scipy pandas matplotlib
cd experiments/joiv48/study2
caffeinate -dimsu bash run_steps.sh
```

For each replica count (1, 2), target rate (50-RPS steps) and repetition (3), the script:

1. restarts the deployment (fresh JVM) and waits until it is Ready;
2. runs k6 for a **60-s warm-up (discarded)** and a **120-s measurement window**;
3. computes the server-side p95/p99 over **exactly the k6 window**:
   ```
   histogram_quantile(0.99, sum by (le) (increase(http_server_requests_seconds_bucket{uri="/work"}[120s])))
   ```
   evaluated at the window end;
4. computes p95/p99 from the **Tomcat access log** over the same window;
5. records the **CPU throttling ratio** (`container_cpu_cfs_throttled_periods_total / container_cpu_cfs_periods_total`),
   per-pod request rates, request counts and k6 `dropped_iterations`.

Quick check before the full run (one step, ~2 min):

```bash
REPLICA_LIST=1 RATES_1=50 REPS=1 WARMUP=20 MEASURE=30 bash run_steps.sh
cat results/runs.jsonl
```

The request counts from k6 (`achieved_rps × measure_s`), Prometheus (`srv_count`) and the access log (`alog_n`) should
agree; if they do not, the windows are not aligned.

### 6. Summarize and plot

```bash
python3 summarize.py results/runs.jsonl
python3 ../figures/fig3_latency.py results/runs.jsonl
```

---

## Results reported in the paper (3 runs per step, mean)

| Pods | Target RPS | k6 p99 (ms) | Prometheus p99 (ms) | Access-log p99 (ms) | CPU throttled | Errors | SLO (p99 ≤ 200 ms, 0 errors) |
|---|---|---|---|---|---|---|---|
| 1 | 50 | 17.7 | 13.8 | 13.3 | 3% | 0% | 3/3 |
| 1 | 100 | 89.6 | 64.2 | 62.5 | 91% | 0% | 3/3 |
| 1 | 150 | 975 | 491 | 513 | 100% | 0% | 0/3 |
| 1 | 200 | 6,402 | 918 | 6,056 | 100% | 2.5% | 0/3 |
| 2 | 50 | 6.0 | 5.6 | 5.8 | 0% | 0% | 3/3 |
| 2 | 100 | 18.6 | 12.8 | 12.0 | 4% | 0% | 3/3 |
| 2 | 150 | 33.6 | 26.3 | 27.0 | 11% | 0% | 3/3 |
| 2 | 200 | 54.5 | 39.3 | 40.6 | 54% | 0% | 3/3 |
| 2 | 250 | 247 | 163 | 165 | 96% | 0% | 1/3 |
| 2 | 300 | 567 | 340 | 334 | 100% | 0% | 0/3 |
| 2 | 350 | 3,759 | 911 | 1,503 | 100% | 0.3% | 0/3 |

Key findings:

- **SLO capacity:** 100 RPS (1 pod) and 200 RPS (2 pods), matching the 500m CPU limit. Single 90-s runs without
  warm-up had suggested 150 and 300 RPS.
- **Server–client gap:** with aligned windows, server-side p99 is 1.1–2.0× below client p99 until overload. An earlier
  reading from Grafana panels whose rate window did not match the k6 step suggested 17–34× — a measurement artifact.
- **Overload:** the Prometheus p99 falls far below both the access log and k6 (e.g. 918 vs 6,056 vs 6,402 ms).
- **Error-free SLO violations:** every violation up to 300 RPS had 0% errors.

Raw data: `experiments/joiv48/study2/results_v3/`.

---

## Reproducing Study 1 (Alibaba cluster-trace-v2018)

Download `container_usage.csv` and `container_meta.csv` from
[alibaba/clusterdata](https://github.com/alibaba/clusterdata/tree/master/cluster-trace-v2018) (~4.02 billion usage
records; keep ~150 GB free disk), then:

```bash
pip install duckdb pandas matplotlib
python experiments/joiv48/study1/trace_analysis.py \
  --usage /path/to/container_usage.csv --meta /path/to/container_meta.csv \
  --out results_study1 --db /path/to/trace.duckdb --mem 8GB --threads 8
python experiments/joiv48/figures/fig2_burst.py results_study1/buckets_100k_180k.csv fig2.png
```

Outputs: per-application-group Pearson r, Spearman ρ, median per-container r, within-container lagged r (Table I),
and 1000-s buckets with record, container and application counts (Table II, Fig. 2).


```

