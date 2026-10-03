> Korean version: [한국어](vllm-source-analysis-KR.md)

# How Prefill/Decode Separation Affects TTFT in vLLM

In vLLM, Prefill/Decode separation can improve TTFT and TTFT goodput. If decode token-budget usage and running-request capacity make prefill wait, a prefill-only instance can reduce that wait. Client TTFT improvement must still be judged including KV transfer and decode-entry costs. The existing Transformers-based results alone cannot predict vLLM superiority.

Analysis baseline is the [vLLM v0.30.0 release](https://github.com/vllm-project/vllm/releases/tag/v0.30.0) checked on 2026-10-02, commit `ced6857afa0ea7b2e3f0846a62e1394e90f15607`. Read the V1 default scheduler and NIXL example proxy. This is not a vLLM deployment or GPU performance measurement.

## Scheduling Order Found in Source

[Scheduler.schedule](https://github.com/vllm-project/vllm/blob/ced6857afa0ea7b2e3f0846a62e1394e90f15607/vllm/v1/core/sched/scheduler.py#L561-L665) sets the per-step token budget and iterates `self.running` first. For each request it computes not-yet-computed tokens and caps them by remaining budget. It then proceeds to [post-budget WAITING handling](https://github.com/vllm-project/vllm/blob/ced6857afa0ea7b2e3f0846a62e1394e90f15607/vllm/v1/core/sched/scheduler.py#L801-L865), and [new-request prefill is also capped by remaining budget](https://github.com/vllm-project/vllm/blob/ced6857afa0ea7b2e3f0846a62e1394e90f15607/vllm/v1/core/sched/scheduler.py#L1035-L1080).

The understanding that new prefills are placed in remaining budget while preserving running decodes is therefore correct. V1 does not, however, separate prefill and decode into distinct phase queues. In-progress chunked prefills also enter RUNNING. There is no guarantee that all decodes always run before every partial prefill. The [upstream project test](https://github.com/vllm-project/vllm/blob/ced6857afa0ea7b2e3f0846a62e1394e90f15607/tests/v1/core/test_scheduler.py#L537-L588) also shows partial prefills and decodes remaining in RUNNING together. The test source was reviewed; the test was not run.

[AsyncScheduler](https://github.com/vllm-project/vllm/blob/ced6857afa0ea7b2e3f0846a62e1394e90f15607/vllm/v1/core/sched/async_scheduler.py#L12-L31) also inherits this Scheduler and does not replace the default `schedule()` order. Additional conditions such as speculative decoding, pipeline parallelism, and prefill throttling can change the simple 1-token-decode model.

## Three Limits to Distinguish

| Limit | Meaning in Source | Effect on Prefill Wait |
| --- | --- | --- |
| Token budget | `max_num_batched_tokens`, `max_num_scheduled_tokens` | Serves running requests, then admits prefill chunks for remaining tokens |
| Running request count | `max_num_seqs` | When RUNNING capacity is full, new requests are refused even with token budget left |
| KV cache space | `allocate_slots()` | Without enough KV blocks, new requests cannot enter |

Based on [configuration definitions](https://github.com/vllm-project/vllm/blob/ced6857afa0ea7b2e3f0846a62e1394e90f15607/vllm/config/scheduler.py#L49-L72), [request-count limit](https://github.com/vllm-project/vllm/blob/ced6857afa0ea7b2e3f0846a62e1394e90f15607/vllm/v1/core/sched/scheduler.py#L858-L865), and [full-input-length check in KV allocation](https://github.com/vllm-project/vllm/blob/ced6857afa0ea7b2e3f0846a62e1394e90f15607/vllm/v1/core/kv_cache_manager.py#L508-L524). Here a slot is not the same as a physical GPU count or GPU execution time unit.

For example, assuming no speculative decoding or in-progress partial prefills, token budget 512, 128 decode requests, and sufficient running-request capacity and KV space, decodes consume 1 token each and up to 384 tokens can then be assigned to new prefills. A prefill-only instance can avoid that 128-token deduction. This illustrates assigned token counts, not an actual TTFT improvement rate. Per-token compute cost differs between prefill and decode.

## Conditions Where Separation Can Improve TTFT

The following is inferred from source behavior.

- In Aggregation, sustained decode load delays admission of new requests or progress of prefill chunks.
- To protect ITL, aggregation's token budget must stay small. After separation, P can allow large prefill batches while D uses decode-tuned settings.
- P capacity covers incoming input-token volume, and D has room to accept KVs and start first outputs.
- Reduced wait and prefill time exceed exposed KV transfer and extra proxy processing costs.

The [vLLM tuning documentation](https://github.com/vllm-project/vllm/blob/ced6857afa0ea7b2e3f0846a62e1394e90f15607/docs/configuration/optimization.md#L49-L67) also describes small token budgets favoring ITL and large token budgets favoring TTFT. The [separation feature documentation](https://github.com/vllm-project/vllm/blob/ced6857afa0ea7b2e3f0846a62e1394e90f15607/docs/features/disagg_prefill.md#L8-L16) includes separately tuning TTFT and ITL among its goals. The comparison baseline should therefore be the TTFT/ITL combinations each mode achieves under the same resource and load budgets, not one particular configuration of one side.

## Prefill Completion Time vs Client TTFT

The [NIXL test proxy](https://github.com/vllm-project/vllm/blob/ced6857afa0ea7b2e3f0846a62e1394e90f15607/tests/v1/kv_connector/nixl_integration/toy_proxy_server.py#L155-L197) requests P with `max_tokens=1` and `stream=False`. [Follow-up handling](https://github.com/vllm-project/vllm/blob/ced6857afa0ea7b2e3f0846a62e1394e90f15607/tests/v1/kv_connector/nixl_integration/toy_proxy_server.py#L219-L251) passes P-response KV transfer info to D and streams the D response to the client. It does not forward P-generated tokens to the client immediately.

A simplified time model for this proxy path is as follows. Overlapping intervals are not double-counted.

```text
Aggregation TTFT ≈ A wait + prefill elapsed time in mixed batch + response forwarding
Disaggregation TTFT ≈ P wait and prefill + exposed delay of KV transfer path
                      + D entry and first-output generation + proxy/response forwarding
```

The [KV connector execution path](https://github.com/vllm-project/vllm/blob/ced6857afa0ea7b2e3f0846a62e1394e90f15607/vllm/v1/worker/kv_connector_model_runner_mixin.py#L76-L103) notifies the scheduler when async KV receive completes. The corresponding D request waits in `WAITING_FOR_REMOTE_KVS` until then. [Receive completion handling](https://github.com/vllm-project/vllm/blob/ced6857afa0ea7b2e3f0846a62e1394e90f15607/vllm/v1/core/sched/scheduler.py#L2951-L2977) returns the request to WAITING, and even with all prompt KVs matched there is a path recomputing the last prompt token for next-token sampling. KV arrival alone does not deliver the first output to the client.

If a different proxy forwards P's first token first, the TTFT boundary changes. In that case KV handoff delay can appear between the first and second tokens, so actual token intervals must be measured together.

## What Changes from the Existing Benchmark

The current [server](../../../../../src/huggingface/llama/inference_distributed/server.py) runs GPU work with `ThreadPoolExecutor(max_workers=1)`, and the [decode loop](../../../../../src/huggingface/llama/inference_distributed/engine.py) keeps running until one request's generation finishes. It uses per-request batch 1 and does not mix multiple requests per step like vLLM. Existing TTFT gaps therefore include request-level serial wait, worker count, and HTTP state-transfer path effects; they do not measure vLLM chunked-prefill token-budget contention.

Switching to vLLM lets both A and D batch requests continuously, so existing numbers cannot be carried over. In particular, a new prefill does not wait for a decode request's full output completion merely because decode requests exist.

The current load is concurrency up to 8 with actual input up to 734 tokens. For example, with budget 2,048 and at most 8 decodes, pure decode consumes about 8 tokens per step, so token-budget reduction from a decode-first policy alone is unlikely to explain a large TTFT gap. Whether concurrent prefill arrivals, running-request-count limits, KV shortage, or actual mixed-batch execution time dominates must be checked separately. The general GPU API server defaults for v0.30.0 are under [EngineArgs](https://github.com/vllm-project/vllm/blob/ced6857afa0ea7b2e3f0846a62e1394e90f15607/vllm/engine/arg_utils.py#L2750-L2759), but real experiments must state values explicitly and record run configuration.

Also, the current MPS 25% active-thread limit is not the same as 4 dedicated GPUs. Per the [NVIDIA MPS explanation](https://docs.nvidia.com/deploy/mps/when-to-use-mps.html#dynamic-execution-resource-provisioning), the limit is a per-client usage cap and does not reserve dedicated resources. Splitting P/D into separate processes does not fully remove physical-GPU resource interference. Input-load concentration on one P and 3-D processing capacity must be evaluated together.

## Items to Verify in a vLLM Comparison Experiment

While keeping the existing A4 vs P1D3 resource budget, comparing the following together can separate hypotheses.

1. Vary A's token budget across values and tune P and D budgets separately for D. Example search values are 256, 512, 1,024, 2,048, within executable memory range. Do not conclude from one configuration that disadvantages one side.
2. Record `max_num_seqs`, actual KV cache size, prefix-cache hit ratio, and speculative decoding settings. Compare under the same SLOs and total resource budget.
3. Alongside the current load, measure loads where long inputs arrive while decodes continue. Apart from fixed concurrency, increase request counts at the same arrival rate to observe queueing effects.
4. Collect client TTFT, per-request average TPOT, per-token intervals, P completion, KV receive completion, and D first-output times separately.
5. Compute TTFT-only, TPOT-only, and joint-intersection goodput and report attainment together. Judge improvement by client-basis goodput.

vLLM's own [metrics calculation](https://github.com/vllm-project/vllm/blob/ced6857afa0ea7b2e3f0846a62e1394e90f15607/vllm/v1/metrics/stats.py#L460-L504) records first-output delay and subsequent output intervals separately. [prefill_time](https://github.com/vllm-project/vllm/blob/ced6857afa0ea7b2e3f0846a62e1394e90f15607/vllm/v1/metrics/stats.py#L540-L560) is elapsed time from first SCHEDULED to first token, which differs from pure GPU prefill compute time. D-instance TTFT is also measured from D-entry time, so do not use it as a substitute for client TTFT including P and proxy.
