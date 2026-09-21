# AIPerf CPU benchmark

- Image: `local/transformers-enhanced-cache:0.1.0`
- Image ID: `sha256:b19d539e6c688f2b5e391c03a7da522fc70e681066fbe36597b794ef87db1d61`
- Started (UTC): 2026-09-21T10:59:39.546534+00:00
- Status: complete
- PVC cache policy: `clear-before-sweep` (clear once before the first condition's warmup).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 47.98 | 76.08 | 129.71 | 19.33 | 20.21 | 796.68 | 1273.09 | 2142.55 | 872.76 |
| 2 | 100.00 | 49.05 | 910.81 | 1402.29 | 19.19 | 20.03 | 791.09 | 1261.77 | 232.05 | 1701.91 |
| 4 | 100.00 | 49.00 | 2590.68 | 3370.09 | 19.22 | 19.96 | 792.21 | 1257.76 | 100.58 | 3382.89 |
| 8 | 100.00 | 48.75 | 5862.51 | 6673.76 | 19.29 | 20.13 | 795.81 | 1268.26 | 65.34 | 6658.32 |

Full AIPerf exports, request CSV, resource JSONL/CSV, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
