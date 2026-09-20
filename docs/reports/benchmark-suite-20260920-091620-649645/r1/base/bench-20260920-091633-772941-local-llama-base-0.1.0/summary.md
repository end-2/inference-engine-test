# AIPerf CPU benchmark

- Image: `local/llama-base:0.1.0`
- Image ID: `sha256:4710ee54b1a7868bbbaf1cff55ffa2fe553294d5bb70371a67dd58c6e8ebe539`
- Started (UTC): 2026-09-20T09:16:33.772941+00:00
- Status: complete
- PVC cache policy: `preserve` (no PVC cache deletion).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 42.58 | 636.00 | 1140.82 | 8.46 | 10.13 | 347.51 | 585.53 | 232.67 | 983.51 |
| 2 | 100.00 | 43.73 | 1574.11 | 2051.19 | 8.29 | 9.94 | 337.02 | 544.37 | 98.23 | 1911.13 |
| 4 | 100.00 | 44.04 | 3441.00 | 4301.56 | 8.23 | 9.92 | 334.05 | 543.51 | 46.02 | 3775.05 |
| 8 | 100.00 | 44.66 | 6975.36 | 7940.46 | 8.03 | 9.44 | 328.09 | 552.78 | 24.23 | 7303.44 |

Full AIPerf exports, request CSV, resource JSONL/CSV, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
