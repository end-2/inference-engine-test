> Korean version: [한국어](requirements-KR.md)

# Minimum Runtime Requirements

Host environment, tools, and resource requirements for a CPU-only kind cluster and for inference and measurement workloads.

Base versions follow [tool versions](../../config/versions.env). Support for other versions needs confirmation by actual runs.

## Host OS and container environment

| Item | Requirement |
| --- | --- |
| OS | Local Linux, macOS, Windows (WSL2). A distribution and kernel supported by Docker |
| cgroup | cgroup v2 enabled, as needed by default Kubernetes configuration |
| CPU architecture | x86_64 or arm64. Node image matches the host architecture |
| Docker | Local Docker Engine and Docker access for the current user |
| Node execution | Environment allows privileged kind node containers and host directory bind mounts |
| Shell | POSIX `sh` plus common commands such as `awk`, `grep`, and `mktemp` |

Builds and cluster runs use the same local Docker daemon.

## kind and Kubernetes

Use the kind, kubectl, and node image combination in [versions.env](../../config/versions.env). The node image architecture must match the host CPU architecture. When changing versions, check [supported images for the kind release](https://github.com/kubernetes-sigs/kind/releases) and the [kubectl version skew policy](https://kubernetes.io/releases/version-skew-policy/#kubectl).

Create the CPU cluster with `local-k8s.sh up`; it does not include GPU settings. `up` mounts the host model directory read-only to `/models` on nodes. For GPU clusters, see the [benchmark guide](benchmark.md#gpu-benchmarks). For model downloads and path configuration, see the [model volume guide](models.md), and for cluster configuration changes, see the [cluster guide](local-k8s.md).

## Additional tools by task

| Task | Additional requirements |
| --- | --- |
| kind, kubectl and Helm installation | `curl` or `wget` for downloads, `sha256sum` or `shasum` for checksum verification, `tar` with gzip support for Helm |
| Model and tokenizer downloads | `curl`, `sha256sum` or `shasum` for checksum verification |
| Image builds | `docker build` |
| [Automated benchmark](benchmark.md#automated-measurement-with-pod-restarts) | Python 3.10 or later |
| Local inference and engine tests | Python 3.12 environment and the selected engine's dependencies in the [inference guide](inference-engine.md) |
| Distributed Prefill/Decode runner and reports | Python with PyYAML; report figures also need matplotlib, as described in the [PD guide](prefill-decode.md) |
| Makefile commands | `make`. Not needed when running scripts directly |

## CPU, memory, and disk

Sum the resource requests of the selected inference Deployment and the [AIPerf Job](../../k8s/aiperf/values.yaml), and reserve headroom for Kubernetes system Pods. Check inference settings in the [Transformers](../../k8s/inference/values.yaml) or [llama.cpp](../../k8s/inference/profiles/base-llamacpp-cpu.yaml) manifest.

When Docker runs in a VM, also check resources assigned to the VM. Adjust measurement resources for the environment while keeping `requests=limits`.

Disk needs space for [model files](models.md#download), Docker images and build cache, kind node image copies, temporary archives, and results. Also check free space in `TMPDIR` and the Docker data path.

## Network

Initial installation and image builds, plus model and tokenizer downloads, need HTTPS access to each file source.

| Target | Main sources |
| --- | --- |
| kind, kubectl and Helm | GitHub releases, `dl.k8s.io`, `get.helm.sh` |
| Node and auxiliary images | Container registries such as Docker Hub |
| Image build dependencies | Debian package repositories, PyPI |
| Models and tokenizers | Hugging Face |

In proxy or firewall environments, also allow redirected download hosts and CDNs.

For offline runs, prepare [tools and images](local-k8s.md#environment-preparation), inference [models](models.md), and the [tokenizer](aiperf.md#preparing-the-tokenizer) for AIPerf measurement in advance.

The default network is IPv4, and the Kubernetes API binds to local `127.0.0.1`. Docker networking and cluster DNS must work, and Pod and Service ranges must not collide with host or VPN ranges. For remote access or IPv6 configuration, change [cluster settings](local-k8s.md#cluster-settings).

## Pre-run checks

After host preparation and tool installation, check from the repository root.

```sh
uname -s
uname -m
./scripts/local-k8s.sh doctor
```

`doctor` checks tool presence and Docker access, but does not guarantee every version combination or file permission.

Follow [quick start](../../README.md#quick-start) for the base experiment, and the [Transformers guide](inference-engine.md#docker-and-kubernetes) for server-only deployment. Without a model, run `scripts/local-k8s.sh up` then `scripts/local-k8s.sh test` to check only cluster and DNS.
