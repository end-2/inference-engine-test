# AIPerf GPU benchmark

- Image: `local/transformers-enhanced-batch-gpu:0.1.0`
- Image ID: `sha256:135a6e1ff5f565de3e7a40df66df3386e7c3393589abedb0456de01807d461b3`
- Started (UTC): 2026-09-28T14:28:27.463513+00:00
- Status: complete
- Device: `gpu`; compute setting: `dtype=float16`.
- PVC cache policy: `preserve` (no PVC cache deletion).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 33.48 | 86.89 | 101.68 | 28.29 | 29.30 | 1163.31 | 1845.82 | 1804.75 | 1250.20 |
| 2 | 100.00 | 55.05 | 86.44 | 101.87 | 37.17 | 58.65 | 1433.82 | 1824.67 | 1813.05 | 1520.26 |
| 4 | 100.00 | 89.33 | 208.82 | 978.79 | 43.71 | 60.29 | 1643.62 | 1878.34 | 1595.10 | 1852.44 |
| 8 | 100.00 | 83.67 | 2011.45 | 2130.45 | 51.90 | 62.52 | 1910.57 | 1956.12 | 116.86 | 3922.02 |

| Concurrency | GPU UUID | Samples | GPU avg (%) | GPU max (%) | Memory avg (MiB) | Memory max (MiB) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | GPU-7b77b97b-2222-89f1-2d5e-5c488faedd7b | 31 | 15.61 | 21.00 | 415.55 | 422.00 |
| 2 | GPU-7b77b97b-2222-89f1-2d5e-5c488faedd7b | 22 | 14.91 | 23.00 | 419.18 | 428.00 |
| 4 | GPU-7b77b97b-2222-89f1-2d5e-5c488faedd7b | 16 | 13.12 | 25.00 | 441.12 | 468.00 |
| 8 | GPU-7b77b97b-2222-89f1-2d5e-5c488faedd7b | 17 | 13.06 | 24.00 | 442.59 | 468.00 |

Full AIPerf exports, request CSV, resource JSONL/CSV, GPU CSV when selected, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
