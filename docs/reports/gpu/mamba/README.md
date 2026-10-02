> Korean version: [한국어](README-KR.md)
# Mamba GPU test results

Compared the baseline engine and cross-request prefix state cache for `state-spaces/mamba-130m-hf` on an RTX 2060 SUPER 8GB. Used PyTorch 2.10.0+cu128, Transformers 4.57.6, and FP16. Both engines use a plain PyTorch CUDA path without Mamba-specific kernels.

## AIPerf verification

Ran once per condition at concurrency 1 with 2 warmup and 100 measured requests. Input/output distribution is `64,32:50;256,64:50`, with 16 dataset entries, seed 42, and sequential input reuse. Cache was cleared before the sweep, so warmup and early measurement misses are included. The baseline engine was measured first.

| Condition | Requests | Mean TTFT (ms) | Mean response time (ms) | Output tok/s | Max GPU memory (MiB) | Source |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| base | 100 | 252.44 | 1037.65 | 40.33 | 550 | [summary](aiperf-base-20260930/bench-20260930-025300-141375-local-transformers-mamba-base-gpu-0.1.0/summary.md) |
| cache | 100 | 80.40 | 907.72 | 46.09 | 550 | [summary](aiperf-cache-20260930/bench-20260930-025634-922097-local-transformers-mamba-cache-gpu-0.1.0/summary.md) |

In this run mean TTFT fell 68.1% and output throughput rose 14.3%. Both conditions had no request failures or short output lengths. Each condition was measured once, so no repeat error margin was computed.

The shared API does not expose cached token counts in usage. AIPerf prompt-cache hit metrics were not used, and cache behavior was verified through engine restore checks and shutdown logs.

Shutdown logs record 84 RAM hits, 0 disk hits, 18 misses, 10284 restored tokens, and 0 cache errors. This total includes 2 warmup requests.

## Correctness and state restore

[Serial engine verification](cache-check-20260930/summary.md) confirms baseline, cold, warm, and post-restart disk restore match for 64/256-token inputs and 16-token outputs. First text callback time is recorded separately from AIPerf TTFT.

Python tests pass 119 regression and 4 live HTTP tests. They check GPU FP32/FP16, prefix branches and short inputs, corruption recovery, cancellation, sampling, SSE, and 4 concurrent request result isolation. Two existing SmolLM2 pretrained model integration tests were excluded from this run.

## Reproduction

Follow the [Mamba execution and test guide](../../../guides/mamba-cache.md). Model revision is in [state restore verification metadata](cache-check-20260930/run.json), and image digests are in each AIPerf run `run.json`. Measurement settings are in the corresponding `run.json` and AIPerf reports. The verified GPU images are loaded on the worker, so rerun with the build-skip command in the guide.

Images were built from this repository Dockerfile using the existing CUDA runtime as OCI build context. General Docker storage had insufficient free space, so build state and OCI export were placed on a work disk. After measurement the Mamba Deployment was left at 0 replicas and the existing llama.cpp Deployment 1 replica was restored.
