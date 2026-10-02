> Korean version: [한국어](summary-KR.md)

# 3-repetition benchmark by inference implementation

All 12 sweeps measuring 4 conditions 3 times each are complete. All 4,800 measured and 96 warmup requests succeeded with no short or over-length outputs.

- Status: complete
- Repetitions per condition: 3
- Inference node: `local-k8s-worker`; AIPerf node: `local-k8s-worker2`
- Each sweep uses concurrency 1, 2, 4, 8; each step has 2 warmup and 100 profiling requests.
- Each step starts with a fresh inference Pod. Image IDs and node placement are fixed across repetitions.
- Cache clear: empty PVC before every step. Cache preserve: empty PVC before the sweep, then retain it between steps.
- Cache clearing precedes warmup; cache can fill and be reused within each step.
- Execution order rotates by one condition each repetition. All sweeps run sequentially.
- Values are mean ± sample standard deviation across sweeps. TTFT p95 is the mean of per-sweep p95 values, not a pooled p95.

| Condition | Concurrency | Runs | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| base | 1 | 3 | 43.24 ± 0.57 | 628.68 ± 6.70 | 1119.64 ± 18.75 | 8.29 ± 0.15 |
| base | 2 | 3 | 43.83 ± 0.14 | 1572.32 ± 4.24 | 2062.74 ± 10.95 | 8.19 ± 0.10 |
| base | 4 | 3 | 44.03 ± 0.27 | 3442.62 ± 18.30 | 4319.00 ± 41.40 | 8.18 ± 0.11 |
| base | 8 | 3 | 44.45 ± 0.21 | 7009.25 ± 34.46 | 7984.90 ± 58.09 | 8.05 ± 0.10 |
| enhanced-batch | 1 | 3 | 49.35 ± 0.31 | 572.66 ± 4.78 | 1078.96 ± 9.91 | 6.70 ± 0.02 |
| enhanced-batch | 2 | 3 | 50.15 ± 0.32 | 854.30 ± 3.87 | 1449.09 ± 6.76 | 19.28 ± 0.35 |
| enhanced-batch | 4 | 3 | 50.57 ± 0.32 | 1334.28 ± 31.55 | 2609.01 ± 105.61 | 48.07 ± 1.35 |
| enhanced-batch | 8 | 3 | 51.69 ± 0.16 | 2525.54 ± 155.68 | 4050.89 ± 319.28 | 94.60 ± 4.37 |
| enhanced-cache-clear | 1 | 3 | 98.93 ± 0.31 | 106.16 ± 0.30 | 434.90 ± 5.90 | 7.71 ± 0.03 |
| enhanced-cache-clear | 2 | 3 | 98.53 ± 1.43 | 531.55 ± 6.42 | 1762.11 ± 17.06 | 7.70 ± 0.11 |
| enhanced-cache-clear | 4 | 3 | 97.20 ± 1.84 | 1388.29 ± 25.48 | 3330.59 ± 71.88 | 7.83 ± 0.18 |
| enhanced-cache-clear | 8 | 3 | 97.64 ± 0.52 | 3032.04 ± 17.64 | 6915.72 ± 10.30 | 7.73 ± 0.07 |
| enhanced-cache-preserve | 1 | 3 | 97.48 ± 0.78 | 107.07 ± 1.72 | 441.68 ± 2.58 | 7.83 ± 0.07 |
| enhanced-cache-preserve | 2 | 3 | 128.15 ± 2.75 | 336.58 ± 7.86 | 563.05 ± 21.63 | 7.68 ± 0.16 |
| enhanced-cache-preserve | 4 | 3 | 129.34 ± 1.89 | 969.95 ± 15.06 | 1300.33 ± 41.07 | 7.57 ± 0.07 |
| enhanced-cache-preserve | 8 | 3 | 130.01 ± 3.53 | 2190.50 ± 56.90 | 2602.04 ± 66.29 | 7.58 ± 0.17 |

## Comparison graphs

![3-repetition throughput and TTFT comparison](figures/benchmark-comparison.png)

## Sweep reports

| Order | Repetition | Condition | Status | Report |
| ---: | ---: | --- | --- | --- |
| 1 | 1 | base | complete | [summary](r1/base/bench-20260920-091633-772941-local-llama-base-0.1.0/summary.md) |
| 2 | 1 | enhanced-batch | complete | [summary](r1/enhanced-batch/bench-20260920-092434-166531-local-llama-enhanced-batch-0.1.0/summary.md) |
| 3 | 1 | enhanced-cache-clear | complete | [summary](r1/enhanced-cache-clear/bench-20260920-093145-314357-local-llama-enhanced-cache-0.1.0/summary.md) |
| 4 | 1 | enhanced-cache-preserve | complete | [summary](r1/enhanced-cache-preserve/bench-20260920-093646-261612-local-llama-enhanced-cache-0.1.0/summary.md) |
| 5 | 2 | enhanced-batch | complete | [summary](r2/enhanced-batch/bench-20260920-094049-214568-local-llama-enhanced-batch-0.1.0/summary.md) |
| 6 | 2 | enhanced-cache-clear | complete | [summary](r2/enhanced-cache-clear/bench-20260920-094800-747005-local-llama-enhanced-cache-0.1.0/summary.md) |
| 7 | 2 | enhanced-cache-preserve | complete | [summary](r2/enhanced-cache-preserve/bench-20260920-095303-749128-local-llama-enhanced-cache-0.1.0/summary.md) |
| 8 | 2 | base | complete | [summary](r2/base/bench-20260920-095708-648602-local-llama-base-0.1.0/summary.md) |
| 9 | 3 | enhanced-cache-clear | complete | [summary](r3/enhanced-cache-clear/bench-20260920-100514-693326-local-llama-enhanced-cache-0.1.0/summary.md) |
| 10 | 3 | enhanced-cache-preserve | complete | [summary](r3/enhanced-cache-preserve/bench-20260920-101020-699662-local-llama-enhanced-cache-0.1.0/summary.md) |
| 11 | 3 | base | complete | [summary](r3/base/bench-20260920-101418-182171-local-llama-base-0.1.0/summary.md) |
| 12 | 3 | enhanced-batch | complete | [summary](r3/enhanced-batch/bench-20260920-102220-720274-local-llama-enhanced-batch-0.1.0/summary.md) |

`runs.csv` and `summary.jsonl` contain the individual sweep metrics; `summary.csv` includes mean, standard deviation, minimum, and maximum for every metric.
Image IDs, commands, and execution order are recorded in `run.json`. Per-request exports and resource time series are saved locally under each sweep report and are excluded from Git.

## Interpretation

- At concurrency 2, 4, 8, cache preservation averaged 30.1–33.2% higher throughput than clearing. At concurrency 8, throughput is 97.64 → 130.01 tok/s and mean TTFT is 27.8% lower.
- At concurrency 8, enhanced-batch throughput is 16.3% higher than base. Mean TTFT fell from 7009.25 to 2525.54 ms, while mean ITL rose from 8.05 to 94.60 ms.
- These results use a load that repeats 16 datasets with the same seed 42. Both cache conditions start the sweep from an empty cache; the difference is whether the cache is preserved between concurrency steps. Warmup and measurement refill and reuse the cache within each step.

## Validation and environment

- [Final validation record](verification.json): 48 steps, 48 distinct inference Pod UIDs, 4,800 measured and 96 warmup requests, 0 short or over-length outputs.
- Input data file SHA-256 is identical across all 48 steps. AIPerf container settings other than result path and concurrency are identical. All 15 cache clears were verified with 0 remaining entries after deletion.
- Inference uses 12 CPU and 16 GiB, AIPerf uses 1 CPU and 1 GiB, with requests equal to limits. Saved inference and AIPerf Pods were all verified on their assigned nodes with Guaranteed QoS.
- [Environment record](environment.json): the Docker VM's 15 CPUs and about 24 GiB are shared by 4 kind nodes. Background Deployment images, replica counts, and Docker resource settings were the same before and after measurement. Image IDs and placement nodes were fixed for every variant during the run.
- Measurement period (UTC): 2026-09-20 09:16:20–10:29:33. At exit the `llama-base` Deployment was 1/1 Ready on the enhanced-batch image.

## Re-run

Follow the [benchmark guide](../../../guides/benchmark.md#repeated-measurement-of-all-implementations) to prepare the cluster and images and select the actual nodes. This report's image IDs and execution order are in [run.json](run.json). Results from a different environment should be interpreted separately from the conditions above.
