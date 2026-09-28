# AIPerf GPU benchmark

- Image: `local/enhanced-batch-llamacpp-gpu:0.1.0`
- Image ID: `sha256:879f0a215780278d0aeb93338109000cf3794baa972566b55ea743a4d720d521`
- Started (UTC): 2026-09-28T14:52:41.167433+00:00
- Status: complete
- Device: `gpu`; compute setting: `n_gpu_layers=-1`.
- PVC cache policy: `preserve` (no PVC cache deletion).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 257.77 | 26.90 | 46.92 | 3.24 | 3.37 | 133.90 | 212.39 | 5455.63 | 160.80 |
| 2 | 100.00 | 307.89 | 45.03 | 72.57 | 5.42 | 7.01 | 224.37 | 394.89 | 3230.81 | 269.40 |
| 4 | 100.00 | 356.11 | 79.91 | 133.69 | 9.35 | 11.00 | 385.41 | 655.77 | 1834.39 | 465.32 |
| 8 | 100.00 | 392.76 | 134.58 | 219.70 | 16.98 | 19.83 | 697.99 | 1144.38 | 1088.36 | 832.57 |

| Concurrency | GPU UUID | Samples | GPU avg (%) | GPU max (%) | Memory avg (MiB) | Memory max (MiB) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | GPU-7b77b97b-2222-89f1-2d5e-5c488faedd7b | 10 | 24.60 | 82.00 | 880.00 | 896.00 |
| 2 | GPU-7b77b97b-2222-89f1-2d5e-5c488faedd7b | 9 | 24.22 | 78.00 | 880.00 | 900.00 |
| 4 | GPU-7b77b97b-2222-89f1-2d5e-5c488faedd7b | 9 | 17.11 | 77.00 | 880.00 | 900.00 |
| 8 | GPU-7b77b97b-2222-89f1-2d5e-5c488faedd7b | 9 | 16.67 | 75.00 | 881.78 | 904.00 |

Full AIPerf exports, request CSV, resource JSONL/CSV, GPU CSV when selected, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
