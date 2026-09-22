# AIPerf CPU benchmark

- Image: `local/transformers-enhanced-cache:0.1.0`
- Image ID: `sha256:6c900feed1fd8de408d6cfefe89883caf3272678dca83414e3fd014a2deee21b`
- Started (UTC): 2026-09-22T06:36:24.154551+00:00
- Status: complete
- PVC cache policy: `clear-before-sweep` (clear once before the first condition's warmup).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 47.11 | 76.56 | 119.77 | 19.71 | 20.45 | 811.18 | 1287.76 | 2101.63 | 887.75 |
| 2 | 100.00 | 47.65 | 939.18 | 1444.52 | 19.72 | 21.35 | 812.52 | 1299.41 | 224.32 | 1751.71 |
| 4 | 100.00 | 48.12 | 2638.55 | 3423.88 | 19.55 | 20.42 | 805.48 | 1286.58 | 98.33 | 3444.03 |
| 8 | 100.00 | 48.49 | 5894.48 | 6709.28 | 19.40 | 20.24 | 799.06 | 1274.99 | 64.33 | 6693.54 |

Full AIPerf exports, request CSV, resource JSONL/CSV, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
