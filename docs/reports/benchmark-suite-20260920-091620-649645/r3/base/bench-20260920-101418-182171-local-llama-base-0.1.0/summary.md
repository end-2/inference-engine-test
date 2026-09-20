# AIPerf CPU benchmark

- Image: `local/llama-base:0.1.0`
- Image ID: `sha256:4710ee54b1a7868bbbaf1cff55ffa2fe553294d5bb70371a67dd58c6e8ebe539`
- Started (UTC): 2026-09-20T10:14:18.182171+00:00
- Status: complete
- PVC cache policy: `preserve` (before each condition's warmup).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 43.56 | 627.19 | 1112.92 | 8.21 | 10.18 | 333.98 | 544.67 | 235.76 | 961.17 |
| 2 | 100.00 | 43.77 | 1575.36 | 2072.97 | 8.16 | 9.50 | 333.87 | 546.87 | 98.33 | 1909.22 |
| 4 | 100.00 | 44.30 | 3425.18 | 4289.17 | 8.05 | 9.61 | 328.52 | 526.50 | 46.23 | 3753.70 |
| 8 | 100.00 | 44.46 | 7008.16 | 7963.61 | 7.96 | 9.54 | 328.90 | 558.52 | 24.36 | 7337.06 |

Raw AIPerf exports, request CSV, resource JSONL/CSV, and logs are under each `c<concurrency>/` directory.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
