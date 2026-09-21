# AIPerf CPU benchmark

- Image: `local/llama-enhanced-cache:0.1.0`
- Image ID: `sha256:0bf4b86be3de5000cb50eb88d18752978a95525f7291a2f46a9c7370e2a55f3f`
- Started (UTC): 2026-09-20T10:10:20.699662+00:00
- Status: complete
- PVC cache policy: `clear-before-sweep` (clear once before the first condition's warmup).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 98.39 | 105.96 | 438.82 | 7.75 | 9.34 | 319.15 | 553.06 | 13937.15 | 425.11 |
| 2 | 100.00 | 130.24 | 329.86 | 570.91 | 7.57 | 9.15 | 310.42 | 533.65 | 784.74 | 640.27 |
| 4 | 100.00 | 130.29 | 962.98 | 1287.07 | 7.51 | 9.19 | 308.52 | 517.20 | 394.84 | 1271.50 |
| 8 | 100.00 | 133.98 | 2126.67 | 2527.58 | 7.39 | 8.77 | 301.51 | 513.61 | 263.28 | 2428.19 |

Full AIPerf exports, request CSV, resource JSONL/CSV, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
