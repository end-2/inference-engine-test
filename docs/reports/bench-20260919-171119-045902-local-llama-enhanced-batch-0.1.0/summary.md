# AIPerf CPU benchmark

- Image: `local/llama-enhanced-batch:0.1.0`
- Image ID: `sha256:1629cba22fdf7a84938cf5d5a278c1421a5da7733223edbc2c7ad061b6922860`
- Started (UTC): 2026-09-19T17:11:19.045902+00:00
- Status: complete
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 49.85 | 576.90 | 1091.35 | 6.39 | 7.00 | 262.84 | 415.17 | 264.06 | 839.75 |
| 2 | 100.00 | 50.63 | 859.86 | 1445.45 | 18.76 | 45.16 | 788.72 | 1804.59 | 195.69 | 1648.58 |
| 4 | 100.00 | 51.84 | 1402.22 | 2713.48 | 44.33 | 70.25 | 1820.16 | 3189.60 | 115.57 | 3222.38 |
| 8 | 100.00 | 52.19 | 2165.91 | 3623.31 | 102.31 | 137.67 | 4216.05 | 7689.31 | 72.60 | 6381.97 |

Raw AIPerf exports, request CSV, resource JSONL/CSV, and logs are under each `c<concurrency>/` directory.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
