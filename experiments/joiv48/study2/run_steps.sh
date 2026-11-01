#!/usr/bin/env bash
# Repeated, warmed-up step-load profile for the JOIV48 revision
# (Reviewer 1 crit. 4 item 4, crit. 5; Reviewer 2 crit. 4-5).
#
# For each replica count, each target rate and each repetition:
#   1. restart the autoscale-demo deployment (fresh JVM) and wait until Ready
#   2. run k6 in-cluster (warm-up WARMUP s discarded, then MEASURE s measured)
#   3. take the server-side p95/p99 from Prometheus over EXACTLY the k6 window
#   4. take p95/p99 from the Tomcat access log over the same window (independent check)
#   5. record CPU-throttling ratio and per-pod request rate for the window
# Results are appended to results/runs.jsonl ; then run summarize.py.
#
# IMPORTANT: delete/suspend the HPA first (kubectl delete hpa autoscale-demo), otherwise it overrides the replica count.
# Requirements: kubectl context pointing at the test cluster, Prometheus reachable
# at $PROM (e.g. kubectl -n monitoring port-forward svc/prometheus 9090), python3 + requests.
set -euo pipefail

NS=${NS:-default}
DEPLOY=${DEPLOY:-autoscale-demo}               # Deployment name
APP_LABEL=${APP_LABEL:-app=autoscale-demo}     # pod label selector
CONTAINER=${CONTAINER:-autoscale-demo}         # container name inside the pod
SVC_URL=${SVC_URL:-http://autoscale-demo.${NS}.svc.cluster.local:8080}
PROM=${PROM:-http://localhost:9090}
K6_IMAGE=${K6_IMAGE:-grafana/k6:0.54.0}   # pin the version you report in the paper
WARMUP=${WARMUP:-60}
MEASURE=${MEASURE:-120}
REPS=${REPS:-3}
OUT=${OUT:-results}
mkdir -p "$OUT"

# (no associative arrays: macOS ships bash 3.2)
REPLICA_LIST=${REPLICA_LIST:-"1 2"}
RATES_1=${RATES_1:-"50 100 150 200"}
RATES_2=${RATES_2:-"50 100 150 200 250 300 350"}
rates_for() {
  if [ "$1" = "1" ]; then echo "$RATES_1"; else echo "$RATES_2"; fi
}

kubectl -n "$NS" create configmap k6-script-joiv48 --from-file=workload.js -o yaml --dry-run=client | kubectl apply -f -

for REPLICAS in $REPLICA_LIST; do
  kubectl -n "$NS" scale deploy/"$DEPLOY" --replicas="$REPLICAS"
  for RATE in $(rates_for "$REPLICAS"); do
    for REP in $(seq 1 "$REPS"); do
      echo "=== replicas=$REPLICAS rate=$RATE rep=$REP ==="
      kubectl -n "$NS" rollout restart deploy/"$DEPLOY"
      kubectl -n "$NS" rollout status deploy/"$DEPLOY" --timeout=300s
      sleep 20   # let Prometheus discover the new pods (>= 2 scrape intervals)

      POD=k6-r${REPLICAS}-${RATE}-${REP}-$RANDOM
      kubectl -n "$NS" run "$POD" --image="$K6_IMAGE" --restart=Never \
        --overrides='{"spec":{"volumes":[{"name":"s","configMap":{"name":"k6-script-joiv48"}}],
          "containers":[{"name":"k6","image":"'"$K6_IMAGE"'","args":["run","--quiet","/s/workload.js"],
          "env":[{"name":"TARGET","value":"'"$SVC_URL"'"},{"name":"RATE","value":"'"$RATE"'"},
                 {"name":"WARMUP","value":"'"$WARMUP"'"},{"name":"MEASURE","value":"'"$MEASURE"'"}],
          "volumeMounts":[{"name":"s","mountPath":"/s"}]}]}}'
      kubectl -n "$NS" wait --for=jsonpath='{.status.phase}'=Succeeded pod/"$POD" \
        --timeout=$((WARMUP + MEASURE + 180))s || true
      kubectl -n "$NS" logs "$POD" | sed -n '/===K6_SUMMARY_BEGIN===/,/===K6_SUMMARY_END===/p' \
        | sed '1d;$d' > "$OUT/k6_${REPLICAS}_${RATE}_${REP}.json"
      kubectl -n "$NS" delete pod "$POD" --wait=false
      sleep 15   # one extra scrape interval after the window ends

      python3 server_side.py --k6 "$OUT/k6_${REPLICAS}_${RATE}_${REP}.json" \
        --prom "$PROM" --ns "$NS" --selector "$APP_LABEL" --container "$CONTAINER" \
        --replicas "$REPLICAS" --rep "$REP" >> "$OUT/runs.jsonl" \
        || echo "replicas=$REPLICAS rate=$RATE rep=$REP" >> "$OUT/failed_server_side.txt"
    done
  done
done
echo "done -> $OUT/runs.jsonl ; now run: python3 summarize.py $OUT/runs.jsonl"
