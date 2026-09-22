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
| base | 1 | 3 | 43.44 ± 0.32 | 142.41 ± 2.26 | 241.23 ± 6.01 | 19.89 ± 0.09 | 96.49 ± 0.70 |
| base | 2 | 3 | 43.99 ± 0.25 | 1086.58 ± 5.43 | 1622.09 ± 2.16 | 19.71 ± 0.16 | 95.29 ± 0.53 |
| base | 4 | 3 | 44.33 ± 0.16 | 2934.60 ± 10.57 | 3793.09 ± 17.34 | 19.54 ± 0.09 | 94.57 ± 0.34 |
| base | 8 | 3 | 44.29 ± 0.05 | 6523.55 ± 11.45 | 7426.80 ± 19.13 | 19.57 ± 0.03 | 94.64 ± 0.12 |
| enhanced-batch | 1 | 3 | 44.41 ± 0.17 | 146.24 ± 0.33 | 241.34 ± 0.49 | 19.35 ± 0.14 | 94.40 ± 0.36 |
| enhanced-batch | 2 | 3 | 61.28 ± 0.18 | 307.77 ± 0.07 | 416.79 ± 1.19 | 27.38 ± 0.10 | 68.40 ± 0.20 |
| enhanced-batch | 4 | 3 | 77.06 ± 0.24 | 738.56 ± 1.57 | 767.90 ± 1.61 | 38.99 ± 0.14 | 54.40 ± 0.17 |
| enhanced-batch | 8 | 3 | 77.56 ± 1.11 | 2814.20 ± 48.88 | 3086.80 ± 202.29 | 38.57 ± 0.48 | 54.06 ± 0.77 |
| enhanced-cache | 1 | 3 | 47.13 ± 0.07 | 76.98 ± 0.36 | 119.89 ± 0.12 | 19.68 ± 0.05 | 88.95 ± 0.14 |
| enhanced-cache | 2 | 3 | 48.05 ± 0.39 | 930.85 ± 7.92 | 1428.67 ± 14.71 | 19.57 ± 0.15 | 87.24 ± 0.71 |
| enhanced-cache | 4 | 3 | 47.96 ± 0.17 | 2647.67 ± 9.22 | 3439.44 ± 14.75 | 19.61 ± 0.07 | 87.41 ± 0.31 |
| enhanced-cache | 8 | 3 | 47.73 ± 0.94 | 5991.29 ± 123.06 | 7151.80 ± 728.63 | 19.70 ± 0.35 | 87.84 ± 1.75 |

Profiling excludes warmup, Pod preparation and result collection. Sweep elapsed time includes these tasks.

## Sweep reports

| Order | Repetition | Condition | Status | Elapsed (s) | Report |
| ---: | ---: | --- | --- | ---: | --- |
| 1 | 1 | base | complete | 474.37 | [summary](r1/base/bench-20260922-062223-432376-local-transformers-base-0.1.0/summary.md) |
| 2 | 1 | enhanced-batch | complete | 366.26 | [summary](r1/enhanced-batch/bench-20260922-063017-854071-local-transformers-enhanced-batch-0.1.0/summary.md) |
| 3 | 1 | enhanced-cache | complete | 454.55 | [summary](r1/enhanced-cache/bench-20260922-063624-154551-local-transformers-enhanced-cache-0.1.0/summary.md) |
| 4 | 2 | enhanced-batch | complete | 364.40 | [summary](r2/enhanced-batch/bench-20260922-064358-753028-local-transformers-enhanced-batch-0.1.0/summary.md) |
| 5 | 2 | enhanced-cache | complete | 458.53 | [summary](r2/enhanced-cache/bench-20260922-065003-199269-local-transformers-enhanced-cache-0.1.0/summary.md) |
| 6 | 2 | base | complete | 479.41 | [summary](r2/base/bench-20260922-065741-782591-local-transformers-base-0.1.0/summary.md) |
| 7 | 3 | enhanced-cache | complete | 455.15 | [summary](r3/enhanced-cache/bench-20260922-070541-244253-local-transformers-enhanced-cache-0.1.0/summary.md) |
| 8 | 3 | base | complete | 474.41 | [summary](r3/base/bench-20260922-071316-449356-local-transformers-base-0.1.0/summary.md) |
| 9 | 3 | enhanced-batch | complete | 365.47 | [summary](r3/enhanced-batch/bench-20260922-072110-912444-local-transformers-enhanced-batch-0.1.0/summary.md) |

`runs.csv` and `summary.jsonl` contain the individual sweep metrics; `summary.csv` includes mean, standard deviation, minimum, and maximum for every metric.
Image IDs, commands, and execution order are recorded in `run.json`. Per-request exports and resource time series are saved locally under each sweep report and are excluded from Git.
