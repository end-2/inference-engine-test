# AIPerf CPU benchmark

- Image: `local/transformers-enhanced-cache:0.1.0`
- Image ID: `sha256:b19d539e6c688f2b5e391c03a7da522fc70e681066fbe36597b794ef87db1d61`
- Started (UTC): 2026-09-21T10:44:20.721406+00:00
- Status: complete
- PVC cache policy: `clear-before-sweep` (clear once before the first condition's warmup).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 48.05 | 75.46 | 122.85 | 19.29 | 20.21 | 796.11 | 1273.26 | 2159.50 | 871.57 |
| 2 | 100.00 | 48.98 | 911.79 | 1406.00 | 19.22 | 20.06 | 792.52 | 1263.97 | 231.35 | 1704.31 |
| 4 | 100.00 | 49.02 | 2589.24 | 3368.39 | 19.21 | 20.02 | 791.65 | 1261.08 | 99.39 | 3380.89 |
| 8 | 100.00 | 49.02 | 5832.27 | 6657.06 | 19.22 | 20.08 | 792.38 | 1265.35 | 65.45 | 6624.65 |

Full AIPerf exports, request CSV, resource JSONL/CSV, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
