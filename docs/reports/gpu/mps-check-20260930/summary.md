> Korean version: [한국어](summary-KR.md)

# kind MPS 2-Way Split Model Execution Verification

On 2026-09-30 UTC, configured 2 MPS shared resources on an RTX 2060 SUPER 8 GiB and ran the four models in `.models/` concurrently on two Pods. All 48 generation requests succeeded for both the same-model 4-combination set and the different-model 2-combination set.

## Environment and Configuration

- Cluster: `kind-local-k8s-gpu`, node: `local-k8s-gpu-worker`.
- NVIDIA driver: `580.126.09`, device plugin Helm chart: `0.20.1`.
- PyTorch: `2.10.0+cu128`, Transformers: `4.57.6`.
- Each Pod ran as one CUDA process and requested `nvidia.com/gpu.shared: 1`.
- Set `nvidia.com/mps.capable=true` on the worker and applied the following configuration via Helm `config.map.mps` and `config.default=mps`.

```yaml
version: v1
sharing:
  mps:
    renameByDefault: true
    resources:
      - name: nvidia.com/gpu
        replicas: 2
```

The node `nvidia.com/gpu.shared` quota was 2. Verified memory limit `4G` and active thread percentage `50.0` with MPS control commands. In each combination, verified 2 client PIDs connected to the same MPS server, with overlapping inference execution windows of the two processes. Transformers clients showed 16 SMs.

## Results

| Pod A Model | Pod B Model | Execution | Successful Requests | Observed Max Total GPU Memory (MiB) |
| --- | --- | --- | ---: | ---: |
| SmolLM2-135M | SmolLM2-135M | FP16 | 8/8 | 836 |
| Mamba-130M | Mamba-130M | FP16 | 8/8 | 1512 |
| Jamba-tiny-dev | Jamba-tiny-dev | FP16 | 8/8 | 1700 |
| Qwen2.5-0.5B | Qwen2.5-0.5B | GGUF Q4_K_M | 8/8 | 1572 |
| SmolLM2-135M | Qwen2.5-0.5B | FP16, GGUF Q4_K_M | 8/8 | 1204 |
| Mamba-130M | Jamba-tiny-dev | FP16 | 8/8 | 1606 |

Memory is total GPU usage read via `nvidia-smi` during inference at roughly 1-second plus status-query intervals, including both Pods and the MPS server. It is not the instantaneous peak between samples nor per-Pod usage.

Each Pod generated 64 tokens each from 128-token and 512-token inputs with batch size 1. Ran twice per input length; a separate 32-token input and 8-token generation warmup is excluded from the request count. Passed the same start time after model loading and warmup of each combination finished.

Mamba and Jamba ran on the PyTorch CUDA path without dedicated Mamba CUDA extensions. Jamba `use_mamba_kernels` is `False`. Qwen used `n_ctx=1024`, `n_batch=512`, `n_gpu_layers=-1`, and both Pods confirmed 25/25 layer GPU offload in logs.

## Scope and Records

These results verify model loading and CUDA token generation using local weights. They do not measure HTTP serving, large batches, long context, inter-request caches, sustained load, or generation quality. MPS limits are per CUDA client; do not interpret them as a 4 GiB limit for a whole Pod running multiple CUDA processes.

Image identifiers, client memory, and per-combination results are in [summary.json](summary.json). Run scripts, Pod specs, generation results, and MPS logs are kept in `.local-k8s/mps-check-20260930/` at the repository root.

After verification, removed the test namespace and MPS Pods and restored the Helm configuration, all existing Deployment specs, and the GPU `Default` compute mode. The `nvidia.com/gpu` quota is 1 again, and the existing llama.cpp server readiness and HTTP status responses are normal.
