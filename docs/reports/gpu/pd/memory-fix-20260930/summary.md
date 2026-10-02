> Korean version: [한국어](summary-KR.md)

# Aggregation vs Prefill/Decode Disaggregation Performance Comparison

SmolLM2-135M-Instruct, FP16, GPU: `NVIDIA GeForce RTX 2060 SUPER, GPU-7b77b97b-2222-89f1-2d5e-5c488faedd7b, 580.126.09, 8192 MiB`.

Measured requests included in aggregation are 160, with 0 errors among them. 5 input/output combinations, concurrency [1, 8], 1 repetition, with 8 requests measured per condition per repetition.

Disaggregation average throughput is higher than aggregation in 3 of 10 conditions. This is a result for two MPS shares of a single GPU and HTTP state transfer through CPU memory.

The disaggregation / aggregation throughput ratio at concurrency 8 ranges from 0.53x to 0.68x.

![Throughput ratio](figures/throughput-ratio.png)

## Concurrency 8 Comparison

A is aggregation, D is disaggregation. Input lengths are synthetic-text settings; actual usage is shown separately in the table.

| Input/Output | Actual Avg Input | A tok/s | D tok/s | D Change | A TTFT ms | D TTFT ms | A p95 Latency ms | D p95 Latency ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 64/16 | 94.0 | 66.57 | 36.71 | -44.8% | 814.5 | 1644.9 | 1917.7 | 3477.9 |
| 64/256 | 94.0 | 67.29 | 35.93 | -46.6% | 11275.5 | 25115.5 | 30428.4 | 56988.1 |
| 704/16 | 734.0 | 60.45 | 32.50 | -46.2% | 944.6 | 2001.7 | 2112.1 | 3920.7 |
| 704/256 | 734.0 | 66.77 | 35.26 | -47.2% | 11435.2 | 25724.2 | 30666.3 | 58056.6 |
| mixed | 254.0 | 51.90 | 35.49 | -31.6% | 7858.3 | 17846.2 | 30205.7 | 44169.7 |

![Throughput and TTFT](figures/throughput-ttft.png)

## Measurement Conditions

- Aggregation: 2 full inference workers. Disaggregation: 1 Prefill worker and 1 Decode worker.
- Each worker uses 1 MPS share, CPU request 1 and limit 2, 2 GiB memory. Both modes use the same CPU router.
- Splits one physical GPU into 2 MPS shares with a 50% per-client active thread limit.
- Greedy decoding, EOS suppression, batch 1 per request, prefix cache and continuous batching disabled.
- Measured all combinations of synthetic inputs [64, 704] and outputs [16, 256]. Mixed distribution is `64,256:50;704,16:50`.
- Used AIPerf 0.12.0, seed 42, 8 datasets, sequential sampling.
- In mixed load, measured per-repetition request counts by actual input/output are 6 requests of 94/256 tokens and 2 of 734/16 tokens. Configured probabilities and actual shares of the finite dataset can differ.
- Excluded 2 warmup requests per condition from statistics. Deployment, model loading, and AIPerf startup time are also excluded from throughput.
- Per-repetition mode order is A→D. Verified that request payload hashes and actual input/output length request counts match between modes.
- If output length differs from the requested value or a request errors, that run is not stored as a successful result.

## Metrics and Interpretation Scope

Throughput, average latency, average TTFT, and ITL are arithmetic means of per-repetition AIPerf metrics. With 1 measurement, run-to-run variability is not estimated. p95 latency and p95 TTFT use nearest-rank over all repeated requests in the same condition. Samples are 8 per mode per condition; more samples are needed for precise estimation of long-tail latency.

TTFT is time until the first text chunk arrives and includes queueing, tokenization, and HTTP transfer. Because of the TextStreamer word buffer, it can differ from first GPU token generation time. ITL is the AIPerf streaming metric.

The disaggregated path copies GPU KV cache to CPU, then sends it over the Prefill→Router→Decode HTTP path. Decode does not recompute the prompt. First-token selection also runs on the Decode worker, so TTFT includes Decode queueing. Aggregation's two workers each decode, while the disaggregated setup has one decode worker. Interpret long-output throughput, transfer cost, and high-concurrency latency under these conditions.

Do not generalize to RDMA, NVLink or CUDA IPC transfer, continuous batching, large models, or multi-physical-GPU performance.

## Raw Data and Reproduction

Values are in [aggregation CSV](summary.csv), [per-condition A/D comparison](comparison.csv), [aggregation configuration and verification JSON](summary.json), and [worker phase diagnostics](phase-diagnostics.json). Phase diagnostics are worker-log averages including warmup, separate from AIPerf measurement statistics.

Per-request AIPerf exports, payloads, GPU samples, and Pod logs are kept in `reports/pd/memory-fix-20260930` in storage. Raw paths are excluded from Git.

```sh
make pd-benchmark
python3 scripts/report-pd.py docs/reports/gpu/pd/memory-fix-20260930
```

For setup and configuration, see the [PD comparison guide](../../../../guides/prefill-decode.md).

GPU output equivalence, MPS actual configuration, and existing environment restoration checks are in [environment validation results](environment-validation.json).
