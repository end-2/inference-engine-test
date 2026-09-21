# AIPerf CPU benchmark

- Image: `local/transformers-enhanced-batch:0.1.0`
- Image ID: `sha256:d46fbc571c9ea0a971e5adc25225d205ce7b4ba0146b4c29944207102e8cd496`
- Started (UTC): 2026-09-21T10:38:16.323173+00:00
- Status: complete
- PVC cache policy: `preserve` (no PVC cache deletion).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 45.35 | 145.36 | 237.21 | 18.88 | 19.78 | 778.15 | 1244.40 | 995.39 | 923.51 |
| 2 | 100.00 | 62.32 | 305.86 | 413.82 | 26.84 | 42.68 | 1038.13 | 1327.48 | 524.65 | 1343.99 |
| 4 | 100.00 | 78.68 | 733.72 | 763.46 | 37.92 | 45.82 | 1395.14 | 1433.85 | 209.00 | 2128.85 |
| 8 | 100.00 | 78.69 | 2777.31 | 2916.87 | 37.98 | 45.96 | 1397.67 | 1437.34 | 59.74 | 4174.98 |

Full AIPerf exports, request CSV, resource JSONL/CSV, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
