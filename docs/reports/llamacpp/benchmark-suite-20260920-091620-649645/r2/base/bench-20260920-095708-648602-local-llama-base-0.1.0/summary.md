# AIPerf CPU benchmark

- Image: `local/llama-base:0.1.0`
- Image ID: `sha256:4710ee54b1a7868bbbaf1cff55ffa2fe553294d5bb70371a67dd58c6e8ebe539`
- Started (UTC): 2026-09-20T09:57:08.648602+00:00
- Status: complete
- PVC cache policy: `preserve` (no PVC cache deletion).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 43.59 | 622.84 | 1105.16 | 8.19 | 9.83 | 337.76 | 573.36 | 237.59 | 960.60 |
| 2 | 100.00 | 43.99 | 1567.48 | 2064.06 | 8.10 | 10.40 | 332.48 | 550.92 | 98.99 | 1899.96 |
| 4 | 100.00 | 43.76 | 3461.67 | 4366.27 | 8.26 | 10.38 | 338.13 | 553.72 | 45.88 | 3799.80 |
| 8 | 100.00 | 44.24 | 7044.25 | 8050.63 | 8.16 | 9.71 | 334.23 | 558.41 | 24.06 | 7378.48 |

Full AIPerf exports, request CSV, resource JSONL/CSV, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
