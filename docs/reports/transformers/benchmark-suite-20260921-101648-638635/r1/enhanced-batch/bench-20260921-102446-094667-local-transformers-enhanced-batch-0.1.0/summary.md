# AIPerf CPU benchmark

- Image: `local/transformers-enhanced-batch:0.1.0`
- Image ID: `sha256:d46fbc571c9ea0a971e5adc25225d205ce7b4ba0146b4c29944207102e8cd496`
- Started (UTC): 2026-09-21T10:24:46.094667+00:00
- Status: complete
- PVC cache policy: `preserve` (no PVC cache deletion).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 45.47 | 144.99 | 238.78 | 18.81 | 19.67 | 775.92 | 1238.94 | 998.22 | 920.90 |
| 2 | 100.00 | 62.05 | 306.88 | 418.40 | 26.96 | 42.99 | 1042.87 | 1341.26 | 524.51 | 1349.76 |
| 4 | 100.00 | 78.39 | 733.17 | 764.79 | 38.16 | 46.51 | 1403.89 | 1448.42 | 209.09 | 2137.06 |
| 8 | 100.00 | 78.74 | 2781.74 | 2968.38 | 37.83 | 45.62 | 1392.05 | 1424.18 | 59.71 | 4173.79 |

Full AIPerf exports, request CSV, resource JSONL/CSV, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
