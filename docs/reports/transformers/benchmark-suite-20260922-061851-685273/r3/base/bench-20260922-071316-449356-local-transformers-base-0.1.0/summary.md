# AIPerf CPU benchmark

- Image: `local/transformers-base:0.1.0`
- Image ID: `sha256:70db92ecf798cb2c40556370dbbc43dd04ba56b51790aad72c7b7581c1f16584`
- Started (UTC): 2026-09-22T07:13:16.449356+00:00
- Status: complete
- PVC cache policy: `preserve` (no PVC cache deletion).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 43.81 | 141.37 | 238.15 | 19.78 | 20.67 | 814.51 | 1290.52 | 1027.80 | 955.88 |
| 2 | 100.00 | 44.15 | 1082.56 | 1620.92 | 19.63 | 20.33 | 808.48 | 1280.49 | 168.15 | 1891.04 |
| 4 | 100.00 | 44.30 | 2937.59 | 3797.85 | 19.53 | 20.43 | 804.72 | 1282.20 | 65.81 | 3742.31 |
| 8 | 100.00 | 44.32 | 6518.84 | 7410.88 | 19.55 | 20.26 | 804.70 | 1274.44 | 36.75 | 7323.54 |

Full AIPerf exports, request CSV, resource JSONL/CSV, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
