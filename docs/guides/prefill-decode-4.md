> Korean version: [한국어](prefill-decode-4-KR.md)

# MPS 4-Way Prefill/Decode Comparison

Compares 4 Aggregation workers against 1 Prefill and 3 Decodes on SmolLM2-135M FP16. It is a separate overlay based on the [2-way setup](prefill-decode.md), and keeps the existing configuration files and base run commands.

[GPU setup validation](../reports/gpu/pd/four-slot-check-20261001/validation.md) confirmed request distribution across four CUDA clients and both modes.

[Full workload comparison](../reports/gpu/pd/benchmark-four-20261001/summary.md) records throughput, TTFT, latency, and router memory validation over 3 repetitions.

The RUNNING-first policy and chunked prefill similar to vLLM V1 can be tested with the [separate token budget scheduler](prefill-decode-scheduler.md).

| Item | Existing 2-way | Additional 4-way |
| --- | --- | --- |
| Selection | `MPS_REPLICAS=2` or omitted | `MPS_REPLICAS=4` |
| Default cluster | `local-k8s-gpu-mps` | `local-k8s-gpu-mps4` |
| Namespace | `pd-comparison` | `pd-comparison-4` |
| MPS configuration | `config/cluster/mps.yaml` | `config/cluster/mps-4.yaml` |
| Aggregation | 2 workers | 4 workers |
| Disaggregation | 1 Prefill, 1 Decode | 1 Prefill, 3 Decodes |
| Per-client memory limit on 8 GiB GPU | 4 GiB | 2 GiB |
| Per-client active thread limit | 50% | 25% |

Each worker uses 1 shared GPU slot, CPU request 1 and limit 2, and 2 GiB host memory. In 4-way, both modes total CPU request 4, limit 8, and 8 GiB memory across workers. MPS limits are per-CUDA-client limits and do not guarantee throughput ratios.

The router distributes round-robin to the StatefulSet Pod addresses of either 4 Aggregations or 3 Decodes. `--decode-urls` accepts multiple Decode addresses and takes precedence over the legacy `--decode-url`. Readiness checks all backends of the selected mode. It does not automatically retry requests sent to a failed backend.

## Cluster and image preparation

First meet the [MPS prerequisites](gpu-mps.md#preparation-and-creation) and stop existing work on GPU 0. Both clusters use the same physical GPU, so do not run MPS daemons at the same time. Cluster and namespace separation does not mean physical separation of GPU resources.

To preserve the running 2-way PD cluster while stopping it, run the following after benchmark Jobs finish. Existing PVCs and the cluster are kept.

```sh
GPU_SHARING=mps MPS_REPLICAS=2 ./scripts/local-k8s-gpu.sh kubectl \
  -n pd-comparison scale deployment,statefulset --all --replicas=0
GPU_SHARING=mps MPS_REPLICAS=2 ./scripts/local-k8s-gpu.sh kubectl \
  -n pd-comparison wait --for=delete pod -l app.kubernetes.io/part-of=pd-comparison --timeout=180s
GPU_SHARING=mps MPS_REPLICAS=2 ./scripts/local-k8s-gpu.sh kubectl \
  label node -l nvidia.com/gpu.present=true nvidia.com/mps.capable-
```

After the MPS control daemon Pod in the NVIDIA namespace exits and `nvidia-smi` shows no CUDA work, start 4-way. If other GPU services are running, stop them first.

```sh
make up DEVICE=gpu GPU_SHARING=mps MPS_REPLICAS=4
make build-image load-image DEVICE=gpu GPU_SHARING=mps MPS_REPLICAS=4 VARIANT=transformers-pd
make build-benchmark-image load-benchmark-image DEVICE=gpu GPU_SHARING=mps MPS_REPLICAS=4
make pd-deploy MPS_REPLICAS=4 PD_MODE=disaggregated
```

For a custom cluster name, pass the same `CLUSTER_NAME` to all commands. Passing `MPS_REPLICAS=4` against the existing 2-way cluster name is rejected. `up` and `test` check that 4 CUDA clients connect to the same MPS server.

```sh
k4() { GPU_SHARING=mps MPS_REPLICAS=4 ./scripts/local-k8s-gpu.sh kubectl -n pd-comparison-4 "$@"; }
k4 get pods -o wide
k4 port-forward service/pd-router 8000:8000
```

To switch to Aggregation, run the following. It refuses to switch while a benchmark Job is running, and deploys the new mode after terminated worker Pods return GPU slots.

```sh
make pd-deploy MPS_REPLICAS=4 PD_MODE=aggregated
```

## Workload comparison

Both modes use the same [base workload](../../config/benchmarks/pd.json). Input and output lengths, mix distribution, concurrency, request count, and repetition count match the 2-way setup.

```sh
make pd-benchmark MPS_REPLICAS=4
# Direct equivalent
python3 scripts/benchmark-pd.py --mps-replicas 4 --config config/benchmarks/pd.json
```

Stores results in `docs/reports/gpu/pd/pd4-<timestamp>/` and `reports/pd/pd4-<timestamp>/`. JSON records MPS slot count, per-role worker counts, namespace, and run configuration. Report generation shows 4 shares, the 25% limit, and 3 Decodes.

```sh
python3 scripts/report-pd.py docs/reports/gpu/pd/pd4-<timestamp>
```

The router's 2 concurrent transfer slots, 8 request admission limit, and 1 GiB memory cap apply in common. In streaming, a transfer slot returns when the Decode response header arrives, so 3 Decode workers can generate concurrently. In non-streaming, a slot can be held until response completion, so use the default streaming workload for this comparison. For metrics and memory settings, see the [common guide](prefill-decode.md#router-memory-limits).

4-way changes Decode worker count and resource allocation on the same physical GPU. Compare throughput, TTFT, and latency on the same workload without assuming it is faster than 2-way.

## Teardown and restoring the existing setup

After copying results, stop only the 4-way cluster. Its results PVC is also deleted.

```sh
make down DEVICE=gpu GPU_SHARING=mps MPS_REPLICAS=4
make up DEVICE=gpu GPU_SHARING=mps MPS_REPLICAS=2
make pd-deploy MPS_REPLICAS=2 PD_MODE=aggregated
```

4-way manifests are in the [Aggregation profile](../../k8s/inference-distributed/profiles/mps-4-aggregated.yaml) and [Disaggregation profile](../../k8s/inference-distributed/profiles/mps-4-disaggregated.yaml). Run validation with the common guide's PD tests and `tests/test_gpu_cluster.py`.
