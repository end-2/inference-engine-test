> Korean version: [한국어](summary-KR.md)

# Mamba Prefix State Cache GPU Verification

- Model: `state-spaces/mamba-130m-hf`, revision `1e76775f628fbf1350fbe4dbb3d971ba64af25a1`
- Environment: RTX 2060 SUPER 8GB, PyTorch 2.10.0+cu128, Transformers 4.57.6, FP16
- Kernel: generic PyTorch CUDA path. No Mamba-specific kernels were used.
- Conditions: concurrency 1, input 64/256 tokens, 16 output tokens, greedy decoding. Measured base, cold, and warm 3 times each, and disk restore once.
- Excluded initial model loading and warmup. Response body, finish reason, and usage for the same token input matched across all conditions.
- Results are from direct engine calls. Excludes HTTP and request queueing; first-text latency is the time until the first non-empty TextStreamer callback.

| Input Tokens | Condition | Avg Response Time (ms) | Avg First Text (ms) | Avg Output tok/s |
| ---: | --- | ---: | ---: | ---: |
| 64 | base | 426.52 | 133.88 | 37.52 |
| 64 | cold | 447.84 | 155.55 | 35.73 |
| 64 | warm | 314.98 | 22.53 | 50.80 |
| 64 | disk-restart | 321.55 | 26.48 | 49.76 |
| 256 | base | 828.01 | 556.56 | 19.59 |
| 256 | cold | 852.06 | 577.38 | 19.01 |
| 256 | warm | 314.69 | 42.09 | 50.84 |
| 256 | disk-restart | 326.68 | 46.57 | 48.98 |

`cold` includes prefix computation and state serialization. `warm` restores the state from the immediately preceding identical request. `disk-restart` shuts down the engine, reloads it, then restores the disk checkpoint.

The reused prefix length is 63 for 64-token input and 255 for 256-token input. The last input token is recomputed to obtain logits. Each state file is 1,478,216 bytes, excluding token IDs and store header size.

Measurement samples are small and base, cold, and warm were not run in fully randomized order. The numbers verify prefix-reuse behavior and cost in the same environment; they do not represent dedicated CUDA kernels or other models.

[Per-request raw data and run conditions](run.json), [reproduction commands and implementation rules](../../../../guides/mamba-cache.md)

## Functional Verification

- Transformers regression tests: 50 passed. 6 requiring a separate server or the existing SmolLM2 model path were excluded from that run.
- Real Mamba HTTP server tests: 4 passed. Verified repeated requests, SSE and usage, 4 concurrent requests, multiple messages with EOS allowed.
- Benchmark runner and suite: 52 passed. GPU path and manifests: 10 passed. Shared cache store: 7 passed.
- Checksum, retry, and model-selection tests for model download, existing Transformers manifest checks, and Kubernetes server dry run of the new GPU manifest passed.

The GPU image uses the repository Dockerfile and reuses the existing CUDA image as the runtime build context. Build status and OCI artifacts were kept on the work disk and brought to the GPU worker. The verification image digest is recorded in `run.json`.
