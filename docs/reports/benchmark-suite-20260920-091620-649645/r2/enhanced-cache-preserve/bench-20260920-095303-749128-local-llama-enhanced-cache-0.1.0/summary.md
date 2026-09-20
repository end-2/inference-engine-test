# AIPerf CPU benchmark

- Image: `local/llama-enhanced-cache:0.1.0`
- Image ID: `sha256:0bf4b86be3de5000cb50eb88d18752978a95525f7291a2f46a9c7370e2a55f3f`
- Started (UTC): 2026-09-20T09:53:03.749128+00:00
- Status: complete
- PVC cache policy: `clear-before-sweep` (clear once before the first condition's warmup).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 97.04 | 109.05 | 442.39 | 7.86 | 9.19 | 321.93 | 548.51 | 12330.75 | 430.98 |
| 2 | 100.00 | 125.03 | 345.22 | 579.65 | 7.86 | 9.71 | 321.96 | 553.51 | 750.80 | 667.18 |
| 4 | 100.00 | 130.57 | 959.63 | 1267.53 | 7.56 | 9.60 | 308.09 | 503.22 | 393.05 | 1267.72 |
| 8 | 100.00 | 127.21 | 2235.92 | 2654.62 | 7.73 | 9.83 | 317.40 | 547.74 | 267.82 | 2553.32 |

Full AIPerf exports, request CSV, resource JSONL/CSV, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
