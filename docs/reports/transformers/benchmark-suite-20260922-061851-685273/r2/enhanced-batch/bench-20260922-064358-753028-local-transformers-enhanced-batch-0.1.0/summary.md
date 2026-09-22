# AIPerf CPU benchmark

- Image: `local/transformers-enhanced-batch:0.1.0`
- Image ID: `sha256:5461c8613b00afad0e8dc458dc6616db9cd6aa2234b8b02d0f1caed8cf524b2a`
- Started (UTC): 2026-09-22T06:43:58.753028+00:00
- Status: complete
- PVC cache policy: `preserve` (no PVC cache deletion).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 44.45 | 146.22 | 241.32 | 19.30 | 20.16 | 795.77 | 1267.34 | 990.64 | 942.00 |
| 2 | 100.00 | 61.49 | 307.83 | 417.89 | 27.27 | 43.29 | 1054.10 | 1345.94 | 522.30 | 1361.93 |
| 4 | 100.00 | 77.25 | 736.96 | 766.34 | 38.89 | 46.90 | 1431.35 | 1465.79 | 208.02 | 2168.32 |
| 8 | 100.00 | 78.82 | 2760.03 | 2970.64 | 38.03 | 47.26 | 1404.87 | 1470.39 | 62.27 | 4164.90 |

Full AIPerf exports, request CSV, resource JSONL/CSV, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
