> Korean version: [한국어](README-KR.md)
# Inference engine test

Measures inference, batching, and prefix cache for Transformers and llama.cpp on kind. CPU is the default and NVIDIA GPU is optional.

For Benchmark, Availability, and HPA test results see [reports-transformers.md](docs/reports-transformers.md).

## Prerequisites

- Host with Docker running, POSIX shell, Python 3.10 or later and `make`
- For tool installation, `curl` or `wget`, `sha256sum` or `shasum` for checksum verification, and internet access
- For model download, `curl` and internet access
- Before running inference, secure Docker resources matching [CPU, memory, and disk requirements](docs/guides/requirements.md#cpu-memory-and-disk)

## Quick start

Run from the repository root. It automatically performs model download and verification, cluster creation, image build and load, deployment, and repeated measurements.

### Using make

```sh
make install
make benchmark-suite
```

The default experiment repeats concurrency `1,2,4,8` three times for each of three implementations. Results are saved to `docs/reports/transformers/benchmark-suite-*/summary.md`. For metrics, cache policy, and runtime see the [benchmark guide](docs/guides/benchmark.md). `make benchmark` and `make benchmark-suite` automatically include image build through kind load, deployment, and AIPerf execution when needed.

For GPU runs see [GPU benchmark preparation and results](docs/guides/benchmark.md#gpu-benchmarks).
For sharing one GPU between two Pods see the [MPS cluster guide](docs/guides/gpu-mps.md).
For combined versus disaggregated Prefill and Decode performance comparison see the [PD comparison guide](docs/guides/prefill-decode.md).

To measure a single sweep only, select the implementation with `VARIANT`.

```sh
make benchmark # transformers-base (default)
make benchmark VARIANT=transformers-enhanced-batch
make benchmark VARIANT=transformers-enhanced-cache
```

Select llama.cpp with `make benchmark VARIANT=base-llamacpp` after [switching engines](docs/guides/inference-engine.md#switching-engines), and run `enhanced-batch-llamacpp` and `enhanced-cache-llamacpp` the same way. Reports are stored per backend in `docs/reports/llamacpp/` and `docs/reports/transformers/`.

### Running scripts directly

`make` commands wrap executables in `scripts/`. You can run them directly with the same effect. `VARIANT` is a `make`-only convenience variable, while scripts take image, build target, and manifests directly.

```sh
./scripts/local-k8s.sh install # same as make install
./scripts/local-k8s.sh up      # same as make up
python3 scripts/run-benchmark-suite.py # same as make benchmark-suite, default backend is transformers
python3 scripts/run-benchmark-suite.py --backend llamacpp # full llamacpp repeats

./scripts/run-benchmark.py # same as make benchmark
./scripts/run-benchmark.py --help # show all options
# enhanced example
./scripts/run-benchmark.py --image local/transformers-enhanced-batch:0.1.0 --build-target transformers-enhanced-batch --manifests k8s/transformers-enhanced-batch
./scripts/run-benchmark.py --image local/transformers-enhanced-cache:0.1.0 --build-target transformers-enhanced-cache --manifests k8s/transformers-enhanced-cache --cache-policy clear-per-concurrency
```

| Purpose | make | Run script directly |
| --- | --- | --- |
| Install tools | `make install` | `./scripts/local-k8s.sh install` |
| Create/delete cluster | `make up`, `make down` | `./scripts/local-k8s.sh up`, `./scripts/local-k8s.sh down` |
| Cluster status | `make status`, `make test` | `./scripts/local-k8s.sh status`, `./scripts/local-k8s.sh test` |
| Single sweep | `make benchmark` | `./scripts/run-benchmark.py` |
| Full repeats | `make benchmark-suite` | `python3 scripts/run-benchmark-suite.py` |

For running only the server see the [inference engine guide](docs/guides/inference-engine.md), and for llama.cpp deployment see the [llamacpp section](docs/guides/inference-engine.md#llamacpp) of the same document. After use, delete the cluster and PVC data inside nodes with `make down` or `./scripts/local-k8s.sh down`. Host models and collected reports are kept.

For details see [cluster usage](docs/guides/local-k8s.md), [model management](docs/guides/models.md), [Mamba state cache](docs/guides/mamba-cache.md), [AIPerf settings](docs/guides/aiperf.md), [benchmark execution and result analysis](docs/guides/benchmark.md), [quality checks](docs/guides/quality-check.md), [multi-node service stability test](docs/guides/availability-test.md), [CPU HPA test](docs/guides/hpa-test.md), and [test results](docs/reports/README.md).
