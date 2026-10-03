> Korean version: [한국어](gpu-mps-KR.md)

# MPS GPU sharing cluster

`GPU_SHARING=mps` creates a separate kind cluster that registers GPU 0 as 2 shared resources. Two Pods on one worker can each request `nvidia.com/gpu.shared: 1`. Default behavior of the CPU cluster and GPU exclusive mode is unchanged.

`MPS_REPLICAS=4` keeps existing settings while selecting `local-k8s-gpu-mps4` and the [separate 4-way config](../../config/cluster/mps-4.yaml). The run procedure comparing 4 aggregations with 1 prefill and 3 decodes is in the [4-way PD guide](prefill-decode-4.md). When omitted, `MPS_REPLICAS=2`; a command that changes the split count of an existing cluster is rejected.

## Preparation and creation

Prepare the [GPU environment tools and runtime](benchmark.md#gpu-benchmarks) first. The MPS cluster and the existing GPU cluster use the same physical GPU 0, so do not run GPU workloads at the same time. When starting MPS, if a CUDA process is on the GPU, `up` prints the PID and stops. Set existing inference Deployments to 0 replicas or stop those GPU jobs first.

```sh
make install DEVICE=gpu
make download-model
make up DEVICE=gpu GPU_SHARING=mps
make status DEVICE=gpu GPU_SHARING=mps
```

| Setting | GPU exclusive mode | MPS mode |
| --- | --- | --- |
| `GPU_SHARING` | `none` (default) | `mps` |
| Default cluster name | `local-k8s-gpu` | `local-k8s-gpu-mps` |
| Worker resource | `nvidia.com/gpu: 1` | `nvidia.com/gpu.shared: 2` |

The MPS mode kubeconfig is stored at `.local-k8s/<cluster name>/kubeconfig`. `CLUSTER_NAME` can rename it, but does not change the sharing mode or split count of an existing cluster. Use the same `GPU_SHARING`, `MPS_REPLICAS`, and `CLUSTER_NAME` for creation, image loading, status, and deletion.

The [MPS config](../../config/cluster/mps.yaml) sets each CUDA client's memory limit and compute thread limit to half. On an 8 GiB GPU the memory limit is 4 GiB. The reference configuration uses one CUDA process per Pod; this does not mean summed Pod limits across processes or guaranteed 50% throughput. For config behavior, see the [NVIDIA device plugin docs](https://github.com/NVIDIA/k8s-device-plugin#with-cuda-mps).

## Two-Pod inference example

Deploy the [Deployment and Service](../../k8s/inference/profiles/transformers-base-mps.yaml) that use the SmolLM2 model and existing GPU images. The Deployment has 2 replicas and each Pod requests 1 shared GPU resource. CPU requests of the default GPU Deployment are also adjusted so both Pods fit together.

```sh
make build-image load-image DEVICE=gpu GPU_SHARING=mps VARIANT=transformers-base
GPU_SHARING=mps LOCAL_K8S_SCRIPT=./scripts/local-k8s-gpu.sh ./scripts/k8s.sh apply k8s/inference/profiles/transformers-base-mps.yaml
GPU_SHARING=mps ./scripts/local-k8s-gpu.sh kubectl rollout status deployment/transformers-mps --timeout=300s
GPU_SHARING=mps ./scripts/local-k8s-gpu.sh kubectl get pods -l app=transformers-mps -o wide
GPU_SHARING=mps ./scripts/local-k8s-gpu.sh kubectl port-forward service/transformers-mps 8000:8000
```

API request format follows the [inference engine guide](inference-engine.md). When deploying another model, use `runtimeClassName: nvidia` and `nvidia.com/gpu.shared: 1`. Concurrent run results for all four local models and validation conditions are in the [MPS model report](../reports/gpu/mps-check-20260930/summary.md).

`make benchmark` and `make benchmark-suite` are for GPU exclusive measurement and do not accept MPS mode. Run the MPS inference server with the deployment steps above.
For sources, dedicated deployments, and AIPerf runs comparing split prefill and decode, see the [PD comparison guide](prefill-decode.md).

## Validation and shutdown

`up` on a new cluster automatically runs a CUDA smoke test that starts as many Pods as the selected split count. It checks GPU memory writes and reads, the number of clients connected to the same MPS server, and removes test resources. On rerun, all selected shared resources must be free.

```sh
GPU_SHARING=mps ./scripts/local-k8s-gpu.sh kubectl scale deployment/transformers-mps --replicas=0
make test DEVICE=gpu GPU_SHARING=mps
GPU_SHARING=mps ./scripts/local-k8s-gpu.sh kubectl scale deployment/transformers-mps --replicas=2
```

`down` stops regular Pods on workers, then stops the MPS daemon and deletes the cluster. In-node data is deleted and host models are kept. Restart stopped inference Deployments of the existing GPU cluster when needed.

```sh
make down DEVICE=gpu GPU_SHARING=mps
```

Configuration and lifecycle tests that run without a GPU:

```sh
python3 -m unittest discover -s tests -p 'test_gpu_*.py' -v
sh tests/test-local-k8s.sh
```
