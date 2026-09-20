# AIPerf CPU benchmark

- Image: `local/llama-enhanced-cache:0.1.0`
- Image ID: `sha256:0bf4b86be3de5000cb50eb88d18752978a95525f7291a2f46a9c7370e2a55f3f`
- Started (UTC): 2026-09-20T09:36:46.261612+00:00
- Status: complete
- PVC cache policy: `clear-before-sweep` (clear once before the first condition's warmup).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 97.02 | 106.21 | 443.82 | 7.88 | 9.26 | 324.80 | 564.69 | 13768.99 | 431.00 |
| 2 | 100.00 | 129.17 | 334.66 | 538.60 | 7.61 | 8.93 | 310.94 | 517.92 | 755.09 | 645.59 |
| 4 | 100.00 | 127.17 | 987.23 | 1346.39 | 7.65 | 9.25 | 316.28 | 550.12 | 386.08 | 1303.51 |
| 8 | 100.00 | 128.84 | 2208.90 | 2623.92 | 7.60 | 9.51 | 313.37 | 529.81 | 267.10 | 2522.27 |

Full AIPerf exports, request CSV, resource JSONL/CSV, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
