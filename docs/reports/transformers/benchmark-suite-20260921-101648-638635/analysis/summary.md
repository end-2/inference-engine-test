> Korean version: [한국어](summary-KR.md)

# SmolLM2 CPU performance comparison: default single-node kind

On 2026-09-21, measured SmolLM2-135M-Instruct FP32 with 8 CPU requests/limits, 16Gi memory, and 4 PyTorch compute threads. Each of base, enhanced-batch, and enhanced-cache ran a concurrency 1, 2, 4, 8 sweep with 3 repetitions.

All 3,600 measured and 72 warmup requests succeeded. There were no short or over-length outputs, and all stored Pod states show 0 container restarts. Total suite time was **64 min 18s**, and the sum of measured-request run time was **49 min 07s**.

## Throughput and latency

Mean ± sample standard deviation. Latency p95 is the mean of per-run p95 values, not a pooled-across-requests p95.

| Implementation | Concurrency | Output tok/s | TTFT mean (ms) | TTFT p95 (ms) | ITL mean (ms) | Mean response (s) | Measured run (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| base | 1 | 44.79 ± 0.17 | 138.88 ± 0.62 | 233.32 ± 3.71 | 19.33 ± 0.08 | 0.93 ± 0.00 | 93.59 ± 0.36 |
| base | 2 | 44.96 ± 0.11 | 1063.57 ± 2.73 | 1589.18 ± 9.06 | 19.27 ± 0.05 | 1.86 ± 0.00 | 93.24 ± 0.23 |
| base | 4 | 45.27 ± 0.07 | 2874.59 ± 3.96 | 3729.29 ± 6.00 | 19.12 ± 0.05 | 3.66 ± 0.01 | 92.61 ± 0.15 |
| base | 8 | 45.09 ± 0.08 | 6408.65 ± 12.18 | 7300.41 ± 13.77 | 19.20 ± 0.03 | 7.20 ± 0.01 | 92.97 ± 0.17 |
| enhanced-batch | 1 | 45.39 ± 0.07 | 145.32 ± 0.31 | 239.77 ± 3.18 | 18.84 ± 0.04 | 0.92 ± 0.00 | 92.35 ± 0.14 |
| enhanced-batch | 2 | 62.21 ± 0.14 | 306.36 ± 0.51 | 415.15 ± 2.83 | 26.88 ± 0.07 | 1.35 ± 0.00 | 67.39 ± 0.15 |
| enhanced-batch | 4 | 78.53 ± 0.15 | 733.91 ± 0.85 | 762.99 ± 2.07 | 38.03 ± 0.12 | 2.13 ± 0.00 | 53.38 ± 0.10 |
| enhanced-batch | 8 | 79.32 ± 1.05 | 2756.33 ± 40.23 | 2934.21 ± 29.59 | 37.60 ± 0.52 | 4.14 ± 0.06 | 52.85 ± 0.69 |
| enhanced-cache | 1 | 48.08 ± 0.12 | 75.73 ± 0.32 | 127.16 ± 3.75 | 19.29 ± 0.04 | 0.87 ± 0.00 | 87.19 ± 0.22 |
| enhanced-cache | 2 | 48.90 ± 0.19 | 913.21 ± 3.35 | 1406.97 ± 5.24 | 19.24 ± 0.07 | 1.71 ± 0.01 | 85.72 ± 0.34 |
| enhanced-cache | 4 | 49.06 ± 0.09 | 2587.39 ± 4.52 | 3367.36 ± 3.36 | 19.19 ± 0.04 | 3.38 ± 0.01 | 85.45 ± 0.15 |
| enhanced-cache | 8 | 48.97 ± 0.20 | 5837.01 ± 23.49 | 6648.95 ± 29.70 | 19.22 ± 0.07 | 6.63 ± 0.03 | 85.60 ± 0.35 |

## Sweep durations

Total duration includes image and cluster checks, Pod readiness, cache initialization, warmup, and result collection. Measured time is AIPerf's `benchmark_duration`.

| Implementation | Run 1 | Run 2 | Run 3 | Total mean | Measured mean |
| --- | ---: | ---: | ---: | ---: | ---: |
| base | 7 min 56s | 7 min 53s | 7 min 55s | 7 min 55s | 6 min 12s |
| enhanced-batch | 6 min 05s | 6 min 04s | 6 min 05s | 6 min 05s | 4 min 26s |
| enhanced-cache | 7 min 26s | 7 min 25s | 7 min 27s | 7 min 26s | 5 min 44s |

## Comparison with previous multi-node measurement

Used the same model, image IDs, data seed and input files, 8 CPUs, and 4 PyTorch threads as before. The comparison also reflects fewer nodes and removal of existing monitoring and other test Pods.

| Implementation | Concurrency | Previous output tok/s | Single-node output tok/s | Change |
| --- | ---: | ---: | ---: | ---: |
| base | 1 | 44.54 | 44.79 | +0.57% |
| base | 2 | 44.70 | 44.96 | +0.57% |
| base | 4 | 44.72 | 45.27 | +1.22% |
| base | 8 | 44.74 | 45.09 | +0.78% |
| enhanced-batch | 1 | 44.97 | 45.39 | +0.95% |
| enhanced-batch | 2 | 61.94 | 62.21 | +0.43% |
| enhanced-batch | 4 | 77.64 | 78.53 | +1.15% |
| enhanced-batch | 8 | 77.88 | 79.32 | +1.85% |
| enhanced-cache | 1 | 47.36 | 48.08 | +1.53% |
| enhanced-cache | 2 | 48.55 | 48.90 | +0.73% |
| enhanced-cache | 4 | 48.45 | 49.06 | +1.26% |
| enhanced-cache | 8 | 48.54 | 48.97 | +0.88% |

Comparison figures against the previous multi-node measurement are summarized in the table above and [comparison CSV](summary.csv).

## Measurement conditions and interpretation

- Apple M5 Pro, Docker Linux aarch64, Docker VM with 15 CPUs and about 24GiB memory. Uses 1 control-plane node with default kind settings.
- On the fresh cluster, both inference and AIPerf were pinned to local-k8s-control-plane. Default system Pods and this experiment's workloads ran. Inference and AIPerf Pods use Guaranteed QoS; AIPerf uses 1 CPU and 1Gi memory.
- Each concurrency used a fresh inference Pod, and the per-round implementation execution order was rotated. enhanced-batch maximum batch size is 4 with 5ms wait.
- enhanced-cache cleared the PVC only before the sweep and preserved it between concurrency steps. Warmup and measurement fill and reuse the cache.
- 16 inputs, seed 42, sequential repetition, streaming, ignore_eos. Target input/output distributions are 50% each for 64/32 and 256/64. The actual 100 requests are 69 with 32-token outputs and 31 with 64-token outputs; inputs are 94 or 286 tokens including the chat template. Input data hashes are identical across all 36 conditions.
- Cache performance reflects this load repeating the same inputs. Service loads dominated by unique inputs need separate measurement.

[Per-run metrics and individual reports](../summary.md), [mean and standard deviation CSV](../summary.csv), [validation results](run.json), [run environment and image hashes](../environment/run.json).

`runs.csv` holds the inference Pod CPU sample mean and maximum memory working set over the measured-request window. Identical kubelet CPU timestamps are included once; this is not a time-weighted mean.

## Redeployment and re-run

Recreated `local-k8s` with the default `config/cluster/kind.yaml`. Cluster settings are recorded in the [run environment](../environment/run.json).

Loaded the same image IDs as before onto the new node, passed the DNS smoke test, then ran. Cluster recreation and image loading time are not included in the suite durations above.

```sh
python3 scripts/run-benchmark-suite.py --backend transformers --repetitions 3 \
  --inference-node local-k8s-control-plane \
  --benchmark-node local-k8s-control-plane
```

After measurement, kept the single-node cluster and restored base with 8 CPU requests/limits and 4 PyTorch compute threads. Verified `/readyz` 200 and archived the [restored Pod](after-pod.json).
