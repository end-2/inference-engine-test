# AIPerf GPU benchmark

- Image: `local/transformers-mamba-cache-gpu:0.1.0`
- Image ID: `sha256:3a1ef33c9fc27e3bc80476f467ddf20423c1102494a7b8e1d1e8a233524cb0d0`
- Started (UTC): 2026-09-30T02:56:34.922097+00:00
- Status: complete
- Device: `gpu`; compute setting: `dtype=float16`.
- PVC cache policy: `clear-before-sweep` (clear once before the first condition's warmup).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 46.09 | 80.40 | 383.26 | 20.23 | 20.88 | 827.32 | 1298.44 | 3104.26 | 907.72 |

| Concurrency | GPU UUID | Samples | GPU avg (%) | GPU max (%) | Memory avg (MiB) | Memory max (MiB) |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | GPU-7b77b97b-2222-89f1-2d5e-5c488faedd7b | 25 | 14.08 | 20.00 | 511.92 | 550.00 |

Full AIPerf exports, request CSV, resource JSONL/CSV, GPU CSV when selected, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.
