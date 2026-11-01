// k6 load script for one load step of the JOIV48 capacity profile.
// Open-loop constant-arrival-rate load (no coordinated omission), with a
// discarded warm-up phase and a separate measurement phase.
//
// Request: GET /work?ms=5 on autoscale-demo (same request as the authors' original test.js).
// env: TARGET (http://autoscale-demo.default.svc.cluster.local:8080), RATE (RPS), WORK_MS (default 5),
//      WARMUP (s, default 60), MEASURE (s, default 120), VUS (pre-allocated, default 4*RATE/10+50)
//
// The summary JSON (printed between markers) contains the measurement-phase
// metrics only, plus the wall-clock measurement window so that the server-side
// Prometheus query and the access-log percentile use exactly the same interval.
import http from 'k6/http';
import { check } from 'k6';

const TARGET = __ENV.TARGET || 'http://autoscale-demo.default.svc.cluster.local:8080';
const WORK_MS = __ENV.WORK_MS || '5';
const RATE = parseInt(__ENV.RATE || '50');
const WARMUP = parseInt(__ENV.WARMUP || '60');
const MEASURE = parseInt(__ENV.MEASURE || '120');
const VUS = parseInt(__ENV.VUS || '300');      // same as original test.js (preAllocatedVUs 300, maxVUs 600)

export const options = {
  discardResponseBodies: true,
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
  scenarios: {
    warmup: {
      executor: 'constant-arrival-rate', rate: RATE, timeUnit: '1s',
      duration: `${WARMUP}s`, preAllocatedVUs: VUS, maxVUs: VUS * 2,
      tags: { phase: 'warmup' }, gracefulStop: '0s',
    },
    measure: {
      executor: 'constant-arrival-rate', rate: RATE, timeUnit: '1s',
      startTime: `${WARMUP}s`, duration: `${MEASURE}s`,
      preAllocatedVUs: VUS, maxVUs: VUS * 2,
      tags: { phase: 'measure' }, gracefulStop: '30s',
    },
  },
  // thresholds only exist so that the tagged sub-metrics appear in the summary
  thresholds: {
    'http_req_duration{phase:measure}': ['p(99)>=0'],
    'http_req_failed{phase:measure}': ['rate>=0'],
    'http_reqs{phase:measure}': ['count>=0'],
    'iterations{scenario:measure}': ['count>=0'],
    'dropped_iterations{scenario:measure}': ['count>=0'],
    'dropped_iterations{scenario:warmup}': ['count>=0'],
  },
};

export function setup() {
  return { t0: Date.now() };
}

export default function () {
  const res = http.get(`${TARGET}/work?ms=${WORK_MS}`, { timeout: '10s' });
  check(res, { '2xx': (r) => r.status >= 200 && r.status < 300 });
}

export function handleSummary(data) {
  const m = data.metrics;
  const get = (name, field) => (m[name] && m[name].values ? m[name].values[field] : null);
  const t0 = data.setup_data ? data.setup_data.t0 : null;
  const out = {
    rate_target: RATE,
    warmup_s: WARMUP,
    measure_s: MEASURE,
    window_start_ms: t0 ? t0 + WARMUP * 1000 : null,
    window_end_ms: t0 ? t0 + (WARMUP + MEASURE) * 1000 : null,
    achieved_rps: get('http_reqs{phase:measure}', 'count') / MEASURE,
    p95_ms: get('http_req_duration{phase:measure}', 'p(95)'),
    p99_ms: get('http_req_duration{phase:measure}', 'p(99)'),
    error_rate: get('http_req_failed{phase:measure}', 'rate'),
    dropped_iterations_measure: get('dropped_iterations{scenario:measure}', 'count') || 0,
    dropped_iterations_warmup: get('dropped_iterations{scenario:warmup}', 'count') || 0,
    vus_max: get('vus_max', 'max'),
  };
  return {
    stdout: `\n===K6_SUMMARY_BEGIN===\n${JSON.stringify(out)}\n===K6_SUMMARY_END===\n`,
  };
}
