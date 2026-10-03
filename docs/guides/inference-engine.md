> Korean version: [한국어](inference-engine-KR.md)

# Inference engine

Run and configure base, enhanced/batch, and enhanced/cache inference servers. The default device is CPU; [GPU benchmarks](benchmark.md#gpu-benchmarks) are also supported. The default engine is Transformers with PyTorch; llama.cpp is also available. Batching and caching are independent implementations for both engines.

Follow the Transformers procedure below; for llama.cpp follow [that engine's procedure](#llamacpp). For manifest and ConfigMap handling, see [manifest management](manifests.md).

## Transformers

`src/transformer/` runs local `HuggingFaceTB/SmolLM2-135M-Instruct` with PyTorch. Base is serial inference, enhanced/batch is request batching, and enhanced/cache is cross-request prefix KV reuse.

### Model and local run

Run in a Python 3.12 environment. Validate model weights, tokenizer, and config with the [pinned revision](../../config/models/smollm2-135m-transformers.env) and [SHA-256 list](../../config/models/smollm2-135m-transformers.sha256).

Downloads need `curl` and `sha256sum` or `shasum`. Reserve disk for selected model files and memory for weights, KV cache, and runtime.

```sh
./scripts/download-transformers-model.sh
python3.12 -m venv /tmp/transformer-venv
. /tmp/transformer-venv/bin/activate
# On Linux, install CPU-only PyTorch first.
python -m pip install torch==2.10.0 --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r src/transformer/requirements.txt
PYTHONPATH=src python -m transformer.base.server --model .models/smollm2-135m
```

On macOS skip the CPU index install and install requirements only. This local run uses CPU and default dtype `float32`. `--device cuda` uses CUDA-enabled PyTorch and default dtype `float16`. CPU `--dtype bfloat16` performance varies by kernel. Dependency versions follow [requirements](../../src/transformer/requirements.txt).

Downloads preserve validated files and resume interrupted files. After all files validate, they move to the final directory `.models/smollm2-135m/`. `LOCAL_K8S_MODELS_DIR` can change the model root; use the same value for cluster creation.

The server reads local files only and does not use remote model code or auto-downloads.

The model is English-focused SmolLM2-135M-Instruct, loaded with the Llama model class and the model chat template applied. Set CPU threads with `--n-threads` for the environment.

### API and implementation selection

`GET /healthz` and `GET /readyz` return server status; `GET /v1/models` returns the served model. `POST /v1/chat/completions` takes conversation `messages` and generates a response. `stream: true` uses SSE and sends `[DONE]` on clean finish.

The model ID is `HuggingFaceTB/SmolLM2-135M-Instruct`. It supports `max_tokens` or `max_completion_tokens`, `temperature`, `top_p`, `ignore_eos`, and `stream_options.include_usage`.

```sh
curl http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"HuggingFaceTB/SmolLM2-135M-Instruct","messages":[{"role":"user","content":"Say hello in one short sentence."}],"max_tokens":32}'
```

| Implementation | Python module | Docker target, image name |
| --- | --- | --- |
| Base | `transformer.base.server` | `transformers-base` |
| Batch | `transformer.enhanced.batch.server` | `transformers-enhanced-batch` |
| GPU Batch | `transformer.enhanced.batch_gpu.server` | `transformers-enhanced-batch-gpu` |
| Cache | `transformer.enhanced.cache.server` | `transformers-enhanced-cache` |
| Base + Prometheus | `transformer.base_metric.server` | `transformers-base-metric` |
| Mamba | `transformer.mamba.server` | `transformers-mamba-base` |
| Mamba prefix cache | `transformer.mamba.cache.server` | `transformers-mamba-cache` |
| Jamba hybrid batch + HiCache | `transformer.hybrid.server` | `transformers-hybrid` |

Mamba uses a separate model and state checkpoints. For run method and cache rules, see [Mamba state cache](mamba-cache.md).

For the extra implementation combining Jamba Mamba state buffers, Attention KV, and tiered prefix cache, see [Hybrid batching and HiCache](hybrid-cache.md).

Switch implementations by changing the module in the local run command. See each module's `--help` for common CLI and defaults.

Input plus output cannot exceed `--n-ctx`; inputs are not auto-truncated. Token counts use actual input and generated IDs; the terminating EOS is excluded from output token count. SSE text preserves UTF-8 and word boundaries, so one chunk can contain multiple tokens.

Base and cache generate with Transformers `generate()`, leaving KV updates and stop conditions to the library. Sampling is active only when `temperature > 0`, with `top_k=0` disabling top-k limits. Model file sampling defaults are not applied on top of request `temperature` and `top_p`. `ignore_eos` suppresses EOS tokens instead of only disabling the stop condition.

Streaming decodes with `TextStreamer`; base and cache exclude input text with `skip_prompt=True`. Usage is computed from generated IDs excluding inputs and the final EOS. If EOS appears at the last generation step, `finish_reason` is `stop`.

Requests cancelled before generation do not call the model. Cancellation during generation is checked by `StoppingCriteria` after token generation, so it does not immediately stop the in-flight operation and its token output.

Base + Prometheus adds `transformers_*` request, token count, and TTFT metrics at `/metrics` to the same serial engine. For local runs also install `src/transformer/base_metric/requirements.txt`. [Multi-node availability](availability-test.md) and [HPA](hpa-test.md) use this image.

### Request batching

To reduce serial inference waits, run operations of multiple requests as one batch. The [batching worker](../../src/transformer/enhanced/batch/engine.py) collects requests for `--batch-wait-ms` and processes up to `--max-parallel` together.

Different-length inputs use tokenizer left padding and `prepare_inputs_for_generation()` position ID setup. Sampling uses Transformers `TemperatureLogitsWarper`, `TopPLogitsWarper`, and `SuppressTokensLogitsProcessor`. Each request keeps separate sampling options, output limits, and cancellation state; finished rows are removed from KV and batch before the next decode.

Per-request generation settings, stream distribution, and finished-row removal not provided by plain `generate()` are handled in the [batch backend](../../src/transformer/enhanced/batch/backend.py) loop.

New requests are not added to a batch in progress. New requests wait for the next batch, so long outputs can increase queueing delay. Cross-request prefix cache is not kept.

One worker runs model operations and HTTP threads wait for results. Worker errors propagate to waiting requests, and health and readiness fail.

GPU batch uses the same worker. Requests with `temperature=0` and `ignore_eos=true` reuse decode operations through per-batch-width CUDA Graphs. Other sampling options use the regular GPU batch path. Build the GPU image with `make build-image DEVICE=gpu VARIANT=transformers-enhanced-batch`.

### Prefix KV cache

All implementations use KV inside one request's decode; the cache implementation also reuses prefix KV across requests to reduce prefill.

The [cache engine](../../src/transformer/enhanced/cache/engine.py) keeps only input length with `DynamicCache.crop()` after `generate()` returns, and stores it as safetensors. Generated token KV is not stored; on generation exceptions or process exit, the new snapshot for that request is not stored either.

On cache lookup, restore the longest common token ID prefix as `past_key_values` and compute the remaining input. When the full input matches, recompute the last token to obtain logits.

| CLI option | Purpose |
| --- | --- |
| `--cache-dir` | Cache storage root |
| `--cache-ram-mib` | RAM budget for serialized KV and token IDs, 0 disables |
| `--cache-disk-mib` | Per-namespace disk budget, 0 disables |
| `--cache-min-prefix` | Minimum prefix token count allowed for store and restore |

Entries evicted from RAM LRU move to disk; disk hits move up to RAM when size allows. On clean shutdown, RAM entries are saved. Bad checksums or tensors are dropped and recomputed.

Namespaces are separated by model file hash and layout, head size, library version, dtype, context, and CPU settings, with a single-writer lock. Stored response text is not reused.

The RAM budget excludes running model KV, deserialization buffers, and Python indexes. Disk writes are synchronous. Old namespaces are not auto-deleted; entries that were only in RAM can be lost on forced shutdown.

### Docker and Kubernetes

The [Dockerfile](../../src/Dockerfile) uses `src/` as context; Transformers targets install the CPU PyTorch wheel. Weights are not included in images.

```sh
make download-model
./scripts/local-k8s.sh up
make build-image load-image
./scripts/k8s.sh apply k8s/inference/profiles/transformers-base-cpu.yaml
./scripts/local-k8s.sh kubectl rollout status deployment/transformers-base --timeout=300s
./scripts/local-k8s.sh kubectl port-forward service/transformers-base 8000:8000
```

Each directory has Deployment and Service manifests; cache also includes a PVC. Switch to batching and cache with the following commands.

```sh
make build-image load-image VARIANT=transformers-enhanced-batch
./scripts/k8s.sh apply k8s/inference/profiles/transformers-enhanced-batch-cpu.yaml

make build-image load-image VARIANT=transformers-enhanced-cache
./scripts/k8s.sh apply k8s/inference/profiles/transformers-enhanced-cache-cpu.yaml
```

Select only one of the three configurations. They replace the same `Deployment/transformers-base` and `Service/transformers-base`; the cache PVC is kept when switching implementations. Do not run other inference jobs on the same node during performance measurement.

Before deploying, you can validate with the API server using `./scripts/render-k8s.sh k8s/inference/profiles/transformers-base-cpu.yaml > /tmp/inference.yaml && ./scripts/local-k8s.sh kubectl apply --dry-run=server -f /tmp/inference.yaml`. The commands above use default image tags. If built with another `IMAGE_TAG`, set `container.image` in the selected profile to the same tag.

CPU, memory, and `--n-threads` are set in each Deployment.

The model is mounted read-only from kind node `/models/smollm2-135m` to `/model`. The cache implementation connects a [dedicated PVC](../../k8s/inference/profiles/transformers-enhanced-cache-cpu.yaml) at `/cache` and needs the cluster default StorageClass.

Measurement Pods set CPU and memory requests equal to limits. Actual resource values are in the [base Deployment](../../k8s/inference/values.yaml).

### Validation

Tests run in the Python environment above plus `httpx` and metric dependencies. They create small Llama-structure weights in a temp directory to verify CPU compute, batch padding and finished-row removal, cancellation, cache restore, and corruption recovery.

```sh
python -m pip install -r src/transformer/base_metric/requirements.txt httpx
python -m unittest discover -s tests -p 'test_transformers_*.py' -v
sh tests/test-download-transformers-model.sh
# Uses API discovery of the running local cluster.
sh tests/test-transformers-manifests.sh
TEST_TRANSFORMERS_MODEL_PATH="$PWD/.models/smollm2-135m" \
  python -m unittest discover -s tests -p 'test_transformers_engine.py' -v
# Real HTTP and SSE requests to the running API
SERVED_MODEL_NAME=HuggingFaceTB/SmolLM2-135M-Instruct python tests/test-api-llamacpp.py
```

Real-model tests verify `generate` results, SSE content, and disk cache restore.

## llama.cpp

llama.cpp runs GGUF models on CPU. Base is serial inference, enhanced/batch is continuous batching, and enhanced/cache is a RAM and disk prefix KV cache. Batching and caching run independently. Dependencies and CPU build options are managed in the [Dockerfile](../../src/Dockerfile).

### Switching engines

Transformers and llama.cpp use different Deployments. When switching engines on the same cluster, stop the existing engine Pods first. Idle Pods still reserve resources, so deploying together can leave new Pods Pending on CPU or memory shortage.

To switch from Transformers to llama.cpp, finish running benchmarks then execute:

```sh
./scripts/local-k8s.sh kubectl scale deployment/transformers-base --replicas=0
./scripts/local-k8s.sh kubectl wait --for=delete pod -l app=transformers-base --timeout=120s
```

For the opposite direction, replace `transformers-base` with `base-llamacpp` in the commands above. If selecting an engine for the first time, the stop step is not needed. Applying the target engine manifest or running its benchmark restarts that Deployment. PVCs and models are kept.

### llama.cpp deployment

From the repository root, specify `VARIANT=base-llamacpp` to prepare the model and images.

```sh
make download-model VARIANT=base-llamacpp
make up
make build-image load-image VARIANT=base-llamacpp
./scripts/k8s.sh apply k8s/inference/profiles/base-llamacpp-cpu.yaml
```

After deployment, wait for server readiness and connect the port.

```sh
./scripts/local-k8s.sh kubectl rollout status deployment/base-llamacpp --timeout=300s
./scripts/local-k8s.sh kubectl port-forward service/base-llamacpp 8000:8000
```

Call from another terminal. The model name matches `SERVED_MODEL_NAME` in [model settings](../../config/models/qwen2.5-0.5b-gguf-llamacpp.env).

```sh
curl http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"Qwen/Qwen2.5-0.5B-Instruct","messages":[{"role":"user","content":"Hello"}],"max_completion_tokens":32}'
```

`GET /healthz` and `GET /readyz` return status after model load; `GET /v1/models` returns the model name. Chat supports `system`, `user`, and `assistant` roles with string or text-part arrays. Specify output length with either `max_tokens` or `max_completion_tokens`.

`stream: true` uses SSE responses. With `stream_options: {"include_usage": true}`, the last data chunk includes token usage. Clean finish is `[DONE]`; generation failure is distinguished with an `error` object.

### Run and length limits

Server options are at `PYTHONPATH=src python -m llamacpp.base.server --help`; deployed values are in the [Deployment](../../k8s/inference/profiles/base-llamacpp-cpu.yaml).

Prompts apply the GGUF chat template, then tokenize. If input limits, output limits, or input plus requested output exceed context size, return HTTP 400 without auto-shortening lengths.

Token usage is computed from actual input and generated token IDs. `ignore_eos: true` suppresses stop tokens for fixed-length measurement. Model access is serialized on a single thread; on connection close, in-flight generation stops at the next interrupt check. Interruption during prompt processing can take time.

### llama.cpp base validation

For response quality on representative questions, see the [quick quality check](quality-check.md).

API regression tests can run without a model. Run in a separate Python environment.

```sh
python -m pip install fastapi==0.141.1 httpx==0.28.1
python -m unittest discover -s tests -p 'test_server_llamacpp.py' -v
```

Token accounting and interrupt behavior on a real model are validated after installing inference dependencies. Native library builds need a C/C++ compiler and CMake.

```sh
python -m pip install -r src/llamacpp/base/requirements.txt
TEST_MODEL_PATH="$PWD/.models/qwen2.5-0.5b/qwen2.5-0.5b-instruct-q4_k_m.gguf" \
  python -m unittest discover -s tests -p 'test_engine_llamacpp.py' -v
```

Validate HTTP and SSE responses of a running server with:

```sh
python tests/test-api-llamacpp.py
```

Use `API_SERVER_URL` for another address and `SERVED_MODEL_NAME` for another model name.

### Selecting llama.cpp implementations

| Implementation | Python module | Image target |
| --- | --- | --- |
| Base | `llamacpp.base.server` | `base-llamacpp` |
| Batch | `llamacpp.enhanced.batch.server` | `enhanced-batch-llamacpp` |
| Cache | `llamacpp.enhanced.cache.server` | `enhanced-cache-llamacpp` |
| Base + Prometheus | `llamacpp.base_metric.server` | `base-metric-llamacpp` |

After preparing model and cluster in the base deployment, build and apply the selected image.

```sh
make build-image load-image VARIANT=enhanced-batch-llamacpp
./scripts/k8s.sh apply k8s/inference/profiles/enhanced-batch-llamacpp-cpu.yaml
./scripts/local-k8s.sh kubectl rollout status deployment/base-llamacpp --timeout=300s
```

For cache, replace `enhanced-batch-llamacpp` with `enhanced-cache-llamacpp` in the commands above. The three configurations replace the same `Deployment/base-llamacpp` and `Service/base-llamacpp:8000`, so apply only one. Keep the Deployment selector and distinguish implementations with the Pod `inference-variant` label and image. Measurement resources use `requests=limits` like base.

Base + Prometheus is used in [availability tests](availability-test.md#llamacpp) and [HPA tests](hpa-test.md#llamacpp).

For load settings, see [AIPerf](aiperf.md); for performance comparison, see [benchmarks](benchmark.md); for response quality, see [quality check](quality-check.md).

### Continuous batching

The [batching worker](../../src/llamacpp/enhanced/batch/batching.py) owns one native context. Each request keeps separate sequence IDs, samplers, generated tokens, and UTF-8 stream decoders.

Tokens of decoding requests go into the batch first; remaining space takes new prompt pieces. Remove KV of finished or cancelled requests and assign slots to waiting requests.

HTTP worker threads wait for scheduler results. Only the batching worker accesses model and tokenizer. On native decode failure, waiting calls end with errors and health/readiness return failure.

| CLI option | Purpose |
| --- | --- |
| `--max-parallel` | Active request slots. Must not exceed `--n-batch` |
| `--prefill-chunk` | Input token cap per request in one scheduling step |
| `--n-batch` | Token cap submitted to native decode across all requests |
| `--n-ubatch` | Physical batch cap of native compute |
| `--n-threads-batch` | Prefill and multi-token decode thread count. Uses `--n-threads` when omitted |
| `--n-ctx` | Limit on input plus output sum for one request |

Native KV space is allocated for `n_ctx x max_parallel`; actual size can grow from library alignment. The batching version does not keep cross-request prefix cache.

See `PYTHONPATH=src python -m llamacpp.enhanced.batch.server --help` for defaults, and the [Deployment](../../k8s/inference/profiles/enhanced-batch-llamacpp-cpu.yaml) for deployed values.

### RAM and disk tiered cache

The [cache engine](../../src/llamacpp/enhanced/cache/engine.py) adds prefix lookup and restore to the base serial generation path. After input prefill, at the point the first token is sampled, it stores only the input native sequence KV. Python scores arrays and generated responses are not stored.

Lookup finds the longest common token ID prefix. It restores when a longer prefix than the current native context can be reused. After state restore it computes the new suffix; when the full input matches, it recomputes the last input token to refresh logits.

1. A RAM hit refreshes that entry's LRU order.
2. Past the RAM limit, older entries spill to disk.
3. A disk hit moves to RAM after checksum validation. Entries larger than RAM stay on disk.
4. Past the disk limit, disk LRU entries are removed. On clean shutdown, remaining RAM entries are also saved.

Disk writes are synchronous with temp files, fsync, and atomic rename. Entries that were only in RAM before a forced process exit can be lost. Corrupt entries are dropped and recomputed.

Namespaces are separated by model file, native library, package versions, context size, and architecture, with a per-namespace single-writer lock.

| CLI option | Purpose |
| --- | --- |
| `--cache-dir` | Cache storage root |
| `--cache-ram-mib` | RAM budget for native state and token IDs. 0 disables the RAM tier |
| `--cache-disk-mib` | Per-namespace disk file budget. 0 disables the disk tier |
| `--cache-min-prefix` | Minimum common prefix token count allowed for store and restore |

The RAM budget excludes Python indexes, containers, and temp buffers during restore. The disk budget is per namespace; old model namespaces are not auto-deleted. Indexes use in-memory linear search.

See `PYTHONPATH=src python -m llamacpp.enhanced.cache.server --help` for defaults.

The [cache Deployment](../../k8s/inference/profiles/enhanced-cache-llamacpp-cpu.yaml) mounts a [PVC](../../k8s/inference/profiles/enhanced-cache-llamacpp-cpu.yaml) at `/cache`. The PVC is kept when switching implementations or restarting inference Pods. The cluster default StorageClass is required.

### llama.cpp enhanced validation

Model-free validation uses the same `fastapi`, `httpx` environment as the base API test.

```sh
python -m unittest discover -s tests -p 'test_enhanced_*.py' -v
```

Native integration validation needs the same `llama-cpp-python` version as each image and a real GGUF.

```sh
TEST_MODEL_PATH="$PWD/.models/qwen2.5-0.5b/qwen2.5-0.5b-instruct-q4_k_m.gguf" \
  python -m unittest discover -s tests -p 'test_enhanced_native_llamacpp.py' -v
```

It validates batch multi-request decode, cancellation, slot reuse, cache spill, promotion, corruption recovery, restart, and HTTP/SSE compatibility.
