# AIPerf CPU benchmark

- Image: `local/transformers-base:0.1.0`
- Image ID: `sha256:a033c7e225cbfbb325b73c8e09deb0ee8c6b387f76e589bd90c601776cc72ae6`
- Started (UTC): 2026-09-21T10:51:46.151597+00:00
- Status: complete
- PVC cache policy: `preserve` (no PVC cache deletion).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 44.99 | 138.21 | 229.82 | 19.24 | 20.02 | 792.41 | 1257.91 | 1052.13 | 930.62 |
| 2 | 100.00 | 45.08 | 1060.44 | 1582.47 | 19.21 | 19.92 | 791.51 | 1255.03 | 171.63 | 1851.95 |
| 4 | 100.00 | 45.19 | 2878.13 | 3725.48 | 19.17 | 19.88 | 789.80 | 1252.19 | 68.00 | 3667.93 |
| 8 | 100.00 | 45.06 | 6412.68 | 7312.12 | 19.21 | 20.10 | 791.56 | 1266.25 | 37.31 | 7204.24 |

Full AIPerf exports, request CSV, resource JSONL/CSV, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
