# AIPerf CPU benchmark

- Image: `local/transformers-base:0.1.0`
- Image ID: `sha256:70db92ecf798cb2c40556370dbbc43dd04ba56b51790aad72c7b7581c1f16584`
- Started (UTC): 2026-09-22T06:57:41.782591+00:00
- Status: complete
- PVC cache policy: `preserve` (no PVC cache deletion).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 43.21 | 140.87 | 237.38 | 19.94 | 20.46 | 828.31 | 1289.05 | 1032.23 | 969.17 |
| 2 | 100.00 | 43.71 | 1092.76 | 1620.77 | 19.90 | 20.39 | 817.08 | 1284.29 | 167.06 | 1909.84 |
| 4 | 100.00 | 44.18 | 2943.35 | 3807.56 | 19.63 | 20.36 | 808.39 | 1282.65 | 65.98 | 3751.74 |
| 8 | 100.00 | 44.23 | 6536.60 | 7448.02 | 19.61 | 20.39 | 807.46 | 1284.22 | 37.35 | 7344.06 |

Full AIPerf exports, request CSV, resource JSONL/CSV, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
