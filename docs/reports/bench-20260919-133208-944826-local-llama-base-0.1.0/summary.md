# AIPerf CPU benchmark

- Image: `local/llama-base:0.1.0`
- Image ID: `sha256:2c12f55c1879205493cddca2025d968620faef1cfd0e466397b93fd2167a0dc2`
- Started (UTC): 2026-09-19T13:32:08.944826+00:00
- Status: complete
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 44.10 | 642.53 | 1145.46 | 7.51 | 8.61 | 306.97 | 508.35 | 230.09 | 949.50 |
| 2 | 100.00 | 45.58 | 1531.78 | 2009.92 | 7.34 | 8.56 | 301.71 | 507.52 | 101.12 | 1833.49 |
| 4 | 100.00 | 45.74 | 3330.85 | 4182.98 | 7.48 | 9.02 | 304.74 | 491.36 | 47.45 | 3635.58 |
| 8 | 100.00 | 46.02 | 6787.63 | 7775.31 | 7.43 | 8.84 | 303.39 | 500.49 | 24.92 | 7091.02 |

Raw AIPerf exports, request CSV, resource JSONL/CSV, and logs are under each `c<concurrency>/` directory.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
