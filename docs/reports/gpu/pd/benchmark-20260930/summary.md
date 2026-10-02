> Korean version: [한국어](summary-KR.md)

# Aggregation vs Prefill/Decode Disaggregation Performance Comparison

**Comparison of the full workload from 1 completed repetition out of 3 planned repetitions.** Additional repetitions were interrupted, and failed repetitions are excluded from performance aggregation. [Raw run status](summary.json) is preserved as failed.

SmolLM2-135M-Instruct, FP16, GPU: `NVIDIA GeForce RTX 2060 SUPER, GPU-7b77b97b-2222-89f1-2d5e-5c488faedd7b, 580.126.09, 8192 MiB`.

Measured requests included in aggregation are 2,560, with 0 errors among them. 10 input/output combinations, concurrency [1, 2, 4, 8], 1 repetition, with 32 requests measured per condition per repetition.

Disaggregation average throughput is higher than aggregation in 6 of 40 conditions. This is a result for two MPS shares of a single GPU and HTTP state transfer through CPU memory.

The disaggregation / aggregation throughput ratio at concurrency 8 ranges from 0.53x to 0.57x.

![Throughput ratio](figures/throughput-ratio.png)

## Concurrency 8 Comparison

A is aggregation, D is disaggregation. Input lengths are synthetic-text settings; actual usage is shown separately in the table.

| Input/Output | Actual Avg Input | A tok/s | D tok/s | D Change | A TTFT ms | D TTFT ms | A p95 Latency ms | D p95 Latency ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 64/16 | 94.0 | 65.98 | 36.95 | -44.0% | 1342.9 | 2718.3 | 2065.2 | 3459.5 |
| 64/64 | 94.0 | 66.87 | 35.83 | -46.4% | 5014.4 | 10995.1 | 8475.9 | 14334.7 |
| 64/256 | 94.0 | 67.12 | 35.69 | -46.8% | 19750.2 | 44010.4 | 33585.9 | 57584.1 |
| 256/16 | 286.0 | 66.16 | 36.04 | -45.5% | 1329.1 | 2789.5 | 2132.9 | 3552.8 |
| 256/64 | 286.0 | 66.86 | 35.57 | -46.8% | 5009.2 | 11082.1 | 8441.7 | 14488.1 |
| 256/256 | 286.0 | 66.84 | 35.43 | -47.0% | 19820.1 | 44346.6 | 33719.5 | 57932.4 |
| 704/16 | 734.0 | 60.49 | 34.34 | -43.2% | 1502.9 | 2950.1 | 2307.1 | 3710.2 |
| 704/64 | 734.0 | 65.57 | 35.16 | -46.4% | 5167.6 | 11236.8 | 8643.0 | 14576.5 |
| 704/256 | 734.0 | 66.46 | 35.25 | -47.0% | 20002.1 | 44594.9 | 33858.0 | 58250.2 |
| mixed | 374.0 | 63.19 | 35.50 | -43.8% | 11985.3 | 26299.7 | 23937.0 | 44158.5 |

![Throughput and TTFT](figures/throughput-ttft.png)

## Measurement Conditions

- Aggregation: 2 full inference workers. Disaggregation: 1 Prefill worker and 1 Decode worker.
- Each worker uses 1 MPS share, CPU request 1 and limit 2, 2 GiB memory. Both modes use the same CPU router.
- Splits one physical GPU into 2 MPS shares with a 50% per-client active thread limit.
- Greedy decoding, EOS suppression, batch 1 per request, prefix cache and continuous batching disabled.
- Measured all combinations of synthetic inputs [64, 256, 704] and outputs [16, 64, 256]. Mixed distribution is `64,256:50;704,16:50`.
- Used AIPerf 0.12.0, seed 42, 32 datasets, sequential sampling.
- In mixed load, measured per-repetition request counts by actual input/output are 18 requests of 94/256 tokens and 14 of 734/16 tokens. Configured probabilities and actual shares of the finite dataset can differ.
- Excluded 4 warmup requests per condition from statistics. Deployment, model loading, and AIPerf startup time are also excluded from throughput.
- Per-repetition mode order is A→D. Verified that request payload hashes and actual input/output length request counts match between modes.
- If output length differs from the requested value or a request errors, that run is not stored as a successful result.

## Metrics and Interpretation Scope

Throughput, average latency, average TTFT, and ITL are arithmetic means of per-repetition AIPerf metrics. With 1 measurement, run-to-run variability is not estimated. p95 latency and p95 TTFT use nearest-rank over all repeated requests in the same condition. Samples are 32 per mode per condition; more samples are needed for precise estimation of long-tail latency.

TTFT is time until the first text chunk arrives and includes queueing, tokenization, and HTTP transfer. Because of the TextStreamer word buffer, it can differ from first GPU token generation time. ITL is the AIPerf streaming metric.

The disaggregated path copies GPU KV cache to CPU, then sends it over the Prefill→Router→Decode HTTP path. Decode does not recompute the prompt. First-token selection also runs on the Decode worker, so TTFT includes Decode queueing. Aggregation's two workers each decode, while the disaggregated setup has one decode worker. Interpret long-output throughput, transfer cost, and high-concurrency latency under these conditions.

Do not generalize to RDMA, NVLink or CUDA IPC transfer, continuous batching, large models, or multi-physical-GPU performance.

## Raw Data and Reproduction

Values are in [aggregation CSV](completed-summary.csv), [per-condition A/D comparison](comparison.csv), [aggregation configuration and verification JSON](completed-summary.json), and [worker phase diagnostics](phase-diagnostics.json). Phase diagnostics are worker-log averages including warmup, separate from AIPerf measurement statistics.

Per-request AIPerf exports, payloads, GPU samples, and Pod logs are kept in `reports/pd/benchmark-20260930` in storage. Raw paths are excluded from Git.

```sh
make pd-benchmark
python3 scripts/report-pd.py docs/reports/gpu/pd/benchmark-20260930 --completed-only
```

For setup and configuration, see the [PD comparison guide](../../../../guides/prefill-decode.md).

GPU output equivalence, MPS actual configuration, and existing environment restoration checks are in [environment validation results](environment-validation.json).

For interruption causes and post-fix verification, see the [stability analysis](stability.md).

For causes of throughput and latency differences, see the [performance cause analysis](analysis.md).
