> Korean version: [한국어](analysis-KR.md)

# 4-Way Split Performance Comparison Interpretation

In the current SmolLM2-135M FP16 configuration, Aggregation average throughput was higher in 39 of 40 conditions. Disaggregation was higher only for 64/256 at concurrency 2, with A 68.91 ± 0.16 and D 69.05 ± 0.98 tok/s — a 0.2% gap. This small gap is not sufficient to claim a performance benefit for the disaggregated setup. ± values are sample SDs across 3 repetitions.

At concurrency 1 and 2, long-output throughput is similar, and the gap widens at concurrency 4 and 8. For 256-token output at concurrency 8, the D/A throughput ratio is 0.756–0.760. This matches the difference that Aggregation uses 4 workers each performing Decode while Disaggregation uses 3 Decode workers.

In [phase records](phase-diagnostics.json), actual input 734 and output 256 tokens average 138.6 ms Prefill and 7,457.8 ms Decode. Prefill is about 1.8% of combined compute time. The Prefill time available for overlapped execution is small, so it did not offset fewer Decode workers and transfer cost. This diagnostic value is a worker-log average summed over concurrency 1, 2, 4, and 8 and three repetitions.

At concurrency 8 and 704/256, client-average TTFT is A 7.18 s and D 11.39 s, and p95 request latency is 16.54 s and 23.81 s respectively. The first output token is also selected by the Decode worker, so queueing ahead of long generations is included in TTFT. In D logs for that actual token length, average Decode wait summed over all concurrencies is 3,278.7 ms, larger than 20.5 ms Prefill wait and 38.3 ms router transfer-slot wait. Do not sum these averages directly into the TTFT of a specific concurrency.

Long inputs also show state-transfer cost. Actual 734-token input state is about 16.33 MiB, exported from GPU to CPU, passed through two HTTP hops, then loaded back to GPU. The output-256-token group averages 32.0 ms export and 10.7 ms import. At concurrency 1 and 704/16, TTFT rises from A 191.3 ms to D 288.4 ms. This gap includes tokenization, serialization, and per-server handling in addition to transfer. `prefill_rpc_ms` overlaps some stages, so do not add it to per-stage times.

Mixed load had different per-worker generated token counts even with equal request counts. Per-repetition throughput at concurrency 8 is as follows.

| Repetition | A tok/s | D tok/s | D/A |
| --- | ---: | ---: | ---: |
| 1 | 101.35 | 91.16 | 0.90 |
| 2 | 102.96 | 89.39 | 0.87 |
| 3 | 117.26 | 87.89 | 0.75 |
| Mean ± SD | 107.19 ± 8.76 | 89.48 ± 1.64 | 0.83 |

The D/A in the last row is the ratio of 3-run average throughputs.

In [per-worker records](mixed-worker-load.csv), each A worker handled 8 measured requests, but the maximum number of 256-token-output requests was 6 in runs 1 and 2 and 5 in run 3. Round-robin spreads request counts but does not equalize generation work. Finite-load spread across 32 requests and completion wait for the last request appear to affect mixed throughput variation. More requests per condition per repetition are needed to estimate this variation and tail latency more precisely.

Per-worker mixed records extract the last condition of each deployment log — mixed load at concurrency 8. Excluding warmup with actual input 80 or 720 tokens, verified that 32 measured requests with 94- or 734-token inputs and per-length counts match AIPerf results.

All measured requests in this run succeeded with no router OOM or Pod restarts. Observed gaps are therefore not explained by failed requests or OOM recovery time. Results compare a single-GPU MPS 4-way split, per-request batch 1, and the current HTTP state-transfer path. Full numbers and measurement conditions are in the [results report](summary.md); environment preservation checks are in [run validation](validation.md).
