# AIPerf CPU benchmark

- Image: `local/transformers-enhanced-cache:0.1.0`
- Image ID: `sha256:6c900feed1fd8de408d6cfefe89883caf3272678dca83414e3fd014a2deee21b`
- Started (UTC): 2026-09-22T07:05:41.244253+00:00
- Status: complete
- PVC cache policy: `clear-before-sweep` (clear once before the first condition's warmup).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 47.21 | 77.17 | 119.89 | 19.63 | 20.43 | 808.55 | 1287.17 | 2081.93 | 885.72 |
| 2 | 100.00 | 48.43 | 923.42 | 1415.45 | 19.42 | 20.17 | 799.97 | 1270.90 | 225.72 | 1723.39 |
| 4 | 100.00 | 47.78 | 2656.99 | 3453.23 | 19.69 | 20.53 | 811.34 | 1292.08 | 98.58 | 3468.33 |
| 8 | 100.00 | 46.68 | 6129.78 | 7992.77 | 20.07 | 20.42 | 830.98 | 1279.14 | 63.03 | 6960.76 |

Full AIPerf exports, request CSV, resource JSONL/CSV, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
