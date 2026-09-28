# Inference benchmark: sweeps

- Status: complete
- Repetitions per condition: 1
- Backend: `llamacpp`; device: `gpu`
- Compute setting: `n_gpu_layers=-1`.
- Inference node: `local-k8s-gpu-worker`; AIPerf node: `local-k8s-gpu-control-plane`
- Each sweep uses concurrency 1, 2, 4, 8; each step has 2 warmup and 100 profiling requests.
- Each step starts with a fresh inference Pod. Image IDs and node placement are fixed across repetitions.
- Cache clear: empty PVC before every step. Cache preserve: empty PVC before the sweep, then retain it between steps.
- Cache clearing precedes warmup; cache can fill and be reused within each step.
- All sweeps run sequentially.
- Values are from one sweep per condition.

| Condition | Concurrency | Runs | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | Profiling (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| base | 1 | 1 | 254.14 | 18.29 | 28.79 | 3.51 | 16.49 |
| base | 2 | 1 | 260.28 | 175.27 | 267.30 | 3.47 | 16.10 |
| base | 4 | 1 | 261.34 | 489.33 | 643.63 | 3.46 | 16.04 |
| base | 8 | 1 | 261.14 | 1097.30 | 1252.95 | 3.47 | 16.05 |
| enhanced-batch | 1 | 1 | 257.77 | 26.90 | 46.92 | 3.24 | 16.26 |
| enhanced-batch | 2 | 1 | 307.89 | 45.03 | 72.57 | 5.42 | 13.61 |
| enhanced-batch | 4 | 1 | 356.11 | 79.91 | 133.69 | 9.35 | 11.77 |
| enhanced-batch | 8 | 1 | 392.76 | 134.58 | 219.70 | 16.98 | 10.67 |
| enhanced-cache-clear | 1 | 1 | 255.14 | 20.53 | 31.00 | 3.44 | 16.43 |
| enhanced-cache-clear | 2 | 1 | 259.12 | 177.87 | 262.57 | 3.44 | 16.18 |
| enhanced-cache-clear | 4 | 1 | 258.98 | 495.82 | 627.83 | 3.44 | 16.18 |
| enhanced-cache-clear | 8 | 1 | 259.26 | 1107.77 | 1242.36 | 3.44 | 16.17 |
| enhanced-cache-preserve | 1 | 1 | 254.82 | 20.56 | 30.85 | 3.44 | 16.45 |
| enhanced-cache-preserve | 2 | 1 | 262.19 | 174.11 | 267.79 | 3.44 | 15.99 |
| enhanced-cache-preserve | 4 | 1 | 262.04 | 488.24 | 630.58 | 3.44 | 16.00 |
| enhanced-cache-preserve | 8 | 1 | 261.74 | 1095.00 | 1246.56 | 3.45 | 16.01 |

| Condition | Concurrency | GPU avg (%) | GPU max (%) | Memory avg (MiB) | Memory max (MiB) |
| --- | ---: | ---: | ---: | ---: | ---: |
| base | 1 | 22.70 | 76.00 | 796.00 | 812.00 |
| base | 2 | 22.90 | 77.00 | 796.00 | 812.00 |
| base | 4 | 23.10 | 77.00 | 799.20 | 812.00 |
| base | 8 | 23.10 | 77.00 | 796.00 | 812.00 |
| enhanced-batch | 1 | 24.60 | 82.00 | 880.00 | 896.00 |
| enhanced-batch | 2 | 24.22 | 78.00 | 880.00 | 900.00 |
| enhanced-batch | 4 | 17.11 | 77.00 | 880.00 | 900.00 |
| enhanced-batch | 8 | 16.67 | 75.00 | 881.78 | 904.00 |
| enhanced-cache-clear | 1 | 21.20 | 71.00 | 796.00 | 812.00 |
| enhanced-cache-clear | 2 | 21.40 | 72.00 | 796.00 | 812.00 |
| enhanced-cache-clear | 4 | 21.70 | 73.00 | 796.00 | 812.00 |
| enhanced-cache-clear | 8 | 21.60 | 73.00 | 796.00 | 812.00 |
| enhanced-cache-preserve | 1 | 21.20 | 71.00 | 796.00 | 812.00 |
| enhanced-cache-preserve | 2 | 21.70 | 73.00 | 788.00 | 796.00 |
| enhanced-cache-preserve | 4 | 21.60 | 73.00 | 788.00 | 796.00 |
| enhanced-cache-preserve | 8 | 21.40 | 72.00 | 788.00 | 796.00 |

Profiling excludes warmup, Pod preparation and result collection. Sweep elapsed time includes these tasks.

## Sweep reports

| Order | Repetition | Condition | Status | Elapsed (s) | Report |
| ---: | ---: | --- | --- | ---: | --- |
| 1 | 1 | base | complete | 214.03 | [summary](r1/base/bench-20260928-144907-081109-local-base-llamacpp-gpu-0.1.0/summary.md) |
| 2 | 1 | enhanced-batch | complete | 193.24 | [summary](r1/enhanced-batch/bench-20260928-145241-167433-local-enhanced-batch-llamacpp-gpu-0.1.0/summary.md) |
| 3 | 1 | enhanced-cache-clear | complete | 261.66 | [summary](r1/enhanced-cache-clear/bench-20260928-145554-466619-local-enhanced-cache-llamacpp-gpu-0.1.0/summary.md) |
| 4 | 1 | enhanced-cache-preserve | complete | 212.51 | [summary](r1/enhanced-cache-preserve/bench-20260928-150016-193979-local-enhanced-cache-llamacpp-gpu-0.1.0/summary.md) |

`runs.csv` and `summary.jsonl` contain the individual sweep metrics; `summary.csv` includes mean, standard deviation, minimum, and maximum for every metric.
Image IDs, commands, and execution order are recorded in `run.json`. Per-request exports and resource time series are saved locally under each sweep report and are excluded from Git.
