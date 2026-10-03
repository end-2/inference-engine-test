> Korean version: [한국어](benchmark-KR.md)

# Running benchmarks and analyzing results

Compare throughput and latency of base, batch, and prefix KV cache implementations with AIPerf. The default device is CPU; NVIDIA GPU is also supported.

For inference implementation and API, see the [inference engine guide](inference-engine.md).

For source boundaries, adding comparison conditions and isolating CUDA Graph performance, see [feature experiments](feature-experiments.md).

## Configuration

| Item | Setting |
| --- | --- |
| Cluster | Default single-node kind, with inference server and AIPerf Jobs placed |
| Model | SmolLM2 Transformers CPU; server and AIPerf use the same revision tokenizer |
| Inference implementation | One of base, batch, cache |
| Single measurement | Restart inference Pod per concurrency, then run warmup and main requests |
| Repeated measurement | Run each implementation repeatedly, rotating execution order each round |
| Observation | Per-request AIPerf results and Kubernetes node, Pod, and container resource samples |

Load conditions and per-option values follow the [AIPerf default benchmark settings](aiperf.md#default-benchmark-settings). Inference resources and threads are managed in each implementation's Deployment; measurement Pods keep CPU and memory `requests=limits`.

## Preparation

Docker, a POSIX shell, Python 3.10 or later, and make are required. Check model and image download connectivity and [CPU, memory, and disk requirements](requirements.md#cpu-memory-and-disk), then install tools from the repository root.

```sh
./scripts/local-k8s.sh install
```

The automated script downloads models and tokenizers, prepares the cluster, builds and loads images, deploys, and measures. For manual tokenizer preparation, see the [AIPerf guide](aiperf.md#preparing-the-tokenizer).

Stop other load experiments during measurement. If another engine is already deployed on the same cluster, stop its Pods per [switching engines](inference-engine.md#switching-engines).

The default run uses a single-node cluster. On multi-node, specify both `--inference-node` and `--benchmark-node`, and select nodes to match the cache PV node affinity. `up` does not change an existing cluster topology.

## Deploy and run

### Automated measurement with Pod restarts

```sh
make benchmark
# Select when measuring the batching or cache implementation
make benchmark VARIANT=transformers-enhanced-batch
make benchmark VARIANT=transformers-enhanced-cache
```

Each command downloads and validates the model, prepares the cluster, builds and loads images, deploys, and measures. On failure it does not proceed to the next step, and leaves completed results and diagnostics logs. The server and cluster are kept after completion.

The runner selects the image, build target and Helm profiles from [inference.json](../../benchmarks/inference.json). `make` uses image names in `VARIANT`; the runner uses backend-specific variant IDs:

```sh
./scripts/run-benchmark.py --backend transformers --variant enhanced-batch
./scripts/run-benchmark.py --backend transformers --variant enhanced-cache --cache-policy clear-before-sweep
python3 scripts/run-benchmark-suite.py --backend transformers
```

`--image`, `--build-target`, `--manifests` and `--benchmark-manifests` override individual selections. See `--help` for node and timeout options. AIPerf image builds use `benchmarks/aiperf/`.

### Per-concurrency PVC cache reset

| `CACHE_POLICY` | Reset point |
| --- | --- |
| `preserve` | Keep disk cache |
| `clear-before-sweep` | Before warmup of the first concurrency |
| `clear-per-concurrency` | Before warmup of each concurrency |

`make benchmark` defaults to `clear-before-sweep` for Transformers and Mamba cache variants, and `preserve` for other variants. Direct runner invocations default to `preserve`; pass `--cache-policy` explicitly when comparing cache conditions.

```sh
make benchmark VARIANT=transformers-enhanced-cache CACHE_POLICY=clear-per-concurrency
```

Cache reset waits for inference Pod termination and flush, then deletes cache files on the dedicated PVC. Model and result PVCs are kept; the used policy is recorded in `run.json`.

Warmup and main requests reuse the cache, so this is not a condition that measures cache misses for every request.

### Repeated measurement of all implementations

Measure base, batch, and cache 3 times each, rotating execution order each round. Cache is reset before the sweep and preserved between concurrencies.

```sh
make benchmark-suite
# Change repetition count
make benchmark-suite REPETITIONS=1
# Resume while keeping completed sweeps
python3 scripts/run-benchmark-suite.py --resume 'docs/reports/transformers/benchmark-suite-<UTC time>'
```

### Selecting llama.cpp

Select the [dedicated profile](../../k8s/aiperf/profiles/qwen2.5.yaml) that uses Qwen2.5 GGUF and a local tokenizer.

```sh
make benchmark VARIANT=base-llamacpp
make benchmark VARIANT=enhanced-batch-llamacpp
make benchmark VARIANT=enhanced-cache-llamacpp
python3 scripts/run-benchmark-suite.py --backend llamacpp
```

The llama.cpp suite repeats four conditions: base, batch, cache reset, and cache preserved. Cache policies are `clear-per-concurrency` and `clear-before-sweep` respectively.

### Selecting Mamba

```sh
make benchmark VARIANT=transformers-mamba-cache
python3 scripts/run-benchmark-suite.py --backend mamba
```

The Mamba suite compares base, cache cleared per concurrency and cache cleared before each sweep. For model preparation and cache behavior, see [Mamba state cache](mamba-cache.md). Jamba uses the separate [hybrid engine benchmark](hybrid-cache.md#base-and-performance-comparison).

## Results and observation

Single measurement results are stored in `docs/reports/<backend>/bench-<UTC time>-<image>/`. `<backend>` is `transformers`, `llamacpp` or `mamba`.

Repeated measurement aggregates are stored in `docs/reports/<backend>/benchmark-suite-<UTC time>/`. The p95 aggregate is the mean of per-run p95 values.

`profiling_seconds` is the main request time; `job_and_collection_seconds` is the time from Job creation to collection completion. The full sweep includes Pod readiness and cache reset time.

| File | Contents |
| --- | --- |
| `summary.md`, `summary.csv`, `summary.jsonl` | Per-concurrency metrics or repeat aggregates |
| `run.json`, `inference.json`, `nodes.json` | Run status, image IDs, and environment |
| `c*/artifacts/profile_export.jsonl`, `c*/requests.csv` | Per-request originals and metrics |
| `c*/resources.jsonl`, `c*/resources.csv` | Node, Pod, and container resource samples |
| Suite `runs.csv` | Individual run metrics |

For inference resource analysis use `role=inference`, `scope=pod`, and do not double-count Pod and container values. For request analysis select `benchmark_phase=profiling`. Resource samples are interval observations and do not represent the CPU cost of an individual request.

Git retention of originals and detailed logs follows the [exclusion rules](../reports/.gitignore). `--reports-dir` uses the given path as is.

## GPU benchmarks

The GPU cluster is `local-k8s-gpu`, separate from the CPU cluster. It needs the NVIDIA driver, Docker NVIDIA runtime, NVIDIA Container Toolkit, and Go. Enable the Toolkit `accept-nvidia-visible-devices-as-volume-mounts` value. `make install DEVICE=gpu` installs pinned nvkind, kind, kubectl and Helm versions. Startup checks Docker GPU access, GPU allocation, and Pod `nvidia-smi` access.

```sh
sudo nvidia-ctk config --set accept-nvidia-visible-devices-as-volume-mounts=true --in-place
```

```sh
make install DEVICE=gpu
make up DEVICE=gpu
make benchmark-suite DEVICE=gpu
make benchmark-suite DEVICE=gpu INFERENCE_BACKEND=llamacpp
```

Select a single implementation like `make benchmark DEVICE=gpu VARIANT=transformers-enhanced-cache`. To stop, use `make down DEVICE=gpu`. The GPU cluster mounts the model directory read-only at `/models` on nodes. One GPU is assigned to one inference Pod, and AIPerf runs on the control-plane node.

For a separate environment that assigns a shared GPU resource to two Pods, see the [MPS cluster guide](gpu-mps.md). Benchmarks in this document use `GPU_SHARING=none`.

Measure Transformers GPU batching with `make benchmark DEVICE=gpu VARIANT=transformers-enhanced-batch`. For the GPU-only batch implementation and CUDA Graph conditions, see the [inference engine guide](inference-engine.md#request-batching).

GPU measurement uses concurrency `1,2,4,8` with the same model and AIPerf profile. Transformers runs with `float16`; llama.cpp runs with `n_gpu_layers=-1`.

GPU results are stored in `docs/reports/gpu/<backend>/`. `run.json` records device, dtype, or GPU layer settings. Each concurrency's `gpu.csv` has GPU UUID, utilization, and used-memory series; the summary has means and maxima. CPU results stay in the existing `docs/reports/<backend>/`. The host environments differ, so do not directly compare these GPU numbers with existing CPU results.

Measured results from the first round and caveats are in [GPU results](../reports/gpu/README.md).

## Validation and troubleshooting

```sh
python3 -m unittest discover -s tests -p 'test_benchmark*.py'
```

- `Pending`: check CPU and memory reservations of inference Pods and Jobs.
- `hostPath type check failed`: check model and tokenizer downloads and the node `/models` mount.
- HTTP 404: check the Job model name and the server model name.
- HTTP 400: check input length including chat template, output length, and context limits.
- Resource collection failure: check node `proxy/stats/summary` read permission and Pod CPU samples.
