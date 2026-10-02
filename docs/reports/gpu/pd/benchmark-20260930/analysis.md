> Korean version: [한국어](analysis-KR.md)

# Why Disaggregation Throughput Is Lower

In this configuration, reducing Decode workers from 2 to 1 has a larger effect than the benefit of overlapping Prefill and Decode. State-transfer cost adds further overhead. The second repetition interrupted by OOM is excluded from the [performance aggregation](summary.md), so do not interpret the gap below as throughput lowered by failed requests.

## Decode Capacity and Stage Imbalance

Aggregation uses two workers that each run Prefill and Decode. Disaggregation uses 1 Prefill worker and 1 Decode worker, and each worker processes one request at a time with batch 1. Total resources are the same — 2 MPS shares of one physical GPU — but the number of workers performing Decode concurrently differs.

Averages from [worker phase records](phase-diagnostics.json) are as follows. Inputs are actual token counts including the chat template. Values sum records across concurrencies, and 94/256 and 734/16 also include mixed-load requests of the same lengths.

| Actual Input/Output | Prefill ms | Decode ms | Decode / Prefill | State Size MiB |
| --- | ---: | ---: | ---: | ---: |
| 94/16 | 32.7 | 426.4 | 13.0 | 2.26 |
| 94/256 | 33.1 | 7,185.8 | 217.2 | 2.26 |
| 734/16 | 80.7 | 438.9 | 5.4 | 16.33 |
| 734/256 | 93.3 | 7,221.3 | 77.4 | 16.33 |

Even with the longest input and shortest output, Decode takes 5.4x longer than Prefill. For input 734 and output 256, Prefill is about 1.3% of the combined compute time. The Prefill time that can be hidden by overlap is therefore small, and a single Decode worker remains the bottleneck.

One Decode worker generating 256 tokens in about 7.22 seconds delivers about 35.5 tok/s. At actual concurrency 8, Disaggregation reaches 35.25 tok/s, close to that limit. Aggregation generates with two workers and records 66.46 tok/s. The D/A throughput ratio at concurrency 8 across all 10 workloads is 0.53–0.57.

The per-MPS-client active thread limit was 50%. This is not two independent GPUs nor a split guaranteeing exactly half the compute performance. Even when the Prefill client is idle, the Decode client's configured active thread limit does not automatically become 100%. This even split therefore does not match the per-role compute share of the current load. For limit behavior, see the [NVIDIA MPS documentation](https://docs.nvidia.com/deploy/mps/when-to-use-mps.html).

## Queueing Inflates TTFT

The first output token is also selected by the Decode worker. The next request cannot receive its first token until the previous request's long Decode finishes.

| Synthetic Input/Output, Concurrency | A tok/s | D tok/s | A TTFT ms | D TTFT ms |
| --- | ---: | ---: | ---: | ---: |
| 64/16, 1 | 33.64 | 33.30 | 89.3 | 104.2 |
| 704/16, 1 | 31.01 | 26.67 | 136.8 | 230.6 |
| 704/256, 8 | 66.46 | 35.25 | 20,002.1 | 44,594.9 |
| mixed, 8 | 63.19 | 35.50 | 11,985.3 | 26,299.7 |

Averaging 128 Disaggregation worker logs for actual input 734 and output 256 across concurrency 1, 2, 4, and 8 gives 30.6 ms Prefill wait and 17,808.9 ms Decode wait. Aggregation worker wait for the same conditions was 6,764.5 ms. In Aggregation, all pre-inference wait is recorded as `prefill_queue_ms`. These averages are diagnostic values showing where wait accumulates, not values to add directly to the TTFT of a specific concurrency.

## Added Cost of KV State Transfer

State is copied from Prefill GPU to CPU, then sent over HTTP through Prefill→Router→Decode before being copied back to GPU. For actual 734-token input, about 16.33 MiB per request traverses two HTTP hops. Logged export takes about 31 ms and import about 9 ms. For 94-token input, they were about 3.4 ms and 4.5 ms respectively.

At concurrency 1 and output 16, the TTFT increase of the disaggregated setup is about 15 ms for short input and about 94 ms for long input. This matches a path with added serialization and transfer, but the full difference cannot be treated as pure network time. `prefill_rpc_ms` includes overlapping wait, tokenization, Prefill, and export, so do not sum it with individual stages.

## Separating OOM from Performance Interpretation

Before the fix, the Router retained KV bodies in HTTP request metadata and exceeded the 1 GiB limit on the second repetition. Causes and before/after verification are recorded in the [stability analysis](stability.md). The main performance table uses only 2,560 requests from the first repetition, completed without errors.

Current code limits on concurrent transfers and strengthened failure/cancellation paths are recorded separately in [Router memory verification](../router-memory-20261001/summary.md).

In a separate GPU check after the existing body-lifetime fix, input 704, output 256, and concurrency 8 gave A 66.77 and D 35.26 tok/s. That check had 160 total requests with no errors or Pod restarts. Fixing the OOM therefore leaves the Decode bottleneck of the current role placement unchanged. Request counts and code differ, so pre- and post-fix data are not combined into the same repetition statistics.

## Conditions to Change in the Next Comparison

Current results were measured with SmolLM2-135M, maximum actual input 734 tokens, batch 1, and no continuous batching or prefix cache. Do not generalize to optimized disaggregated serving with larger models, longer contexts, or multiple physical GPUs. Only one repetition completed the full workload, so reproducibility of small differences is not yet confirmed.

The next experiment should change one condition at a time to isolate effects.

1. Add Decode batching or change the per-role resource ratio to secure Decode capacity. A Decode share larger than the current 50% limit cannot be raised with Pod environment variables alone; MPS control settings and the equal-total-resource comparison condition must change together.
2. After verifying context limits and KV memory, add loads with a large enough Prefill share by increasing input length. Even the current 704/16 is Decode-heavy in compute-time terms.
3. Measure state-transfer improvements as a separate experiment. The current ~47% throughput loss on long outputs is unlikely to be recovered by serialization optimization alone.

After strengthening Router memory limits, the same full matrix must complete at least 3 times for re-verification. Memory stress checks do not replace this performance repetition measurement.
