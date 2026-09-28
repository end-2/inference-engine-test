# AIPerf GPU benchmark

- Image: `local/base-llamacpp-gpu:0.1.0`
- Image ID: `sha256:5d266695c6887e0064c7f67f1e6c48f1114a6a9eb819a8b61bfc6dc1097b3608`
- Started (UTC): 2026-09-28T14:49:07.081109+00:00
- Status: complete
- Device: `gpu`; compute setting: `n_gpu_layers=-1`.
- PVC cache policy: `preserve` (no PVC cache deletion).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 254.14 | 18.29 | 28.79 | 3.51 | 3.69 | 145.06 | 232.25 | 7798.86 | 163.34 |
| 2 | 100.00 | 260.28 | 175.27 | 267.30 | 3.47 | 3.63 | 143.41 | 228.76 | 1068.27 | 318.68 |
| 4 | 100.00 | 261.34 | 489.33 | 643.63 | 3.46 | 3.63 | 143.04 | 228.43 | 413.75 | 632.37 |
| 8 | 100.00 | 261.14 | 1097.30 | 1252.95 | 3.47 | 3.63 | 143.24 | 228.77 | 222.50 | 1240.53 |

| Concurrency | GPU UUID | Samples | GPU avg (%) | GPU max (%) | Memory avg (MiB) | Memory max (MiB) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | GPU-7b77b97b-2222-89f1-2d5e-5c488faedd7b | 10 | 22.70 | 76.00 | 796.00 | 812.00 |
| 2 | GPU-7b77b97b-2222-89f1-2d5e-5c488faedd7b | 10 | 22.90 | 77.00 | 796.00 | 812.00 |
| 4 | GPU-7b77b97b-2222-89f1-2d5e-5c488faedd7b | 10 | 23.10 | 77.00 | 799.20 | 812.00 |
| 8 | GPU-7b77b97b-2222-89f1-2d5e-5c488faedd7b | 10 | 23.10 | 77.00 | 796.00 | 812.00 |

Full AIPerf exports, request CSV, resource JSONL/CSV, GPU CSV when selected, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
