# AIPerf CPU benchmark

- Image: `local/llama-enhanced-cache:0.1.0`
- Image ID: `sha256:0bf4b86be3de5000cb50eb88d18752978a95525f7291a2f46a9c7370e2a55f3f`
- Started (UTC): 2026-09-20T09:48:00.747005+00:00
- Status: complete
- PVC cache policy: `clear-per-concurrency` (clear before each condition's warmup).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 99.24 | 105.82 | 432.36 | 7.68 | 9.06 | 315.68 | 534.55 | 13068.13 | 421.50 |
| 2 | 100.00 | 97.29 | 536.77 | 1779.84 | 7.81 | 9.36 | 321.57 | 559.03 | 457.29 | 858.34 |
| 4 | 100.00 | 95.18 | 1416.63 | 3409.80 | 8.02 | 9.48 | 329.99 | 577.81 | 139.10 | 1746.62 |
| 8 | 100.00 | 97.47 | 3037.38 | 6922.33 | 7.75 | 9.50 | 319.59 | 562.21 | 61.58 | 3356.97 |

Full AIPerf exports, request CSV, resource JSONL/CSV, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
