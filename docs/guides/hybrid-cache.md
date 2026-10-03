> Korean version: [한국어](hybrid-cache-KR.md)

# Jamba hybrid batching and HiCache

`huggingface.jamba.hybrid.server` manages Jamba Attention KV together with Mamba convolution and SSM states. It is a separate module from the existing Transformers and Mamba engines and provides the same HTTP and SSE API. It needs a local checkpoint with `model_type=jamba` that includes both Attention and Mamba layers. Existing SmolLM2 or Mamba-130m weights cannot be used.

## Run

Dependencies use the [Transformers requirements](../../src/huggingface/requirements.txt). The model directory must contain config, safetensors weights, and tokenizer.

```sh
PYTHONPATH=src python -m huggingface.jamba.hybrid.server \
  --model /path/to/jamba --served-model-name jamba-hybrid \
  --device cuda --dtype float16 \
  --max-parallel 4 --batch-wait-ms 5 \
  --cache-dir /tmp/jamba-hicache \
  --cache-gpu-mib 64 --cache-ram-mib 256 --cache-disk-mib 1024
```

On CPU use `--device cpu --dtype float32`. CPU runs disable the GPU cache tier. The API request `model` must match `--served-model-name`.

```sh
curl http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"jamba-hybrid","messages":[{"role":"user","content":"Explain prefix caching."}],"temperature":0,"max_tokens":32}'
```

Docker targets are `transformers-hybrid` for CPU and `transformers-hybrid-gpu` for GPU.

```sh
docker build -f src/Dockerfile.gpu --target transformers-hybrid-gpu \
  -t local/transformers-hybrid-gpu:0.1.0 src
docker run --rm --gpus all -p 8000:8000 \
  -v /path/to/jamba:/model:ro \
  local/transformers-hybrid-gpu:0.1.0 \
  --model /model --device cuda --dtype float16
```

To keep disk cache across container restarts, mount a directory writable by UID 1000 and point to it with `--cache-dir`. Kubernetes AIPerf manifests do not provide Jamba.

## State buffers and batching

[HybridBuffer](../../src/huggingface/jamba/hybrid/state.py) pre-allocates Attention KV and Mamba state space for `max_parallel` and `n_ctx`. KV is appended to the existing buffer, so decode does not rebuild the full KV with `torch.cat()` each time. Mamba state replaced by the Jamba PyTorch path is copied into the same buffer, keeping SSM float32 accumulation precision. Temporary tensor allocation inside kernels remains.

The [batch backend](../../src/huggingface/jamba/hybrid/backend.py) processes as follows.

- Prefill together requests with the same prefix length and restore length. A cache miss computes the full prefix at once.
- When a checkpoint matches the full prefix, skip intermediate prefill buffer copies and restore directly into the decode buffer.
- When appending a suffix to restored Mamba state, compute one token at a time. This is the current Jamba implementation's state update condition.
- For requests with different lengths, apply left padding to Attention KV only, insert each request's exact Mamba state, and decode together.
- Rows finished by EOS, output limit, or cancellation are removed from KV and Mamba state together.
- The same sampling settings are processed per batch, and generated tokens move to CPU once per step.
- Combinations exceeding `n_ctx` because of padding are split into smaller batches. New requests are not added to a batch in progress.

`--mamba-kernels auto` uses accelerated kernels when both CUDA device and Jamba support them. `off` uses the PyTorch path; `required` refuses to start without accelerated kernels. The provided Docker images do not install `mamba-ssm` or `causal-conv1d`, so they run on the PyTorch path.

CUDA Graph is not applied to this module. Current Jamba mask generation and Mamba fallback use dynamic shapes and tensor replacement, so the existing Llama-only graph cannot be reused.

## Prefix checkpoints and tier movement

A checkpoint stores KV, convolution state, and SSM state together **just before the last token of the input**. The last input token is recomputed to obtain logits. Generated token state is not stored in prefix cache.

Mamba state cannot be truncated to an earlier position. So restore only the longest checkpoint whose full stored tokens match the request prefix. For example, a `[1, 2, 3]` checkpoint can serve a `[1, 2, 3, 4]` input but not a `[1, 2, 9, 4]` input. Intermediate boundary checkpoints are not auto-generated.

The [HiCache](../../src/huggingface/jamba/hybrid/hicache.py) tiers are as follows.

| Tier | Stored form | When over limit |
| --- | --- | --- |
| GPU | Independently copied KV and Mamba tensors | Move LRU entries to CPU RAM |
| CPU RAM | Pinned tensors on GPU runs, regular tensors on CPU runs | Serialize LRU entries to disk as safetensors |
| Disk | `.kv` files with token IDs and checksum | Delete LRU files |

Entries stay in one tier, and on hit move to an upper tier when budget allows. GPU and RAM budgets sum tensor payload plus 8 bytes per token. Disk counts file size. An entry larger than a tier's full budget moves to a lower tier; entries that fit no tier are not kept. On CUDA OOM during GPU cache copy, pass that entry to RAM or disk.

`--cache-gpu-mib`, `--cache-ram-mib`, and `--cache-disk-mib` are per-tier budgets; 0 disables. `--cache-min-prefix` is the minimum token count stored and restored. See [EngineSettings](../../src/huggingface/jamba/hybrid/engine.py) for defaults, and `PYTHONPATH=src python -m huggingface.jamba.hybrid.server --help` for all CLI options.

Active batch buffers, model weights, prefill result copies, deserialization buffers, and Python objects are not included in cache budgets. There is no automatic retry on OOM during active inference. Prefix cache copies are separate from active buffers, so batch updates and eviction do not change stored state.

Namespaces are separated by model file hash, library version, dtype, device, and kernel path. Disk allows a single writer and saves upper tiers on clean shutdown. Entries with bad checksums or tensor layout are deleted and recomputed. Old namespaces are not auto-deleted.

This implementation follows the GPU, host, and storage tier structure of [SGLang HiCache design](https://docs.sglang.ai/advanced_features/hicache_design.html) as a project-internal implementation. Storage is local files, and I/O is synchronous. It does not include the SGLang runtime, radix page sharing, async prefetch, or distributed storage backends.

## Validation

```sh
PYTHONPATH=src:tests python -m unittest \
  test_transformers_hybrid test_transformers_server \
  test_transformers_batch test_enhanced_cache_llamacpp -v
```

Tests build a small random Jamba model and check that cold and warm cache plus batch outputs match the no-cache baseline. They cover prefix boundaries, buffer reuse, row removal, cancellation, SSE, tier promotion and eviction, restart, and corruption recovery. On a CUDA PyTorch environment they also run float16 and float32 GPU checks. This validation does not replace quality or throughput benchmarks on a real Jamba checkpoint.

## Base and performance comparison

The [serial base](../../src/huggingface/jamba/base/engine.py) runs the same Jamba model with Transformers `generate()`. It uses dynamic KV and Mamba state inside a request, without cross-request prefix cache or batching. To run over HTTP, set the module to `huggingface.jamba.base.server`.

Benchmarks use AI21's trained development model [Jamba-tiny-dev](https://huggingface.co/ai21labs/Jamba-tiny-dev). Model revision and file checksums are pinned in [model settings](../../config/models/jamba-tiny-dev-transformers.env).

```sh
./scripts/download-transformers-model.sh jamba-tiny-dev
python scripts/benchmark-hybrid.py \
  --model .models/jamba-tiny-dev --device cuda --dtype float16 \
  --prompt-lengths 64,256 --max-tokens 32 --concurrencies 1,2,4,8 \
  --repetitions 3 --waves 2 \
  --report-dir docs/reports/gpu/hybrid/benchmark-suite-local
```

The result directory must be empty. Conditions are base, batch-only, cold cache, GPU hit, RAM hit, and disk hit. Warm conditions place a checkpoint for the tier in each request bundle, and check restored token counts and the actual hit tier. All measured outputs are compared against the same model's base output token IDs; mismatches fail.

This is an engine benchmark that excludes HTTP and input tokenization. It includes request queuing and batch wait time; TTFT is based on the first generated token. Model loading, warmup, and warm cache preparation are excluded. Execution order rotates each repetition; disk conditions do not drop OS page cache. Scope differs from AIPerf reports.

`run.json` records model and source SHA-256, inputs and baseline outputs, run settings, and validation counts. `summary.md`, `summary.csv`, and `summary.jsonl` give throughput and latency versus base; `runs.csv` and local `requests.jsonl` give individual measurements.

Full conditions and validation results on RTX 2060 SUPER are in the [base and hybrid comparison](../reports/gpu/hybrid/README.md).
