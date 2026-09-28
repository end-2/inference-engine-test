# AIPerf GPU benchmark

- Image: `local/enhanced-cache-llamacpp-gpu:0.1.0`
- Image ID: `sha256:9c4ff8dc5e3fbe4a3e1bb1d770caeb8e562ef8c31f263301ea77d2356b223da6`
- Started (UTC): 2026-09-28T14:55:54.466619+00:00
- Status: complete
- Device: `gpu`; compute setting: `n_gpu_layers=-1`.
- PVC cache policy: `clear-per-concurrency` (clear before each condition's warmup).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 255.14 | 20.53 | 31.00 | 3.44 | 3.60 | 142.10 | 226.54 | 7663.63 | 162.63 |
| 2 | 100.00 | 259.12 | 177.87 | 262.57 | 3.44 | 3.60 | 142.05 | 226.58 | 1028.67 | 319.92 |
| 4 | 100.00 | 258.98 | 495.82 | 627.83 | 3.44 | 3.60 | 142.14 | 226.51 | 373.59 | 637.96 |
| 8 | 100.00 | 259.26 | 1107.77 | 1242.36 | 3.44 | 3.60 | 142.17 | 226.67 | 192.80 | 1249.95 |

| Concurrency | GPU UUID | Samples | GPU avg (%) | GPU max (%) | Memory avg (MiB) | Memory max (MiB) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | GPU-7b77b97b-2222-89f1-2d5e-5c488faedd7b | 10 | 21.20 | 71.00 | 796.00 | 812.00 |
| 2 | GPU-7b77b97b-2222-89f1-2d5e-5c488faedd7b | 10 | 21.40 | 72.00 | 796.00 | 812.00 |
| 4 | GPU-7b77b97b-2222-89f1-2d5e-5c488faedd7b | 10 | 21.70 | 73.00 | 796.00 | 812.00 |
| 8 | GPU-7b77b97b-2222-89f1-2d5e-5c488faedd7b | 10 | 21.60 | 73.00 | 796.00 | 812.00 |

Full AIPerf exports, request CSV, resource JSONL/CSV, GPU CSV when selected, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
