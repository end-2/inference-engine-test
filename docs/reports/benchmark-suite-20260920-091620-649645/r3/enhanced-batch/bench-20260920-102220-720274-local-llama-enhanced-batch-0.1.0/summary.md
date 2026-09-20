# AIPerf CPU benchmark

- Image: `local/llama-enhanced-batch:0.1.0`
- Image ID: `sha256:1629cba22fdf7a84938cf5d5a278c1421a5da7733223edbc2c7ad061b6922860`
- Started (UTC): 2026-09-20T10:22:20.720274+00:00
- Status: complete
- PVC cache policy: `preserve` (before each condition's warmup).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 49.33 | 574.45 | 1083.56 | 6.68 | 8.43 | 274.27 | 440.87 | 265.19 | 848.72 |
| 2 | 100.00 | 50.43 | 856.01 | 1446.11 | 19.02 | 45.18 | 799.18 | 1813.16 | 197.66 | 1655.19 |
| 4 | 100.00 | 50.39 | 1313.67 | 2551.24 | 48.92 | 71.56 | 2002.38 | 3475.54 | 126.74 | 3316.05 |
| 8 | 100.00 | 51.52 | 2348.25 | 3684.47 | 99.49 | 135.04 | 4114.88 | 7569.22 | 67.37 | 6463.13 |

Raw AIPerf exports, request CSV, resource JSONL/CSV, and logs are under each `c<concurrency>/` directory.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
