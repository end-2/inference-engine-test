> Korean version: [한국어](summary-KR.md)

# Aggregation vs Prefill/Decode Disaggregation Performance Comparison

SmolLM2-135M-Instruct, FP16, GPU: `NVIDIA GeForce RTX 2060 SUPER, GPU-7b77b97b-2222-89f1-2d5e-5c488faedd7b, 580.126.09, 8192 MiB`.

Measured requests included in aggregation are 7,680, with 0 errors among them. 10 input/output combinations, concurrency [1, 2, 4, 8], 3 repetitions, with 32 requests measured per condition per repetition.

Disaggregation average throughput is higher than aggregation in 1 of 40 conditions. This is a result for 4 MPS shares of a single GPU and HTTP state transfer through CPU memory.

The disaggregation / aggregation throughput ratio at concurrency 8 ranges from 0.76x to 0.83x.

![Throughput ratio](figures/throughput-ratio.png)

## Concurrency 8 Comparison

A is aggregation, D is disaggregation. Input lengths are synthetic-text settings; actual usage is shown separately in the table.

| Input/Output | Actual Avg Input | A tok/s | D tok/s | D Change | A TTFT ms | D TTFT ms | A p95 Latency ms | D p95 Latency ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 64/16 | 94.0 | 123.92 | 94.72 | -23.6% | 531.3 | 794.8 | 1092.3 | 1615.0 |
| 64/64 | 94.0 | 129.66 | 98.27 | -24.2% | 1792.0 | 2823.8 | 4130.6 | 6074.5 |
| 64/256 | 94.0 | 129.44 | 98.41 | -24.0% | 6928.3 | 11119.3 | 16475.4 | 23598.8 |
| 256/16 | 286.0 | 122.98 | 94.08 | -23.5% | 539.6 | 801.9 | 1118.5 | 1569.1 |
| 256/64 | 286.0 | 127.50 | 96.57 | -24.3% | 1816.2 | 2877.1 | 4389.3 | 5983.0 |
| 256/256 | 286.0 | 128.69 | 97.27 | -24.4% | 6950.1 | 11205.1 | 16889.4 | 23873.9 |
| 704/16 | 734.0 | 100.30 | 83.12 | -17.1% | 767.5 | 960.2 | 1360.9 | 1866.1 |
| 704/64 | 734.0 | 120.95 | 94.06 | -22.2% | 2041.1 | 3013.7 | 4389.8 | 6125.6 |
| 704/256 | 734.0 | 127.05 | 96.32 | -24.2% | 7184.4 | 11394.0 | 16540.0 | 23809.7 |
| mixed | 374.0 | 107.19 | 89.48 | -16.5% | 4703.9 | 7200.2 | 15940.8 | 22680.7 |

![Throughput and TTFT](figures/throughput-ttft.png)

## Measurement Conditions

- Aggregation: 4 full inference workers. Disaggregation: 1 Prefill worker and 3 Decode workers.
- Each worker uses 1 MPS share, CPU request 1 and limit 2, 2 GiB memory. Both modes use the same CPU router.
- Splits one physical GPU into 4 MPS shares with a 25% per-client active thread limit.
- Greedy decoding, EOS suppression, batch 1 per request, prefix cache and continuous batching disabled.
- Measured all combinations of synthetic inputs [64, 256, 704] and outputs [16, 64, 256]. Mixed distribution is `64,256:50;704,16:50`.
- Used AIPerf 0.12.0, seed 42, 32 datasets, sequential sampling.
- In mixed load, measured per-repetition request counts by actual input/output are 18 requests of 94/256 tokens and 14 of 734/16 tokens. Configured probabilities and actual shares of the finite dataset can differ.
- Excluded 4 warmup requests per condition from statistics. Deployment, model loading, and AIPerf startup time are also excluded from throughput.
- Per-repetition mode order is A→D, D→A, A→D. Verified that request payload hashes and actual input/output length request counts match between modes.
- If output length differs from the requested value or a request errors, that run is not stored as a successful result.

## Metrics and Interpretation Scope

Throughput, average latency, average TTFT, and ITL are arithmetic means of per-repetition AIPerf metrics. Standard deviation is run-to-run sample SD. p95 latency and p95 TTFT use nearest-rank over all repeated requests in the same condition. Samples are 96 per mode per condition; more samples are needed for precise estimation of long-tail latency.

TTFT is time until the first text chunk arrives and includes queueing, tokenization, and HTTP transfer. Because of the TextStreamer word buffer, it can differ from first GPU token generation time. ITL is the AIPerf streaming metric.

The disaggregated path copies GPU KV cache to CPU, then sends it over the Prefill→Router→Decode HTTP path. Decode does not recompute the prompt. First-token selection also runs on the Decode worker, so TTFT includes Decode queueing. Aggregation's 4 workers each decode, while the disaggregated setup has 3 decode workers. Interpret long-output throughput, transfer cost, and high-concurrency latency under these conditions.

Do not generalize to RDMA, NVLink or CUDA IPC transfer, continuous batching, large models, or multi-physical-GPU performance.

## Raw Data and Reproduction

Values are in [aggregation CSV](summary.csv), [per-condition A/D comparison](comparison.csv), [aggregation configuration and verification JSON](summary.json), and [worker phase diagnostics](phase-diagnostics.json). Phase diagnostics are worker-log averages including warmup, separate from AIPerf measurement statistics.

Per-request AIPerf exports, payloads, GPU samples, and Pod logs are kept in `reports/pd/benchmark-four-20261001` in storage. Raw paths are excluded from Git.

```sh
python3 scripts/benchmark-pd.py --mps-replicas 4 --cluster local-k8s-gpu --config docs/reports/gpu/pd/benchmark-four-20261001/workload.json
python3 scripts/report-pd.py docs/reports/gpu/pd/benchmark-four-20261001
```

For setup and configuration, see the [PD comparison guide](../../../../guides/prefill-decode-4.md).

Execution environment and existing environment restoration checks are in [environment validation results](environment-validation.json).

For causes of throughput and latency differences, see the [performance cause analysis](analysis.md).

For deployment verification scope and existing environment preservation, see [configuration validation](validation.md).

For per-request TTFT and TPOT threshold results, see [Goodput comparison](goodput/summary.md).
