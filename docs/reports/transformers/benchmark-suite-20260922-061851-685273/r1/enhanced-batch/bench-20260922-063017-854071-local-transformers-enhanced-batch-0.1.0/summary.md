# AIPerf CPU benchmark

- Image: `local/transformers-enhanced-batch:0.1.0`
- Image ID: `sha256:5461c8613b00afad0e8dc458dc6616db9cd6aa2234b8b02d0f1caed8cf524b2a`
- Started (UTC): 2026-09-22T06:30:17.854071+00:00
- Status: complete
- PVC cache policy: `preserve` (no PVC cache deletion).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 44.55 | 146.57 | 241.84 | 19.24 | 19.99 | 793.55 | 1258.14 | 986.90 | 940.13 |
| 2 | 100.00 | 61.15 | 307.69 | 415.53 | 27.46 | 43.76 | 1062.00 | 1360.78 | 522.60 | 1369.69 |
| 4 | 100.00 | 76.79 | 740.11 | 769.56 | 39.15 | 47.12 | 1441.20 | 1480.36 | 207.18 | 2181.31 |
| 8 | 100.00 | 76.73 | 2855.02 | 3320.38 | 38.74 | 46.65 | 1426.33 | 1452.97 | 58.13 | 4281.35 |

Full AIPerf exports, request CSV, resource JSONL/CSV, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
