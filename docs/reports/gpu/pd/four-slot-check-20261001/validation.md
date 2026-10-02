> Korean version: [한국어](validation-KR.md)

# MPS 4-Way Split Configuration Verification

On 2026-10-01 UTC, verified real deployments and request distribution for 4 Aggregation workers and 1 Prefill plus 3 Decode workers on an RTX 2060 SUPER 8 GiB. This is a reduced-workload check ahead of the full performance comparison; it draws no conclusions about sustained load or the full input/output matrix.

## Verified Behavior

- 4 MPS shared resources, 25% per-client active thread limit, 2 GiB GPU memory limit.
- 4 CUDA clients connected to the same MPS server concurrently, passing memory write and read checks.
- 4 workers Ready in both modes, with matching GPU slots, CPU, and host memory budgets.
- Request distribution to 4 Aggregation Pod addresses and 3 Decode Pod addresses.
- Matching request payload hashes and actual input/output token distributions between modes.
- All 64 measured requests succeeded, with 0 worker and Router restarts.

Measured synthetic inputs 64 and 704 tokens, output 16 tokens, at concurrency 4 and 8 with 8 requests per condition in 1 run. Actual inputs are 94 and 734 tokens. Excluded 2 warmup requests per condition from measurement statistics. Conditions are recorded in [measurement tables and figures](summary.md) and [reproduction workload](workload.json).

Completed request counts from worker logs including warmup are as follows. Internal Prefill calls are not double-counted in generation-completion logs.

| Mode | Pod | Completed Requests |
| --- | --- | ---: |
| Aggregation | `pd-aggregate-0` | 10 |
| Aggregation | `pd-aggregate-1` | 10 |
| Aggregation | `pd-aggregate-2` | 10 |
| Aggregation | `pd-aggregate-3` | 10 |
| Disaggregation | `pd-decode-0` | 14 |
| Disaggregation | `pd-decode-1` | 13 |
| Disaggregation | `pd-decode-2` | 13 |

The Disaggregation Router cgroup `memory.peak` was 81,686,528 bytes (77.9 MiB). `oom` and `oom_kill` in `memory.events` were 0. Kept 2 concurrent state-transfer slots and the 1 GiB memory limit.

## Existing Configuration Preservation

`config/cluster/mps.yaml`, `config/cluster/mps-smoke.yaml`, and all existing YAML under `k8s/gpu-mps/` have identical SHA-256 before and after the work. The 4-way split is added as new configuration and overlays, keeping the 2-way default. Unit tests verify that requests to reconfigure or delete an existing cluster with a different split count are rejected and that 4-way deployments use only their own namespace.

The real GPU check temporarily set the existing `local-k8s-gpu` cluster to a 4-way split in `pd-comparison-4`. No separate default `local-k8s-gpu-mps4` cluster is kept running. After verification, removed the temporary namespace and restored existing Deployment specs, Helm values, and GPU `Default` compute mode. One `base-llamacpp` is Ready.

30 PD tests, 13 GPU cluster tests, and 11 GPU benchmark configuration tests passed. Both overlays' Kubernetes server dry-runs and shellcheck also passed. Built the new inference image and loaded it on the test node.

[Environment validation JSON](environment-validation.json) records MPS client lists, images, memory, request distribution, and preservation checks. Raw logs and deployment specs are kept in `reports/pd/four-slot-check-20261001/`. For actual use, follow the [4-way execution guide](../../../../guides/prefill-decode-4.md).
