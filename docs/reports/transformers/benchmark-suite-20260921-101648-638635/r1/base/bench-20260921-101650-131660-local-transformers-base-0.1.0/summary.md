# AIPerf CPU benchmark

- Image: `local/transformers-base:0.1.0`
- Image ID: `sha256:a033c7e225cbfbb325b73c8e09deb0ee8c6b387f76e589bd90c601776cc72ae6`
- Started (UTC): 2026-09-21T10:16:50.131660+00:00
- Status: complete
- PVC cache policy: `preserve` (no PVC cache deletion).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 44.70 | 139.43 | 237.21 | 19.35 | 20.28 | 797.46 | 1265.77 | 1043.98 | 936.90 |
| 2 | 100.00 | 44.86 | 1065.48 | 1599.48 | 19.32 | 20.17 | 795.42 | 1269.17 | 170.61 | 1860.90 |
| 4 | 100.00 | 45.27 | 2875.34 | 3736.20 | 19.11 | 19.88 | 787.30 | 1252.47 | 67.91 | 3662.64 |
| 8 | 100.00 | 45.03 | 6418.30 | 7303.87 | 19.22 | 20.00 | 792.52 | 1259.81 | 37.60 | 7210.81 |

Full AIPerf exports, request CSV, resource JSONL/CSV, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
