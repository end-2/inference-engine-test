# AIPerf CPU benchmark

- Image: `local/transformers-enhanced-cache:0.1.0`
- Image ID: `sha256:b19d539e6c688f2b5e391c03a7da522fc70e681066fbe36597b794ef87db1d61`
- Started (UTC): 2026-09-21T10:30:50.779410+00:00
- Status: complete
- PVC cache policy: `clear-before-sweep` (clear once before the first condition's warmup).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 48.22 | 75.64 | 128.93 | 19.24 | 20.04 | 792.82 | 1262.28 | 2148.52 | 868.46 |
| 2 | 100.00 | 48.68 | 917.04 | 1412.62 | 19.32 | 20.25 | 797.73 | 1275.72 | 230.99 | 1714.76 |
| 4 | 100.00 | 49.16 | 2582.24 | 3363.60 | 19.14 | 20.01 | 790.00 | 1258.88 | 100.40 | 3372.24 |
| 8 | 100.00 | 49.14 | 5816.24 | 6616.04 | 19.15 | 20.00 | 789.45 | 1259.79 | 65.89 | 6605.69 |

Full AIPerf exports, request CSV, resource JSONL/CSV, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
