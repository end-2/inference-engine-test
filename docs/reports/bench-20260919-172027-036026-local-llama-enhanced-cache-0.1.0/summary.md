# AIPerf CPU benchmark

- Image: `local/llama-enhanced-cache:0.1.0`
- Image ID: `sha256:0bf4b86be3de5000cb50eb88d18752978a95525f7291a2f46a9c7370e2a55f3f`
- Started (UTC): 2026-09-19T17:20:27.036026+00:00
- Status: complete
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 103.21 | 106.21 | 442.50 | 7.27 | 8.42 | 299.04 | 499.70 | 13743.99 | 405.25 |
| 2 | 100.00 | 138.85 | 311.44 | 513.15 | 7.06 | 8.65 | 289.10 | 480.69 | 802.67 | 600.54 |
| 4 | 100.00 | 144.59 | 865.25 | 1175.97 | 6.78 | 8.18 | 278.53 | 454.61 | 417.80 | 1143.78 |
| 8 | 100.00 | 142.90 | 1985.35 | 2332.25 | 6.84 | 8.14 | 280.77 | 466.63 | 281.14 | 2266.13 |

Raw AIPerf exports, request CSV, resource JSONL/CSV, and logs are under each `c<concurrency>/` directory.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
