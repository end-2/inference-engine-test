> Korean version: [한국어](analysis-KR.md)

# Token Budget Scheduler Verification

Added RUNNING-first continuous batching and chunked prefill and compared A4 vs P1D3 on a real GPU. Verified P1D3 TTFT improvement under conditions where the prefill budget can be set large while keeping the TPOT SLO.

Across 20 same-token-budget comparisons, P1D3 average TTFT was lower in 0 conditions. The basis for configuration selection matters.

Measured 1,920 requests, 0 errors, 0 worker restarts, 0 router OOMs. Preserved the existing MPS configuration and reports and restored the original GPU environment.

## Representative Case: Comparison Protecting a TPOT Ceiling

Synthetic input 704 tokens (actual prompt 734 tokens), output 16 tokens, concurrency 16. As an example goal, selected configurations so per-request average TPOT of 40 ms or less passes at 95%+ in every repetition. Each row samples 48 requests and attainment below sums both repetitions.

| Configuration | Budget | TTFT ms | Avg TPOT ms | TPOT Attainment | Min Per-Repetition Attainment | Goodput req/s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A4 | 32 | 2464.0 | 32.0 | 100.0% | 100.0% | 4.097 |
| A4 | 256 | 451.9 | 42.3 | 45.8% | 45.8% | 5.652 |
| P1D3 | 32 | 8476.5 | 26.7 | 100.0% | 100.0% | 1.256 |
| P1D3 | 256 | 1581.7 | 34.0 | 97.9% | 95.8% | 5.672 |

Comparing goal-passing A4 budget 32 with P1D3 budget 256, average TTFT **falls 35.8% from 2,464.0 to 1,581.7 ms**, and TPOT-only goodput **rises 38.4% from 4.097 to 5.672 req/s**. P1D3 passed 24/24 in the first repetition and 23/24 in the second. A4 budget 256 has shorter TTFT but fails the selection criterion with 45.8% TPOT attainment.

Relaxing the TPOT ceiling to 75 ms passes all A4 budget 256 requests too, with TTFT 451.9 ms — lower than P1D3. TTFT advantage depends on workload and latency goals.

## Cause Interpretation

A4 puts large prefill chunks and decode in the same forward pass. In the representative case, raising budget from 32 to 256 shortens TTFT but raises average TPOT from 32.0 to 42.3 ms. In P1D3, enlarging P chunks still runs D in separate forwards, so average TPOT after the same change is 34.0 ms, mostly meeting the 40 ms goal. Physical GPU execution resources remain shared because of MPS, however.

In P step logs, forwards handling the same 220,480 prefill tokens fell from 6,950 to 1,087. This aggregation includes the full workload and warmup. Same-budget TTFT comparisons show the difference between 4 A prefill-processing workers vs 1 P1D3 P worker, plus HTTP KV transfer and transfer admission wait burden.

In A mixed steps, decode's share of total token budget averaged 6.1% (budget 32) and 0.84% (budget 256). Reading these logs and metrics together, this benefit is best interpreted as the effect of setting large P chunks while protecting the TPOT goal. It does not mean the same outcome on other workloads.

Router transfer concurrency stayed at 2. P concurrent running requests in logs were also at most 2, so this experiment includes that backpressure effect. [Budget 32 phase metrics](../scheduler-20261002-b32/phase-diagnostics.json) and [Budget 256 phase metrics](../scheduler-20261002-b256/phase-diagnostics.json) are diagnostics summing multiple concurrencies and mixed requests of the same I/O lengths; they are not direct time decompositions of the representative-case TTFT above.

![TTFT and TPOT](ttft-tpot.png)

## Concurrency 16 Comparison

A is 4 Aggregation workers, D is 1 Prefill plus 3 Decode workers. Applied the same token budget to all workers. Input lengths are synthetic input settings.

| Budget | Input/Output | A TTFT ms | D TTFT ms | D TTFT Change | A TPOT ms | D TPOT ms | A tok/s | D tok/s |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 32 | i64-o16 | 356.5 | 1145.1 | +221.2% | 35.5 | 30.8 | 226.6 | 120.6 |
| 32 | i64-o128 | 350.6 | 813.6 | +132.1% | 39.3 | 41.4 | 291.5 | 267.0 |
| 32 | i704-o16 | 2464.0 | 8476.5 | +244.0% | 32.0 | 26.7 | 65.6 | 20.1 |
| 32 | i704-o128 | 1950.1 | 7701.3 | +294.9% | 40.5 | 34.4 | 233.4 | 128.4 |
| 32 | mixed | 856.4 | 2762.9 | +222.6% | 39.4 | 37.2 | 221.9 | 171.4 |
| 256 | i64-o16 | 169.7 | 410.8 | +142.0% | 35.7 | 39.2 | 276.4 | 207.1 |
| 256 | i64-o128 | 170.1 | 421.3 | +147.6% | 39.6 | 42.4 | 301.4 | 276.6 |
| 256 | i704-o16 | 451.9 | 1581.7 | +250.0% | 42.3 | 34.0 | 197.3 | 92.7 |
| 256 | i704-o128 | 465.8 | 1177.8 | +152.9% | 42.2 | 45.7 | 276.0 | 235.1 |
| 256 | mixed | 229.6 | 648.1 | +182.2% | 41.0 | 43.3 | 288.8 | 245.5 |

## TTFT of Configurations Protecting the Same TPOT SLO

At concurrency 16, kept only budgets among each mode's two budgets whose TPOT attainment is 95%+ in every repetition, and selected the budget with the lowest average TTFT. Searched ceilings were 25, 30, 35, 40, 50, and 75 ms. This is a limited post-data configuration comparison, not a general optimum search.

[Configuration selection results for all workloads and SLOs](tpot-constrained-ttft.csv) record TTFT, throughput, and minimum per-repetition attainment. Blanks mean no satisfying configuration.

| Input/Output | TPOT Ceiling ms | A Budget | A TTFT ms | D Budget | D TTFT ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| i64-o16 | 35 | - | - | 32 | 1145.1 |
| i64-o16 | 40 | - | - | 32 | 1145.1 |
| i64-o16 | 50 | 256 | 169.7 | 256 | 410.8 |
| i64-o128 | 35 | - | - | - | - |
| i64-o128 | 40 | - | - | - | - |
| i64-o128 | 50 | 256 | 170.1 | 256 | 421.3 |
| i704-o16 | 35 | - | - | 32 | 8476.5 |
| i704-o16 | 40 | 32 | 2464.0 | 256 | 1581.7 |
| i704-o16 | 50 | 32 | 2464.0 | 256 | 1581.7 |
| i704-o128 | 35 | - | - | - | - |
| i704-o128 | 40 | - | - | 32 | 7701.3 |
| i704-o128 | 50 | 256 | 465.8 | 32 | 7701.3 |
| mixed | 35 | - | - | - | - |
| mixed | 40 | - | - | - | - |
| mixed | 50 | 256 | 229.6 | 256 | 648.1 |

## Measurement Conditions and Limits

- SmolLM2-135M-Instruct, FP16, RTX 2060 SUPER 8 GiB, 4 MPS clients. Per-client active thread limit 25%, memory limit 2 GiB. Not dedicated SM partitioning.
- Used input 64 and 704, output 16 and 128 combinations and `64,128:50;704,16:50` mixed load. Concurrency 4 and 16.
- Measured 24 requests after 4 warmups per condition, repeated twice. Repetition order is A→D and D→A. 1,920 measured plus 320 warmup requests total.
- Applied greedy decoding, EOS suppression, max_num_seqs 8, and KV token reservation cap 8,192. No per-P/D budget tuning.
- Results are arithmetic means of per-repetition averages. p95, run-to-run SD, and payload/token-length agreement are in the per-budget reports. With 48 samples per condition per mode, do not treat small gaps as definitive advantages.
- A fixed-concurrency test processing a finite request count. Not a service-capacity verification holding fixed arrival rates over time.
- TTFT is until the first text chunk and includes tokenizer, queue, KV transfer, and TextStreamer buffering. TPOT is per-request `(latency - TTFT) / (output tokens - 1)`. Not a per-token ITL tail-latency measurement.
- Uses dense block masks with packed SDPA and per-step KV copies. Does not include vLLM PagedAttention, CUDA graphs, async scheduler, or preemption. Do not interpret these results as actual vLLM performance.

## Implementation and Verification

Kept the default serial mode and added a [separate scheduler manifest](../../../../../k8s/inference-distributed/profiles/mps-4-scheduled-aggregated.yaml). Behavior and reproduction commands are in the [scheduler guide](../../../../guides/prefill-decode-scheduler.md).

54 CPU tests and 13 cluster tests passed. On a real GPU, 16-token greedy outputs for 64, 94, 286, and 734-token inputs matched the existing serial path for both budgets. Decode results after 734-token KV transfer also matched. [GPU validation](gpu-validation.json) records image source hashes and CUDA version.

Router memory peak was 88.5 MiB with a 1 GiB limit. Kept [environment validation](validation.json), [MPS verification](mps.json), and [restoration verification](restoration.json).

Verified token budget, max_num_seqs, and per-role token kinds in step logs. Computed prefill and decode token sums also match completed request lengths. [Scheduler log aggregation](scheduler-diagnostics.json) includes warmup.

## Raw Data and Further Comparisons

- [Budget 32 results](../scheduler-20261002-b32/summary.md), [TTFT and TPOT goodput](../scheduler-20261002-b32/goodput/separate.md)
- [Budget 256 results](../scheduler-20261002-b256/summary.md), [TTFT and TPOT goodput](../scheduler-20261002-b256/goodput/separate.md)
- [All-condition CSV](comparison.csv), [figure PDF](ttft-tpot.pdf)
- Raw data: `reports/pd/scheduler-20261002-b32/` and `reports/pd/scheduler-20261002-b256/`. Keeps per-request metrics, payloads, GPU samples, and Pod logs.
