# AIPerf CPU benchmark

- Image: `local/transformers-enhanced-batch:0.1.0`
- Image ID: `sha256:d46fbc571c9ea0a971e5adc25225d205ce7b4ba0146b4c29944207102e8cd496`
- Started (UTC): 2026-09-21T11:15:01.489635+00:00
- Status: complete
- PVC cache policy: `preserve` (no PVC cache deletion).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 45.36 | 145.61 | 243.33 | 18.84 | 19.72 | 777.64 | 1241.57 | 993.82 | 923.25 |
| 2 | 100.00 | 62.26 | 306.33 | 413.22 | 26.85 | 42.86 | 1038.95 | 1335.34 | 525.75 | 1345.28 |
| 4 | 100.00 | 78.51 | 734.85 | 760.72 | 38.01 | 45.90 | 1398.48 | 1428.56 | 208.68 | 2133.33 |
| 8 | 100.00 | 80.54 | 2709.96 | 2917.38 | 37.00 | 45.64 | 1367.01 | 1423.92 | 63.58 | 4076.96 |

Full AIPerf exports, request CSV, resource JSONL/CSV, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
