# AIPerf CPU benchmark

- Image: `local/llama-enhanced-batch:0.1.0`
- Image ID: `sha256:1629cba22fdf7a84938cf5d5a278c1421a5da7733223edbc2c7ad061b6922860`
- Started (UTC): 2026-09-20T09:24:34.166531+00:00
- Status: complete
- PVC cache policy: `preserve` (no PVC cache deletion).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 49.67 | 567.24 | 1067.59 | 6.68 | 8.27 | 275.69 | 455.31 | 268.29 | 842.93 |
| 2 | 100.00 | 50.22 | 857.03 | 1444.34 | 19.15 | 44.97 | 805.23 | 1804.05 | 196.49 | 1662.26 |
| 4 | 100.00 | 50.94 | 1370.60 | 2730.90 | 46.51 | 71.03 | 1909.41 | 3420.31 | 117.47 | 3280.00 |
| 8 | 100.00 | 51.72 | 2588.48 | 4269.41 | 93.25 | 146.20 | 3848.86 | 6665.22 | 62.34 | 6437.34 |

Full AIPerf exports, request CSV, resource JSONL/CSV, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
