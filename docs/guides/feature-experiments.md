> Korean version: [한국어](feature-experiments-KR.md)

# Feature performance experiments

Feature implementations share the HTTP request path and retain their own scheduling and model state handling.

## Source boundaries

| Module | Responsibility |
| --- | --- |
| `src/inference/api.py` | Request validation, SSE, cancellation and response token accounting |
| `src/inference/contracts.py` | Engine protocol, generation requests and result types |
| `src/inference/cache.py` | RAM and disk snapshot storage, lookup and eviction |
| `src/inference/metrics.py` | Optional request and generation metrics |
| `src/huggingface/runtime/` | Serial generation, batch queue, sampling and serving settings shared by model families |
| `src/huggingface/{llama,mamba,jamba}/` | Model loading and defaults, baseline and feature implementations |
| `src/llamacpp/{base,batch,cache,metrics}/` | GGUF inference and optional metrics |

```text
src/
├── inference/
├── huggingface/
│   ├── runtime/
│   ├── llama/      # base, batch/gpu, cache, metrics, inference_distributed
│   ├── mamba/      # base, cache
│   └── jamba/      # base, hybrid
└── llamacpp/       # base, batch, cache, metrics
```

Each Hugging Face family defines model loading in `model.py` and HTTP defaults in `serving.py`. Its `base/` exposes the serial comparison entrypoint. Feature implementations use their family model and `runtime/`; shared code does not import comparison entrypoints or other model families. The `huggingface` package name keeps imports distinct from the installed `transformers` library.

An engine implements `prepare_prompt`, `complete`, `stream` and `close`. `stream` emits text through its callback and returns token counts and the finish reason. `complete` also returns text. Server settings retain control of the executor so serial and batched variants keep their respective concurrency behavior. Metrics are enabled only by metric entrypoints.
