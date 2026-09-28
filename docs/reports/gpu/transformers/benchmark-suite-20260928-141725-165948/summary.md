# Inference benchmark: sweeps

- Status: complete
- Repetitions per condition: 1
- Backend: `transformers`; device: `gpu`
- Compute setting: `dtype=float16`.
- Inference node: `local-k8s-gpu-worker`; AIPerf node: `local-k8s-gpu-control-plane`
- Each sweep uses concurrency 1, 2, 4, 8; each step has 2 warmup and 100 profiling requests.
- Each step starts with a fresh inference Pod. Image IDs and node placement are fixed across repetitions.
- Cache: empty PVC before each sweep, then retain it between steps.
- Cache clearing precedes warmup; cache can fill and be reused within each step.
- All sweeps run sequentially.
- Values are from one sweep per condition.

| Condition | Concurrency | Runs | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | Profiling (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| base | 1 | 1 | 33.68 | 82.36 | 97.84 | 28.23 | 124.46 |
| base | 2 | 1 | 34.89 | 1269.44 | 1938.43 | 27.29 | 120.13 |
| base | 4 | 1 | 33.99 | 3723.19 | 4796.67 | 28.05 | 123.34 |
| base | 8 | 1 | 34.21 | 8338.54 | 9464.40 | 27.87 | 122.54 |
| enhanced-batch | 1 | 1 | 33.48 | 86.89 | 101.68 | 28.29 | 125.19 |
| enhanced-batch | 2 | 1 | 55.05 | 86.44 | 101.87 | 37.17 | 76.15 |
| enhanced-batch | 4 | 1 | 89.33 | 208.82 | 978.79 | 43.71 | 46.92 |
| enhanced-batch | 8 | 1 | 83.67 | 2011.45 | 2130.45 | 51.90 | 50.09 |
| enhanced-cache | 1 | 1 | 34.85 | 81.95 | 97.91 | 27.20 | 120.27 |
| enhanced-cache | 2 | 1 | 35.56 | 1251.41 | 1900.77 | 26.63 | 117.87 |
| enhanced-cache | 4 | 1 | 35.24 | 3596.23 | 4638.55 | 26.89 | 118.95 |
| enhanced-cache | 8 | 1 | 34.75 | 8215.42 | 9348.47 | 27.29 | 120.62 |

| Condition | Concurrency | GPU avg (%) | GPU max (%) | Memory avg (MiB) | Memory max (MiB) |
| --- | ---: | ---: | ---: | ---: | ---: |
| base | 1 | 15.65 | 21.00 | 415.55 | 422.00 |
| base | 2 | 16.80 | 22.00 | 416.60 | 422.00 |
| base | 4 | 16.80 | 21.00 | 416.60 | 422.00 |
| base | 8 | 15.97 | 22.00 | 416.71 | 422.00 |
| enhanced-batch | 1 | 15.61 | 21.00 | 415.55 | 422.00 |
| enhanced-batch | 2 | 14.91 | 23.00 | 419.18 | 428.00 |
| enhanced-batch | 4 | 13.12 | 25.00 | 441.12 | 468.00 |
| enhanced-batch | 8 | 13.06 | 24.00 | 442.59 | 468.00 |
| enhanced-cache | 1 | 16.00 | 22.00 | 416.60 | 422.00 |
| enhanced-cache | 2 | 16.30 | 22.00 | 416.53 | 422.00 |
| enhanced-cache | 4 | 15.80 | 22.00 | 415.33 | 422.00 |
| enhanced-cache | 8 | 16.13 | 21.00 | 416.13 | 422.00 |

Profiling excludes warmup, Pod preparation and result collection. Sweep elapsed time includes these tasks.

## Sweep reports

| Order | Repetition | Condition | Status | Elapsed (s) | Report |
| ---: | ---: | --- | --- | ---: | --- |
| 1 | 1 | base | complete | 658.91 | [summary](r1/base/bench-20260928-141728-491441-local-transformers-base-gpu-0.1.0/summary.md) |
| 2 | 1 | enhanced-batch | complete | 475.19 | [summary](r1/enhanced-batch/bench-20260928-142827-463513-local-transformers-enhanced-batch-gpu-0.1.0/summary.md) |
| 3 | 1 | enhanced-cache | complete | 667.29 | [summary](r1/enhanced-cache/bench-20260928-143622-711876-local-transformers-enhanced-cache-gpu-0.1.0/summary.md) |

`runs.csv` and `summary.jsonl` contain the individual sweep metrics; `summary.csv` includes mean, standard deviation, minimum, and maximum for every metric.
Image IDs, commands, and execution order are recorded in `run.json`. Per-request exports and resource time series are saved locally under each sweep report and are excluded from Git.
