# AIPerf CPU benchmark

- Image: `local/llama-base:0.1.0`
- Image ID: `sha256:4710ee54b1a7868bbbaf1cff55ffa2fe553294d5bb70371a67dd58c6e8ebe539`
- Started (UTC): 2026-09-19T17:02:40.905728+00:00
- Status: complete
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 44.23 | 641.90 | 1159.68 | 7.46 | 8.61 | 304.83 | 497.07 | 230.90 | 946.73 |
| 2 | 100.00 | 45.72 | 1527.60 | 2018.44 | 7.34 | 8.80 | 300.32 | 481.73 | 101.33 | 1827.92 |
| 4 | 100.00 | 45.86 | 3323.24 | 4171.97 | 7.42 | 8.79 | 303.36 | 475.60 | 47.58 | 3626.60 |
| 8 | 100.00 | 45.75 | 6824.27 | 7730.38 | 7.55 | 9.08 | 308.58 | 511.86 | 24.72 | 7132.85 |

Full AIPerf exports, request CSV, resource JSONL/CSV, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
