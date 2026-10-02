> Korean version: [한국어](validation-KR.md)

# Execution Environment and Stability Verification

Ran the full workload 3 times from 2026-10-01 12:11:27 to 18:12:59 UTC. Compared 4 Aggregation workers against 1 Prefill plus 3 Decode workers on 4 MPS shares of the same GPU. All 7,680 measured requests across 240 condition runs succeeded; 960 warmup requests are excluded from performance statistics.

- Request payload hashes and actual input/output length request counts matched between modes in every condition and repetition. Output lengths matched requested values.
- Each deployment consisted of 4 GPU workers and 1 router. All were Ready at the end of fixed-length and mixed loads, with 0 Pod restarts.
- Including warmup, verified 360 completed requests per A worker and 480 per D worker in each repetition.
- MPS active thread limit was 25% per client with a 2 GiB GPU memory limit; verified 4 CUDA clients just before completion.
- All deployments had the same inference image ID, and the run image PD source hash matched the repository.

Router container cgroup memory records are as follows. Each mode deployment created fresh Pods. Maxima are per-Pod-lifetime `memory.peak`; memory limit is 1 GiB in all cases.

| Repetition | A Max MiB | D Max MiB | OOM | Pod Restarts |
| --- | ---: | ---: | ---: | ---: |
| 1 | 51.82 | 82.53 | 0 | 0 |
| 2 | 54.21 | 83.71 | 0 | 0 |
| 3 | 47.71 | 82.43 | 0 | 0 |

Measurement temporarily used the existing `local-k8s-gpu` cluster as a 4-way split. After completion, verified that existing Deployment specs and NVIDIA device plugin Helm values match pre-run state. GPU compute mode is `Default`, node allocated resources are restored to 1 GPU and 0 shared GPUs, and the existing `base-llamacpp` is 1/1 Ready.

The existing 2-way-split `config/cluster/mps.yaml`, `config/cluster/mps-smoke.yaml`, and YAML files under `k8s/gpu-mps` have identical SHA-256 before and after the run. The 4-way overlay with 1 Prefill and 3 Decode configuration is retained.

The cluster is now restored to its original configuration. To re-measure, first prepare 4 MPS slots with the [4-way guide](../../../../guides/prefill-decode-4.md), then specify the prepared cluster name in the benchmark `--cluster`. The run command in the report records the cluster name at measurement time.

[Environment validation JSON](environment-validation.json) contains images, MPS configuration, per-deployment Pod status, memory events, and preservation checks. Original Pod snapshots, cgroup records, and worker logs are kept in `reports/pd/benchmark-four-20261001/r*/<mode>/`.
