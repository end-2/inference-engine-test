# AIPerf CPU benchmark

- Image: `local/transformers-enhanced-batch:0.1.0`
- Image ID: `sha256:5461c8613b00afad0e8dc458dc6616db9cd6aa2234b8b02d0f1caed8cf524b2a`
- Started (UTC): 2026-09-22T07:21:10.912444+00:00
- Status: complete
- PVC cache policy: `preserve` (no PVC cache deletion).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 44.22 | 145.91 | 240.86 | 19.51 | 20.11 | 801.11 | 1263.38 | 992.43 | 947.02 |
| 2 | 100.00 | 61.21 | 307.79 | 416.95 | 27.41 | 43.66 | 1060.53 | 1364.74 | 522.41 | 1368.31 |
| 4 | 100.00 | 77.13 | 738.60 | 767.80 | 38.94 | 46.96 | 1432.70 | 1461.58 | 207.54 | 2171.30 |
| 8 | 100.00 | 77.12 | 2827.55 | 2969.37 | 38.93 | 47.13 | 1432.75 | 1471.22 | 58.58 | 4260.30 |

Full AIPerf exports, request CSV, resource JSONL/CSV, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
