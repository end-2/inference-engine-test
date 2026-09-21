# AIPerf CPU benchmark

- Image: `local/llama-enhanced-batch:0.1.0`
- Image ID: `sha256:1629cba22fdf7a84938cf5d5a278c1421a5da7733223edbc2c7ad061b6922860`
- Started (UTC): 2026-09-20T09:40:49.214568+00:00
- Status: complete
- PVC cache policy: `preserve` (no PVC cache deletion).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 49.06 | 576.28 | 1085.74 | 6.72 | 8.73 | 277.04 | 443.54 | 264.20 | 853.32 |
| 2 | 100.00 | 49.79 | 849.87 | 1456.83 | 19.67 | 45.43 | 826.63 | 1836.14 | 197.96 | 1676.50 |
| 4 | 100.00 | 50.38 | 1318.57 | 2544.89 | 48.77 | 71.83 | 1997.29 | 3439.61 | 124.62 | 3315.86 |
| 8 | 100.00 | 51.82 | 2639.90 | 4198.78 | 91.08 | 129.51 | 3782.83 | 6965.63 | 58.59 | 6422.73 |

Full AIPerf exports, request CSV, resource JSONL/CSV, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
