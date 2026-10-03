> Korean version: [한국어](README-KR.md)
# Test results

Reports are separated by measured inference backend.

- [llama.cpp results](llamacpp/README.md): Qwen2.5 GGUF, base, batch, cache, stability and HPA experiments
- [Transformers results](transformers/README.md): SmolLM2-135M-Instruct FP32, base, batch, cache performance comparison, node failure recovery and CPU HPA experiments
- [GPU results](gpu/README.md): Transformers and llama.cpp throughput, Mamba state cache and Jamba hybrid engine comparisons
- [MPS model co-execution check](gpu/mps-check-20260930/summary.md): CUDA creation check for 6 model combinations on the same GPU
- [GPU Prefill/Decode experiment summary](gpu/pd/README.md): 2-way and 4-way split performance, Router memory, token budget and SLO results

Each report original preserves the image name and execution settings from measurement time. For execution see the [benchmark guide](../guides/benchmark.md), and for AIPerf see the [AIPerf guide](../guides/aiperf.md).

For PD experiment report structure, aggregation checks, and Git preservation scope, follow the [experiment results organization guide](../guides/experiment-results.md).
