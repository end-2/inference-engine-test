# AIPerf GPU benchmark

- Image: `local/transformers-mamba-base-gpu:0.1.0`
- Image ID: `sha256:9be1e1cbd31c67029225272e4c63e28753264465f35b34cd8e05c44d56debdf1`
- Started (UTC): 2026-09-30T02:53:00.141375+00:00
- Status: complete
- Device: `gpu`; compute setting: `dtype=float16`.
- PVC cache policy: `preserve` (no PVC cache deletion).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 40.33 | 252.44 | 517.78 | 19.21 | 19.86 | 785.21 | 1224.11 | 473.68 | 1037.65 |

| Concurrency | GPU UUID | Samples | GPU avg (%) | GPU max (%) | Memory avg (MiB) | Memory max (MiB) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | GPU-7b77b97b-2222-89f1-2d5e-5c488faedd7b | 27 | 15.22 | 21.00 | 516.81 | 550.00 |

Full AIPerf exports, request CSV, resource JSONL/CSV, GPU CSV when selected, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
