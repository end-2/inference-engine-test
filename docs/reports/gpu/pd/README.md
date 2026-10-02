> Korean version: [한국어](README-KR.md)
# GPU Prefill/Decode experiment summary

Results for running SmolLM2-135M-Instruct FP16 on a single RTX 2060 SUPER 8 GiB. Reports are separated by MPS slot count, worker role, and scheduler. A2 and A4 are full inference workers 2 and 4, while P1D1 and P1D3 are 1 Prefill worker with 1 and 3 Decode workers.

## Key results

| Comparison | Observed result | Interpretation scope |
| --- | --- | --- |
| Serial, A2 vs P1D1 | At concurrency 8, P1D1 throughput is 0.53-0.57x A2 | Only 1 of 3 planned repeats completed. Second repeat Router OOM stopped the full run |
| Serial, A4 vs P1D3 | A4 throughput higher in 39 of 40 conditions, with P1D3/A4 0.76-0.83x at concurrency 8 | 3 repeats completed. The one P1D3-higher condition differs by about 0.2%, smaller than repeat variation |
| Token budget, same-budget comparison | Mean TTFT lower for A4 in all 20 conditions at budgets 32 and 256 | 2 repeats per budget. No P1D3 TTFT advantage found when budget is fixed |
| Token budget, budget selected to meet TPOT target | At 704/16, concurrency 16, P1D3 mean TTFT down 35.8%, TPOT-only goodput up 38.4% | Conditional result from limited budget search. With TPOT cap relaxed to 75 ms, A4 budget 256 also passes and has lower TTFT. Selection criteria and full figures are in [scheduler analysis](scheduler-20261002/analysis.md) |

The last row is a conditional result from limited budget search. Under the same workload with TPOT cap relaxed to 75 ms, A4 budget 256 also passes and has lower TTFT. Selection criteria and full figures are in [scheduler analysis](scheduler-20261002/analysis.md).

Serial experiments include Decode worker count and HTTP KV transfer cost effects. For long inputs and long outputs in the 4-way split, worker logs show Prefill compute share around 1.8%, so separable compute overlap was small. This value is a diagnostic mean including multiple concurrency levels and warmup, not TTFT decomposition for a specific condition. See [4-way cause analysis](benchmark-four-20261001/analysis.md).

## Experiment list

Request counts are measured samples excluding warmup. Function checks and memory stress checks are not added to performance repeats.

| Report | Configuration and scope | Completed repeats, measured requests | Status and basis |
| --- | --- | --- | --- |
| [2-way performance](benchmark-20260930/summary.md) | Serial A2/P1D1, 10 length distributions, concurrency 1, 2, 4, 8 | 1/3 repeats, 2,560 requests | 0 errors in completed repeats. [Interruption and OOM analysis](benchmark-20260930/stability.md), source state is failed |
| [GPU check after text lifetime fix](memory-fix-20260930/summary.md) | Serial A2/P1D1, reduced workload | 1 repeat, 160 requests | 0 errors and Pod restarts. Not a full matrix remeasurement |
| [Router memory](router-memory-20261001/summary.md) | HTTP mock without GPU inference, concurrency 8, state about 16.33 and 64 MiB | 768 requests | cgroup max 258.5 MiB, 1 GiB cap, 0 OOMs and restarts |
| [4-way setup check](four-slot-check-20261001/validation.md) | Serial A4/P1D3, reduced workload and CUDA client check | 1 repeat, 64 requests | Request distribution, equal resource budget, and output length verified |
| [4-way performance](benchmark-four-20261001/summary.md) | Serial A4/P1D3, 10 length distributions, concurrency 1, 2, 4, 8 | 3 repeats, 7,680 requests | 0 errors, Router OOMs, and Pod restarts. [Execution verification](benchmark-four-20261001/validation.md) |
| [Budget 32](scheduler-20261002-b32/summary.md) | Token budget A4/P1D3, 5 length distributions, concurrency 4, 16 | 2 repeats, 960 requests | [Goodput by SLO](scheduler-20261002-b32/goodput/separate.md) |
| [Budget 256](scheduler-20261002-b256/summary.md) | Token budget A4/P1D3, 5 length distributions, concurrency 4, 16 | 2 repeats, 960 requests | [Goodput by SLO](scheduler-20261002-b256/goodput/separate.md) |

Across both budgets, 1,920 total requests had 0 errors, Router OOMs, and worker restarts. [Cross-budget comparison and GPU output verification](scheduler-20261002/analysis.md) reanalyzes those two runs and is not a separate measurement sample.

[vLLM source review](benchmark-four-20261001/vllm-source-analysis.md) is reference material reviewing the scheduler implementation. It contains no vLLM-measured performance results.

MPS model co-execution itself is in [separate verification](../mps-check-20260930/summary.md). All 48 generation requests succeeded across 6 model combinations, and this is not included in HTTP server performance comparison.

## Comparison conditions and caveats

- Serial uses input 64, 256, 704 and output 16, 64, 256 combinations plus mixed load. Scheduler uses input 64, 704 and output 16, 128 combinations plus different mixed load, so do not compare full-report averages across the two directly.
- Actual fixed-length inputs are 94, 286, 734 tokens including chat template. Per-length sample counts for mixed load are recorded in individual reports.
- Throughput and mean latency are arithmetic means across repeats, standard deviation is sample SD across repeats, and p95 is nearest-rank over pooled requests in the same condition. A single repeat has no across-repeat variation estimate.
- TTFT includes queue wait, tokenizer, HTTP path, and TextStreamer buffering. TPOT is `(total latency - TTFT) / (output tokens - 1)` per request and is not per-token tail latency.
- Distinguish TPOT-only goodput from goodput limiting both TTFT and TPOT. Select settings only after checking that every repeat pass rate exceeds the threshold.
- These are MPS sharing on one physical GPU, small model, and HTTP KV transfer through CPU results. Do not generalize them to separate physical GPUs, RDMA, NVLink, or actual vLLM performance.

## Execution and artifact preservation

See [2-way execution](../../../guides/prefill-decode.md), [4-way execution](../../../guides/prefill-decode-4.md), and [scheduler execution](../../../guides/prefill-decode-scheduler.md) for reproduction commands and requirements. Environment recovery records in older reports reflect state at measurement end.

Each run JSON preserves settings and source hashes, CSVs preserve aggregate figures, and Markdown plus figures preserve interpretation. Per-request sources and logs under `reports/pd/<run-name>/` are kept locally and excluded from Git. Without sources, a checkout can open reports but cannot re-aggregate request-level data or regenerate goodput. The [results organization guide](../../../guides/experiment-results.md) has preserved files and verification steps.
