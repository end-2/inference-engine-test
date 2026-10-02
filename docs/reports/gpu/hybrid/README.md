> Korean version: [한국어](README-KR.md)
# Jamba base and hybrid GPU comparison

Compared base and hybrid engines on the same weights of the development [AI21 Jamba-tiny-dev](https://huggingface.co/ai21labs/Jamba-tiny-dev) model on an RTX 2060 SUPER 8GB. The model has 318,688,640 parameters and revision `ed303361004ac875426a61675edecf8e9d976882`.

Used PyTorch 2.10.0+cu128, Transformers 4.57.6, FP16, and SDPA. This is a PyTorch path without Mamba-specific kernels. Ran with 4 CPU threads, `n_ctx=288`, `max_parallel=8`, and 5ms batch wait. GPU, RAM, and disk cache budgets are 64, 256, and 1024 MiB respectively.

## Key results

Results for 256 input tokens and 32 output tokens. Throughput is output tok/s with 3 repeats per condition, measuring 2 request bundles per repeat. Each bundle submits as many different inputs concurrently as the concurrency level. Measured request counts per condition are therefore 6 at concurrency 1 and 48 at concurrency 8.

| Condition | Concurrency 1 tok/s | Concurrency 8 tok/s, mean and SD | Concurrency 8 vs base | Concurrency 1 TTFT ms | Concurrency 8 TTFT ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| base, serial generate | 27.51 | 27.51 ± 0.57 | 1.00x | 308.12 | 4385.56 |
| batch, no prefix cache | 26.66 | 201.22 ± 2.80 | 7.31x | 342.58 | 371.55 |
| cold cache | 26.78 | 200.55 ± 3.62 | 7.29x | 341.20 | 376.71 |
| GPU hit | 36.15 | 273.43 ± 5.12 | 9.94x | 33.79 | 34.05 |
| RAM hit | 35.87 | 270.53 ± 4.32 | 9.83x | 37.04 | 39.86 |
| disk hit | 35.34 | 265.94 ± 4.38 | 9.67x | 44.88 | 68.07 |

At concurrency 1, GPU hit throughput rose 31.4% over base and TTFT fell 89.0%. Under the same condition, batch and cold cache were about 3% slower than base. Large gains at high concurrency include the effect of batching reducing serial queueing.

Maximum allocated GPU memory at concurrency 8 was 680.4 MiB for base, 1066.8 MiB for batch and cold, and 657.9 MiB for warm cache conditions. These are PyTorch peak allocated means over the measurement interval, not maxima for model loading and warm checkpoint preparation or total GPU usage.

![Throughput and first-token latency by input length and concurrency](benchmark-suite-20260930-063538/figures/benchmark-comparison.png)

## Verification and measurement scope

Covered 64/256-token inputs, 32-token outputs, concurrency 1/2/4/8, and 6 conditions with 3 repeats. All 288 measurement bundles and 1,080 requests matched base output token IDs and usage. There were no short output lengths, cache errors, or restored token count mismatches. GPU, RAM, and disk conditions were checked to confirm hits occurred at the intended layer for each measurement bundle.

Base also uses in-request dynamic KV and Mamba state. It is the reference implementation without cross-request prefix cache, preallocated hybrid buffers, or batching. Inputs, outputs, dtype, and kernel paths match across both engines.

Excludes HTTP and input tokenization, and includes engine queueing, batch wait, generation, and streamer cost. TTFT uses CPU arrival of the first generated token. Excludes model loading, warmup, cache initialization, and warm checkpoint preparation. Cold conditions include checkpoint creation cost.

Warm conditions have prefixes prepared for all requests. This is not a mixed load assuming production hit ratios. Disk conditions read files written immediately before, so they include OS page cache effects and do not represent physical disk cold-read performance. Sample counts are small, so do not interpret p95 as long-term production tail latency.

During measurement the existing llama.cpp Deployment was kept at 0 replicas to isolate GPU inference, and 1 replica and ready state were restored afterward. The existing CUDA runtime image was connected with this repository `src` and `scripts` read-only. Source SHA-256 was compared again against the workspace after measurement.

## Result files and reproduction

- [Full condition summary](benchmark-suite-20260930-063538/summary.md), [summary CSV](benchmark-suite-20260930-063538/summary.csv), [per-bundle CSV](benchmark-suite-20260930-063538/runs.csv)
- [Execution settings, inputs, reference outputs, and model and source SHA-256](benchmark-suite-20260930-063538/run.json)
- [Verification results](benchmark-suite-20260930-063538/verification.json), [GPU environment and existing service restore state](benchmark-suite-20260930-063538/environment.json)
- [Execution and benchmark guide](../../../guides/hybrid-cache.md#base-and-performance-comparison)

Remeasure with `scripts/benchmark-hybrid.py`. Generate charts with `python scripts/plot-hybrid-benchmark.py <result directory>` in an environment with matplotlib. Per-request token IDs and latency sources are kept in local `requests.jsonl` in the result directory.

These results compare a small Jamba development model on the current PyTorch path. Do not generalize them to large Jamba, Mamba acceleration kernels, CUDA Graph, or HTTP service performance.
