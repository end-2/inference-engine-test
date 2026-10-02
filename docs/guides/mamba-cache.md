> Korean version: [한국어](mamba-cache-KR.md)

# Mamba State Cache

Measures prefix state reuse across requests with `state-spaces/mamba-130m-hf`. The model revision and file checksums are pinned in the [model config](../../config/models/mamba-130m-transformers.env) and [SHA-256 list](../../config/models/mamba-130m-transformers.sha256). It is separate from the KV engine for SmolLM2.

| Configuration | Python entry point | VARIANT |
| --- | --- | --- |
| Compute prompt per request | `transformer.mamba.server` | `transformers-mamba-base` |
| Reuse prefix state | `transformer.mamba.cache.server` | `transformers-mamba-cache` |

Both configurations use Mamba's recurrent cache during generation. The comparison is whether prefix state is reused across requests. The server processes requests serially, and increased concurrency appears as queueing. Mamba batching and CUDA graphs are not supported.

## GPU runs

Prepare the [GPU environment](benchmark.md#gpu-benchmarks), then run from the repository root.

```sh
make download-model DEVICE=gpu VARIANT=transformers-mamba-cache
make benchmark DEVICE=gpu VARIANT=transformers-mamba-base
make benchmark DEVICE=gpu VARIANT=transformers-mamba-cache
```

Each command includes image build, load, deployment, and AIPerf measurement. The base and cache Mamba engines share `Deployment/transformers-mamba-base`. The GPU benchmark runner stops other inference engines to free the GPU. Results are stored in `docs/reports/gpu/mamba/`.

If images are already loaded on the GPU worker and control plane, as in the validation environment, skip the build with the following command. The base engine omits `--image`, `--manifests`, and `--cache-policy`.

```sh
python scripts/run-benchmark.py --backend mamba --device gpu \
  --build-context '' --benchmark-build-context '' --concurrencies 1 \
  --image local/transformers-mamba-cache-gpu:0.1.0 \
  --manifests k8s/gpu/transformers-mamba-cache --cache-policy clear-before-sweep
```

A full repetition covers three conditions: the base engine, cache cleared per concurrency, and cache cleared only at sweep start. Each condition uses 2 warmup and 100 measured requests at concurrencies `1,2,4,8`.

```sh
make benchmark-suite DEVICE=gpu VARIANT=transformers-mamba-base REPETITIONS=3
```

To deploy only the server, use the following commands. On a single-GPU setup, first scale other running inference Deployments to 0 replicas.

```sh
make build-image load-image DEVICE=gpu VARIANT=transformers-mamba-cache
./scripts/local-k8s-gpu.sh kubectl apply -f k8s/gpu/transformers-mamba-cache
./scripts/local-k8s-gpu.sh kubectl rollout status deployment/transformers-mamba-base --timeout=300s
./scripts/local-k8s-gpu.sh kubectl port-forward service/transformers-mamba-base 8000:8000
```

For CPU, use `DEVICE=cpu` and `k8s/transformers-mamba-cache`. Local run dependencies follow [Transformers requirements](../../src/transformer/requirements.txt).

```sh
PYTHONPATH=src python -m transformer.mamba.cache.server \
  --model .models/mamba-130m --device cuda --dtype float16 \
  --cache-dir /tmp/mamba-cache
```

## Cache rules

- Serializes each layer's convolution and SSM state to safetensors. RAM LRU and disk spill reuse the existing store with a separate namespace and PVC.
- Saves the state just before the last prompt token. Even on a cache hit for the same prompt, recomputes the last token to obtain next-token logits.
- Restores only when the full saved prefix matches the start of the input. Does not truncate a longer state or reuse the state of a prefix that diverged in the middle.
- After restore, processes the remaining prefix tokens one by one. With a long remaining suffix, it can be slower than the base engine, which processes the full prompt at once.
- Saves state before generation starts, so generated tokens and cancelled generations do not mix into checkpoints. Copies into a request-local buffer on restore.
- The namespace reflects model files, library versions, kernel path, dtype, device, context limits, and thread count. Discards corrupt checkpoints and recomputes the prompt.

Cache options are `--cache-dir`, `--cache-ram-mib`, `--cache-disk-mib`, and `--cache-min-prefix`. The minimum length applies to the saved prefix length excluding the last token. Setting both RAM and disk budgets to 0 disables reuse across requests. Cache state tensor size does not depend on input length, but stored token IDs and checkpoint count add separate costs.

## Model and kernels

This checkpoint is not an instruction model and has no chat template. Pass a single user message as raw text, and join multiple messages in the `System:`, `User:`, `Assistant:` format. If the tokenizer has a chat template, use that template. The API model name is `state-spaces/mamba-130m-hf`.

The Mamba execution path in the provided image is PyTorch. It does not install the `mamba-ssm` or `causal-conv1d` accelerated kernels. It runs on this path even on CUDA devices, and the startup log records `kernel_backend`. Dedicated kernel performance needs separate compatibility checks and measurement.

## Tests

Requires the Transformers dependencies plus `httpx` for HTTP tests and [requirements](../../src/transformer/base_metric/requirements.txt) for metric tests.

```sh
python -m unittest discover -s tests -p 'test_transformers_*.py' -v
python -m unittest discover -s tests -p 'test_enhanced_cache_llamacpp.py' -v
python -m unittest discover -s tests -p 'test_gpu_benchmark.py' -v
sh tests/test-download-transformers-model.sh
```

Checks prefix match and branching, corruption recovery, restart, streaming, sampling, cancellation, and cross-request isolation with a small random model. Also checks FP32 and FP16 when CUDA is available.

To compare base, cold, warm, and disk-restore output on the real model and measure serial latency, use:

```sh
python scripts/check-mamba-cache.py --model .models/mamba-130m \
  --device cuda --dtype float16 --prompt-lengths 64,256 \
  --max-tokens 16 --repetitions 3 --report reports/mamba/summary.json
```

This check excludes HTTP and queueing. `first_text_ms` is the time until the first non-empty string callback of TextStreamer and can differ from the first generated token time. `cold` includes snapshot save cost, and `warm` measures same-prompt reuse. Restart is measured once per input length.

With the real base and cache servers each running, compare HTTP, SSE, and concurrent request results.

```sh
TEST_MAMBA_BASE_URL=http://127.0.0.1:18081 \
TEST_MAMBA_CACHE_URL=http://127.0.0.1:18082 \
python -m unittest discover -s tests -p 'test_transformers_mamba_api.py' -v
```
