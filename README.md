> Korean version: [한국어](README-KR.md)

# Inference engine test

Measures inference, batching and prefix cache with Transformers and llama.cpp on kind. CPU is the default; NVIDIA GPU, Mamba, Jamba and distributed Prefill/Decode experiments have dedicated guides.

## Prerequisites

- A running local Docker daemon, POSIX shell, Python 3.10 or later and `make`
- Download and checksum tools, internet access for initial setup, and enough resources for the selected workloads: see [runtime requirements](docs/guides/requirements.md)

## Quick start

Run from the repository root:

```sh
make install
make benchmark-suite
```

This installs kind, kubectl and Helm, then prepares the model, cluster and images and runs the default CPU comparison. Results are saved under `docs/reports/transformers/benchmark-suite-*/`.

To measure one implementation:

```sh
make benchmark VARIANT=transformers-enhanced-batch
```

For implementation selection, direct script commands, repetitions, cache policies and GPU runs, see the [benchmark guide](docs/guides/benchmark.md). For a server without measurements, see the [inference engine guide](docs/guides/inference-engine.md).

After collecting results, `make down` deletes the CPU cluster and its node-local PVC data. Host models and exported reports are kept.

## Guides and results

- [Source structure and feature experiments](docs/guides/feature-experiments.md), [Helm profiles](docs/guides/manifests.md)
- [Cluster setup](docs/guides/local-k8s.md), [model management](docs/guides/models.md), [AIPerf](docs/guides/aiperf.md)
- [Mamba state cache](docs/guides/mamba-cache.md), [Jamba hybrid batching and HiCache](docs/guides/hybrid-cache.md)
- [MPS GPU sharing](docs/guides/gpu-mps.md), [distributed Prefill/Decode](docs/guides/prefill-decode.md)
- [Quality checks](docs/guides/quality-check.md), [MMLU accuracy](docs/guides/mmlu-check.md), [availability tests](docs/guides/availability-test.md), [HPA tests](docs/guides/hpa-test.md)
- [Test results](docs/reports/README.md), [Transformers CPU report](docs/reports-transformers.md)
