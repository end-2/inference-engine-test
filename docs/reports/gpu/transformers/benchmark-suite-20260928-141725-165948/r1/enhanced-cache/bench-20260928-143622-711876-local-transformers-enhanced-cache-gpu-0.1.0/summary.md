# AIPerf GPU benchmark

- Image: `local/transformers-enhanced-cache-gpu:0.1.0`
- Image ID: `sha256:d979ca31c5600d26dafcc65edebdea4828ac9aa2d5fa2166785df9fd18a3d0a5`
- Started (UTC): 2026-09-28T14:36:22.711876+00:00
- Status: complete
- Device: `gpu`; compute setting: `dtype=float16`.
- PVC cache policy: `clear-before-sweep` (clear once before the first condition's warmup).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 34.85 | 81.95 | 97.91 | 27.20 | 28.17 | 1117.72 | 1771.11 | 1899.94 | 1199.68 |
| 2 | 100.00 | 35.56 | 1251.41 | 1900.77 | 26.63 | 27.58 | 1094.73 | 1733.65 | 158.24 | 2346.14 |
| 4 | 100.00 | 35.24 | 3596.23 | 4638.55 | 26.89 | 27.79 | 1105.18 | 1750.68 | 67.76 | 4701.41 |
| 8 | 100.00 | 34.75 | 8215.42 | 9348.47 | 27.29 | 28.26 | 1120.70 | 1773.61 | 44.19 | 9336.13 |

| Concurrency | GPU UUID | Samples | GPU avg (%) | GPU max (%) | Memory avg (MiB) | Memory max (MiB) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | GPU-7b77b97b-2222-89f1-2d5e-5c488faedd7b | 30 | 16.00 | 22.00 | 416.60 | 422.00 |
| 2 | GPU-7b77b97b-2222-89f1-2d5e-5c488faedd7b | 30 | 16.30 | 22.00 | 416.53 | 422.00 |
| 4 | GPU-7b77b97b-2222-89f1-2d5e-5c488faedd7b | 30 | 15.80 | 22.00 | 415.33 | 422.00 |
| 8 | GPU-7b77b97b-2222-89f1-2d5e-5c488faedd7b | 30 | 16.13 | 21.00 | 416.13 | 422.00 |

Full AIPerf exports, request CSV, resource JSONL/CSV, GPU CSV when selected, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
