# AIPerf GPU benchmark

- Image: `local/enhanced-cache-llamacpp-gpu:0.1.0`
- Image ID: `sha256:9c4ff8dc5e3fbe4a3e1bb1d770caeb8e562ef8c31f263301ea77d2356b223da6`
- Started (UTC): 2026-09-28T15:00:16.193979+00:00
- Status: complete
- Device: `gpu`; compute setting: `n_gpu_layers=-1`.
- PVC cache policy: `clear-before-sweep` (clear once before the first condition's warmup).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 254.82 | 20.56 | 30.85 | 3.44 | 3.58 | 142.12 | 225.67 | 7667.17 | 162.68 |
| 2 | 100.00 | 262.19 | 174.11 | 267.79 | 3.44 | 3.62 | 142.25 | 228.04 | 1086.85 | 316.36 |
| 4 | 100.00 | 262.04 | 488.24 | 630.58 | 3.44 | 3.60 | 142.24 | 226.97 | 414.05 | 630.48 |
| 8 | 100.00 | 261.74 | 1095.00 | 1246.56 | 3.45 | 3.63 | 142.62 | 228.59 | 234.04 | 1237.62 |

| Concurrency | GPU UUID | Samples | GPU avg (%) | GPU max (%) | Memory avg (MiB) | Memory max (MiB) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | GPU-7b77b97b-2222-89f1-2d5e-5c488faedd7b | 10 | 21.20 | 71.00 | 796.00 | 812.00 |
| 2 | GPU-7b77b97b-2222-89f1-2d5e-5c488faedd7b | 10 | 21.70 | 73.00 | 788.00 | 796.00 |
| 4 | GPU-7b77b97b-2222-89f1-2d5e-5c488faedd7b | 10 | 21.60 | 73.00 | 788.00 | 796.00 |
| 8 | GPU-7b77b97b-2222-89f1-2d5e-5c488faedd7b | 10 | 21.40 | 72.00 | 788.00 | 796.00 |

Full AIPerf exports, request CSV, resource JSONL/CSV, GPU CSV when selected, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
