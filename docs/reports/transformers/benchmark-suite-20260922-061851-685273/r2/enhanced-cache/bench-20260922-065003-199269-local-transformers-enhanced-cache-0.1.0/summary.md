# AIPerf CPU benchmark

- Image: `local/transformers-enhanced-cache:0.1.0`
- Image ID: `sha256:6c900feed1fd8de408d6cfefe89883caf3272678dca83414e3fd014a2deee21b`
- Started (UTC): 2026-09-22T06:50:03.199269+00:00
- Status: complete
- PVC cache policy: `clear-before-sweep` (clear once before the first condition's warmup).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 47.07 | 77.21 | 120.00 | 19.71 | 20.57 | 811.31 | 1290.08 | 2081.37 | 888.52 |
| 2 | 100.00 | 48.08 | 929.96 | 1426.02 | 19.56 | 20.37 | 805.82 | 1283.18 | 224.91 | 1735.78 |
| 4 | 100.00 | 47.97 | 2647.47 | 3441.21 | 19.59 | 20.45 | 807.14 | 1288.37 | 95.54 | 3454.60 |
| 8 | 100.00 | 48.04 | 5949.62 | 6753.37 | 19.62 | 20.48 | 808.40 | 1285.24 | 62.78 | 6758.02 |

Full AIPerf exports, request CSV, resource JSONL/CSV, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
