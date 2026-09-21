# AIPerf CPU benchmark

- Image: `local/transformers-base:0.1.0`
- Image ID: `sha256:a033c7e225cbfbb325b73c8e09deb0ee8c6b387f76e589bd90c601776cc72ae6`
- Started (UTC): 2026-09-21T11:07:06.567546+00:00
- Status: complete
- PVC cache policy: `preserve` (no PVC cache deletion).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 44.69 | 139.01 | 232.92 | 19.39 | 20.17 | 798.13 | 1270.81 | 1046.65 | 937.13 |
| 2 | 100.00 | 44.93 | 1064.77 | 1585.58 | 19.28 | 20.02 | 793.17 | 1256.74 | 170.70 | 1857.94 |
| 4 | 100.00 | 45.34 | 2870.32 | 3726.18 | 19.08 | 19.85 | 785.93 | 1250.80 | 67.76 | 3656.24 |
| 8 | 100.00 | 45.18 | 6394.96 | 7285.24 | 19.16 | 20.03 | 789.36 | 1261.82 | 37.88 | 7184.32 |

Full AIPerf exports, request CSV, resource JSONL/CSV, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
