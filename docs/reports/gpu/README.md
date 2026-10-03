> Korean version: [한국어](README-KR.md)
# GPU inference benchmark results

> **Note:** The earlier CPU benchmarks and these GPU benchmarks use different host environments and cluster layouts, so do not compare performance figures directly.

AIPerf results below for Transformers and llama.cpp are single runs of each implementation. Concurrency is `1,2,4,8` with 2 warmup requests and 100 measured requests per condition. Inference Pods ran on a worker with an RTX 2060 SUPER, and AIPerf ran on the control-plane.

| Engine | Model | GPU setting | Measured conditions | Result |
| --- | --- | --- | --- | --- |
| Transformers | `HuggingFaceTB/SmolLM2-135M-Instruct` | `dtype=float16` | base, batch, cache | [First run summary](transformers/benchmark-suite-20260928-141725-165948/summary.md) |
| llama.cpp | `Qwen/Qwen2.5-0.5B-Instruct` | `n_gpu_layers=-1` | base, batch, cache clear, cache preserve | [First run summary](llamacpp/benchmark-suite-20260928-144903-213311/summary.md) |

Each summary has per-concurrency throughput, latency, and mean and maximum GPU utilization and used memory. `run.json` has execution settings and image IDs, and `gpu.csv` time series are kept in the local result directory.

For Transformers batch `max-parallel` setting experiments see the [setting experiment report](transformers/batch-config-tuning-20260928.md), and for GPU-only batch implementation results see the [optimization report](transformers/batch-gpu-optimization-20260928.md).

For comparison of actual model outputs at high GPU batch concurrency see the [output validation report](transformers/batch-gpu-output-validation-20260929.md).

For Mamba-130M prefix state cache implementation, correctness checks, and concurrency-1 AIPerf comparison see [Mamba GPU test results](mamba/README.md).

For base, batch, and GPU/RAM/disk HiCache comparison on the same Jamba-tiny-dev weights see [Jamba hybrid GPU results](hybrid/README.md). These results are engine measurements excluding HTTP.

For concurrent model checks on shared GPU resources, see [MPS model validation](mps-check-20260930/summary.md). The [Prefill/Decode experiment index](pd/README.md) covers two-slot and four-slot placement, token-budget scheduling and SLO results.
