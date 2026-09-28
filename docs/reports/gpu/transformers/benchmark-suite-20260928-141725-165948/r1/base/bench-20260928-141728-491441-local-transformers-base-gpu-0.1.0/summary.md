# AIPerf GPU benchmark

- Image: `local/transformers-base-gpu:0.1.0`
- Image ID: `sha256:7127a3b0a72373a84aa57f114b53afdacaa418aa730bc5f300eead4617717b75`
- Started (UTC): 2026-09-28T14:17:28.491441+00:00
- Status: complete
- Device: `gpu`; compute setting: `dtype=float16`.
- PVC cache policy: `preserve` (no PVC cache deletion).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 33.68 | 82.36 | 97.84 | 28.23 | 29.19 | 1160.45 | 1833.04 | 1913.37 | 1242.81 |
| 2 | 100.00 | 34.89 | 1269.44 | 1938.43 | 27.29 | 28.32 | 1121.95 | 1784.14 | 167.59 | 2391.39 |
| 4 | 100.00 | 33.99 | 3723.19 | 4796.67 | 28.05 | 29.11 | 1151.88 | 1823.71 | 71.75 | 4875.08 |
| 8 | 100.00 | 34.21 | 8338.54 | 9464.40 | 27.87 | 28.83 | 1144.48 | 1811.15 | 47.17 | 9483.01 |

| Concurrency | GPU UUID | Samples | GPU avg (%) | GPU max (%) | Memory avg (MiB) | Memory max (MiB) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | GPU-7b77b97b-2222-89f1-2d5e-5c488faedd7b | 31 | 15.65 | 21.00 | 415.55 | 422.00 |
| 2 | GPU-7b77b97b-2222-89f1-2d5e-5c488faedd7b | 30 | 16.80 | 22.00 | 416.60 | 422.00 |
| 4 | GPU-7b77b97b-2222-89f1-2d5e-5c488faedd7b | 30 | 16.80 | 21.00 | 416.60 | 422.00 |
| 8 | GPU-7b77b97b-2222-89f1-2d5e-5c488faedd7b | 31 | 15.97 | 22.00 | 416.71 | 422.00 |

Full AIPerf exports, request CSV, resource JSONL/CSV, GPU CSV when selected, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
