# AIPerf CPU benchmark

- Image: `local/llama-base:0.1.0`
- Image ID: `sha256:fc89a17727fe472a258de2ff62762c3ddb39fc85ea872aa818f3ce3f6a7436a2`
- Started (UTC): 2026-09-19T08:27:58.432823+00:00
- Status: complete
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 15.62 | 9937.86 | 26058.47 | 13.32 | 16.80 | 2772.77 | 8568.39 | 83.72 | 12710.63 |
| 2 | 100.00 | 15.78 | 22758.67 | 46935.34 | 13.10 | 16.45 | 2721.29 | 8410.96 | 37.27 | 25479.96 |
| 4 | 100.00 | 15.77 | 48469.72 | 79580.63 | 13.07 | 16.52 | 2722.08 | 8450.54 | 17.98 | 51191.80 |
| 8 | 100.00 | 15.71 | 99120.66 | 149788.44 | 13.06 | 16.46 | 2719.96 | 8434.36 | 9.18 | 101840.62 |

Raw AIPerf exports, request CSV, resource JSONL/CSV, and logs are under each `c<concurrency>/` directory.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
