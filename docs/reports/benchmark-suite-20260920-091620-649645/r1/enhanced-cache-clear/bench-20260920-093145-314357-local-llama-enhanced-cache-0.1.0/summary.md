# AIPerf CPU benchmark

- Image: `local/llama-enhanced-cache:0.1.0`
- Image ID: `sha256:0bf4b86be3de5000cb50eb88d18752978a95525f7291a2f46a9c7370e2a55f3f`
- Started (UTC): 2026-09-20T09:31:45.314357+00:00
- Status: complete
- PVC cache policy: `clear-per-concurrency` (before each condition's warmup).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 98.93 | 106.29 | 430.70 | 7.73 | 9.42 | 316.49 | 539.52 | 13362.69 | 422.78 |
| 2 | 100.00 | 100.10 | 524.38 | 1745.81 | 7.59 | 9.35 | 309.65 | 526.87 | 471.53 | 834.04 |
| 4 | 100.00 | 98.78 | 1367.29 | 3269.51 | 7.66 | 9.44 | 315.00 | 526.58 | 144.19 | 1682.29 |
| 8 | 100.00 | 98.23 | 3012.35 | 6903.84 | 7.65 | 9.20 | 316.55 | 555.54 | 61.60 | 3328.90 |

Raw AIPerf exports, request CSV, resource JSONL/CSV, and logs are under each `c<concurrency>/` directory.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
