> Korean version: [한국어](prefill-decode-scheduler-KR.md)

# Token Budget Scheduler Verification

Adding `--scheduler token-budget` to the existing PD workers handles multiple requests' decodes and chunked prefills in one model forward. The default is the existing `serial`. It keeps the MPS 2-way and 4-way manifests, image tags, and namespaces.

[GPU validation results](../reports/gpu/pd/scheduler-20261002/analysis.md) record a 1,920-request comparison and TTFT differences with TPOT SLOs applied.

## Scheduling rules

Based on the [schedule in vLLM V1 v0.30.0](https://github.com/vllm-project/vllm/blob/ced6857afa0ea7b2e3f0846a62e1394e90f15607/vllm/v1/core/sched/scheduler.py#L561-L865). The implementation is in [scheduler.py](../../src/transformer/pd/scheduler.py) and [packed.py](../../src/transformer/pd/packed.py).

1. Each step selects RUNNING requests in arrival order. An in-progress decode usually uses 1 token, and a partial prefill uses part of the remaining prompt.
2. While remaining token budget, running request count, and KV reservation allow, admits WAITING requests in FIFO order.
3. Computes all selected request tokens in one forward. Separates KV by per-request positions and causal attention masks.
4. Returns execution slots and KV reservations of completed or cancelled requests, and admits new requests at the next step.

An in-progress partial prefill is also RUNNING, so this is not a rule where every decode outranks every prefill. In P1D3, P transfers the full-prompt KV, and D recomputes 1 last prompt token to produce the first output. TTFT includes KV transfer and D admission wait.

## Running

Prepare the cluster and model from the [MPS 4-way guide](prefill-decode-4.md). The new configuration also uses all 4 GPU shares, so it cannot run alongside existing PD workers on the same physical GPU.

```sh
DEVICE=gpu IMAGE_TAG=token-budget-v1 ./scripts/build-inference-images.sh transformers-pd
DEVICE=gpu IMAGE_TAG=token-budget-v1 GPU_SHARING=mps MPS_REPLICAS=4 \
  ./scripts/load-inference-images.sh transformers-pd

PD_SCHEDULER=token-budget PD_TOKEN_BUDGET=256 MPS_REPLICAS=4 \
  ./scripts/deploy-pd.sh aggregated
# Switches A4 to P1D3 in the same namespace.
PD_SCHEDULER=token-budget PD_TOKEN_BUDGET=256 MPS_REPLICAS=4 \
  ./scripts/deploy-pd.sh disaggregated

python3 scripts/benchmark-pd.py --mps-replicas 4 --scheduler token-budget \
  --token-budget 32 --config config/benchmarks/pd-scheduled.json
python3 scripts/benchmark-pd.py --mps-replicas 4 --scheduler token-budget \
  --token-budget 256 --config config/benchmarks/pd-scheduled.json
python3 scripts/report-pd.py <report-directory>
python3 scripts/report-pd-goodput.py <report-directory> --tpot-ms 25,30,35,40,50,75
```

Manifests are in `k8s/pd/profiles/mps-4-scheduled-*.yaml`, and the namespace is `pd-comparison-4-scheduled`. To select a separate cluster, use `CLUSTER_NAME` for deployment and `--cluster` for benchmark. Benchmark switches deployments and validates identical payloads and input/output lengths. It does not automatically delete workers after tests.

| Worker option | Default | Behavior |
| --- | ---: | --- |
| `--max-num-batched-tokens` | 256 | Cap on total query tokens in one forward |
| `--max-num-seqs` | 8 | Cap on RUNNING requests per worker |
| `--max-kv-tokens` | 8192 | Reservation cap on total KV length of RUNNING requests |
| `--long-prefill-token-threshold` | 0 | Per-request chunk cap, budget-only when 0 |
| `--scheduler-trace` | Off | Logs per-step prefill/decode tokens, request counts, and timings |

The additional manifest enables trace and sets HTTP admission to 32. It keeps router transfer concurrency 2, state size cap 64 MiB, and memory cap 1 GiB. It applies the same token budget to all A4 and P1D3 workers. These are not separately tuned results for P and D.

## Interpretation scope and verification

This implementation is a Transformers runtime for studying scheduling order and token budget effects. It does not implement vLLM PagedAttention, CUDA graphs, asynchronous scheduling, prefix caching, or KV preemption. It has dense attention masks plus per-step KV combine and split costs, so do not interpret measured throughput as vLLM performance. KV reserves each request's prompt plus maximum output length in advance, and new requests wait when the reservation limit is reached.

TTFT is the time to the first text chunk. It differs from first GPU token generation time because of the TextStreamer word buffer. Per-request TPOT is `(total latency - TTFT) / (output tokens - 1)` and does not replace the per-token ITL distribution.

```sh
python3 -m unittest discover -s tests -p 'test_pd*py'
```

Tests check attention isolation across different-length requests, logits and KV agreement with isolated runs, continuous-batch generation results, KV transfer that recomputes only the last prompt token, cancellation, admission, and bad state recovery. The step-log `pd_scheduler` JSON shows token budget compliance and mixed prefill/decode forwards.
