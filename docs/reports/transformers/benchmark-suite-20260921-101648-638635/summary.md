# Inference benchmark: repeated sweeps

- Status: complete
- Repetitions per condition: 3
- Backend: `transformers`
- Inference node: `local-k8s-control-plane`; AIPerf node: `local-k8s-control-plane`
- Each sweep uses concurrency 1, 2, 4, 8; each step has 2 warmup and 100 profiling requests.
- Each step starts with a fresh inference Pod. Image IDs and node placement are fixed across repetitions.
- Cache: empty PVC before each sweep, then retain it between steps.
- Cache clearing precedes warmup; cache can fill and be reused within each step.
- Execution order rotates by one condition each repetition. All sweeps run sequentially.
- Values are mean ± sample standard deviation across sweeps. TTFT p95 is the mean of per-sweep p95 values, not a pooled p95.

| Condition | Concurrency | Runs | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | Profiling (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| base | 1 | 3 | 44.79 ± 0.17 | 138.88 ± 0.62 | 233.32 ± 3.71 | 19.33 ± 0.08 | 93.59 ± 0.36 |
| base | 2 | 3 | 44.96 ± 0.11 | 1063.57 ± 2.73 | 1589.18 ± 9.06 | 19.27 ± 0.05 | 93.24 ± 0.23 |
| base | 4 | 3 | 45.27 ± 0.07 | 2874.59 ± 3.96 | 3729.29 ± 6.00 | 19.12 ± 0.05 | 92.61 ± 0.15 |
| base | 8 | 3 | 45.09 ± 0.08 | 6408.65 ± 12.18 | 7300.41 ± 13.77 | 19.20 ± 0.03 | 92.97 ± 0.17 |
| enhanced-batch | 1 | 3 | 45.39 ± 0.07 | 145.32 ± 0.31 | 239.77 ± 3.18 | 18.84 ± 0.04 | 92.35 ± 0.14 |
| enhanced-batch | 2 | 3 | 62.21 ± 0.14 | 306.36 ± 0.51 | 415.15 ± 2.83 | 26.88 ± 0.07 | 67.39 ± 0.15 |
| enhanced-batch | 4 | 3 | 78.53 ± 0.15 | 733.91 ± 0.85 | 762.99 ± 2.07 | 38.03 ± 0.12 | 53.38 ± 0.10 |
| enhanced-batch | 8 | 3 | 79.32 ± 1.05 | 2756.33 ± 40.23 | 2934.21 ± 29.59 | 37.60 ± 0.52 | 52.85 ± 0.69 |
| enhanced-cache | 1 | 3 | 48.08 ± 0.12 | 75.73 ± 0.32 | 127.16 ± 3.75 | 19.29 ± 0.04 | 87.19 ± 0.22 |
| enhanced-cache | 2 | 3 | 48.90 ± 0.19 | 913.21 ± 3.35 | 1406.97 ± 5.24 | 19.24 ± 0.07 | 85.72 ± 0.34 |
| enhanced-cache | 4 | 3 | 49.06 ± 0.09 | 2587.39 ± 4.52 | 3367.36 ± 3.36 | 19.19 ± 0.04 | 85.45 ± 0.15 |
| enhanced-cache | 8 | 3 | 48.97 ± 0.20 | 5837.01 ± 23.49 | 6648.95 ± 29.70 | 19.22 ± 0.07 | 85.60 ± 0.35 |

Profiling excludes warmup, Pod preparation and result collection. Sweep elapsed time includes these tasks.

## Sweep reports

| Order | Repetition | Condition | Status | Elapsed (s) | Report |
| ---: | ---: | --- | --- | ---: | --- |
| 1 | 1 | base | complete | 475.92 | [summary](r1/base/bench-20260921-101650-131660-local-transformers-base-0.1.0/summary.md) |
| 2 | 1 | enhanced-batch | complete | 364.64 | [summary](r1/enhanced-batch/bench-20260921-102446-094667-local-transformers-enhanced-batch-0.1.0/summary.md) |
| 3 | 1 | enhanced-cache | complete | 445.50 | [summary](r1/enhanced-cache/bench-20260921-103050-779410-local-transformers-enhanced-cache-0.1.0/summary.md) |
| 4 | 2 | enhanced-batch | complete | 364.35 | [summary](r2/enhanced-batch/bench-20260921-103816-323173-local-transformers-enhanced-batch-0.1.0/summary.md) |
| 5 | 2 | enhanced-cache | complete | 445.38 | [summary](r2/enhanced-cache/bench-20260921-104420-721406-local-transformers-enhanced-cache-0.1.0/summary.md) |
| 6 | 2 | base | complete | 473.34 | [summary](r2/base/bench-20260921-105146-151597-local-transformers-base-0.1.0/summary.md) |
| 7 | 3 | enhanced-cache | complete | 446.97 | [summary](r3/enhanced-cache/bench-20260921-105939-546534-local-transformers-enhanced-cache-0.1.0/summary.md) |
| 8 | 3 | base | complete | 474.87 | [summary](r3/base/bench-20260921-110706-567546-local-transformers-base-0.1.0/summary.md) |
| 9 | 3 | enhanced-batch | complete | 364.94 | [summary](r3/enhanced-batch/bench-20260921-111501-489635-local-transformers-enhanced-batch-0.1.0/summary.md) |

`runs.csv` and `summary.jsonl` contain the individual sweep metrics; `summary.csv` includes mean, standard deviation, minimum, and maximum for every metric.
Image IDs, commands, and execution order are recorded in `run.json`. Per-request exports and resource time series are saved locally under each sweep report and are excluded from Git.
