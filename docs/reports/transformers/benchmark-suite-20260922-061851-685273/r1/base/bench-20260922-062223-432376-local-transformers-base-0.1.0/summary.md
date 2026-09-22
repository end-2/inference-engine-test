# AIPerf CPU benchmark

- Image: `local/transformers-base:0.1.0`
- Image ID: `sha256:70db92ecf798cb2c40556370dbbc43dd04ba56b51790aad72c7b7581c1f16584`
- Started (UTC): 2026-09-22T06:22:23.432376+00:00
- Status: complete
- PVC cache policy: `preserve` (no PVC cache deletion).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 43.32 | 145.00 | 248.16 | 19.94 | 20.92 | 821.63 | 1317.27 | 1004.50 | 966.64 |
| 2 | 100.00 | 44.12 | 1084.42 | 1624.58 | 19.61 | 20.37 | 807.70 | 1282.28 | 167.22 | 1892.11 |
| 4 | 100.00 | 44.50 | 2922.86 | 3773.87 | 19.46 | 20.26 | 801.75 | 1275.35 | 66.92 | 3724.61 |
| 8 | 100.00 | 44.33 | 6515.21 | 7421.51 | 19.56 | 20.43 | 805.64 | 1287.13 | 37.13 | 7320.85 |

Full AIPerf exports, request CSV, resource JSONL/CSV, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
