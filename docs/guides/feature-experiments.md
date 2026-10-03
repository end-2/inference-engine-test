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

Python entrypoints follow this structure. The HTTP benchmark suite maps Docker target names, image names and variant IDs in [inference.json](../../benchmarks/inference.json); these are independent of Python package names.

An engine implements `prepare_prompt`, `complete`, `stream` and `close`. `stream` emits text through its callback and returns token counts and the finish reason. `complete` also returns text. Server settings retain control of the executor so serial and batched variants keep their respective concurrency behavior. Metrics are enabled only by metric entrypoints.

## Experiment configuration

`benchmarks/` contains comparison conditions, workload definitions and the AIPerf image build context at `benchmarks/aiperf/`. `config/` contains cluster, tool version and model preparation settings; `k8s/` contains deployment charts.

[inference.json](../../benchmarks/inference.json) maps each implementation to its image/build target, CPU and GPU Helm profiles, model, AIPerf profile and default suite conditions. GPU image/build targets append `-gpu` to the configured image name. Existing Make variables and runner CLI options can override individual selections.

To add an implementation, implement the engine protocol, add its Docker target and Helm profile, and register the mapping and comparison conditions. Keep baseline settings, model revision, workload, resource limits and measurement scope fixed for the comparison.

Suite JSON files contain `backend`, `device` and a nonempty `conditions` list. Each condition has a unique `name`, a registered `variant`, a `cache_policy`, and optionally `cuda_graph` for Transformers GPU batching. The config selects the backend and device. Repetition count remains a CLI option.

```sh
make benchmark-suite BENCHMARK_CONFIG=benchmarks/cuda-graph.json REPETITIONS=3
# Equivalent runner invocation
python3 scripts/run-benchmark-suite.py --config benchmarks/cuda-graph.json --repetitions 3
```

The [CUDA Graph experiment](../../benchmarks/cuda-graph.json) compares serial base, GPU batch with Graph disabled, and GPU batch with Graph required. The two batch conditions use the same image and Helm profile; only `--cuda-graph` changes. Suite order rotates across repetitions and each concurrency starts a new inference Pod. `run.json` records the resolved catalog and conditions; `--resume` uses those recorded selections.

## CUDA Graph selection and evidence

The GPU batch server accepts `--cuda-graph auto|off|required`:

| Mode | Behavior |
| --- | --- |
| `auto` | Default. Use Graph for eligible requests and eager execution otherwise. |
| `off` | Always use the eager GPU batch implementation. |
| `required` | Require greedy decoding, `ignore_eos=true`, CUDA and the Graph context limits; incompatible work fails. |

```sh
make benchmark DEVICE=gpu VARIANT=transformers-enhanced-batch CUDA_GRAPH=off
```

`GET /runtime` exposes completed batch and request counts by actual `eager` or `cuda_graph` execution path. The benchmark collects this endpoint after the load finishes when a Graph mode is explicitly selected, records it in `c*/runtime.json` and `run.json`, and fails if the mode or path contradicts the experiment. Counts cover the Pod lifetime, including warmup; they are not profiling-only throughput metrics. Failed batch calls are not counted. Engines without runtime diagnostics return an empty object.

HTTP suites record `measurement_scope=http_chat_completions`. The [Hybrid engine benchmark](hybrid-cache.md) records `engine_generation_first_token`, excludes HTTP and tokenization, and measures the first generated token. Keep these scopes separate when comparing results.

## Validation

Use an environment with the existing server and model test dependencies:

```sh
PYTHONPATH=src:tests python -m unittest discover -s tests -p 'test_*.py'
```

The suite covers API behavior, cancellation, cache restoration, output equivalence on small models, Graph selection and experiment routing. CUDA execution tests require a CUDA PyTorch environment. Performance claims require running the selected benchmark on the target hardware.
