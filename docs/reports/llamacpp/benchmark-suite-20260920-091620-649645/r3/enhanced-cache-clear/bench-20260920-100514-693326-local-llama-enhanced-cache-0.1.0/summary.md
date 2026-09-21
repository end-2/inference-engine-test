# AIPerf CPU benchmark

- Image: `local/llama-enhanced-cache:0.1.0`
- Image ID: `sha256:0bf4b86be3de5000cb50eb88d18752978a95525f7291a2f46a9c7370e2a55f3f`
- Started (UTC): 2026-09-20T10:05:14.693326+00:00
- Status: complete
- PVC cache policy: `clear-per-concurrency` (clear before each condition's warmup).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 98.61 | 106.38 | 441.65 | 7.72 | 9.15 | 317.79 | 554.36 | 13778.39 | 424.17 |
| 2 | 100.00 | 98.19 | 533.50 | 1760.69 | 7.71 | 8.96 | 317.13 | 538.69 | 463.95 | 850.64 |
| 4 | 100.00 | 97.65 | 1380.94 | 3312.46 | 7.82 | 9.27 | 319.85 | 532.30 | 141.53 | 1700.79 |
| 8 | 100.00 | 97.22 | 3046.39 | 6920.97 | 7.78 | 9.67 | 319.98 | 537.69 | 60.89 | 3366.37 |

Full AIPerf exports, request CSV, resource JSONL/CSV, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
