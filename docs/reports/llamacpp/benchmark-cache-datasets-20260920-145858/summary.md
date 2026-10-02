> Korean version: [한국어](summary-KR.md)

# Cache performance with 32 and 128 unique inputs

Ran one AIPerf Job each on enhanced-cache with only the unique input count changed to 32 and 128. Each Job measured concurrency 1, 2, 4, 8 in order; all 800 measured and 16 warmup requests succeeded. There were no short outputs, but 24 requests in the 128-input configuration used 1–2 tokens more than the 64-token target.

## Measurement conditions

- Run date: 2026-09-20 UTC (2026-09-21 Korea time). [Timestamps and image IDs](run.json).
- Inference image `local/llama-enhanced-cache:0.1.0`, model Qwen2.5-0.5B-Instruct Q4_K_M.
- 1 inference Pod with 12 CPU and 16 GiB. AIPerf Pod with 1 CPU and 1 GiB. Both measurement Pods use Guaranteed QoS.
- Input/output targets are 64/32 and 256/64 tokens, 50% each, seed 42, sequential inputs.
- 2 warmup and 100 measured requests per concurrency, `ignore_eos=true`, streaming. The same input set is reused within the same Job.
- Before each Job the inference Pod was restarted fresh with an independent empty cache path. RAM 64 MiB, disk 1,024 MiB, minimum prefix 32 tokens. The Pod and RAM/disk caches were retained between concurrency steps.
- No separate client load was generated; existing monitoring services were running.

## Measurement results

Each row is a single measurement. TTFT and ITL show mean and p95 together.

| Unique input setting | Concurrency | Successful requests | Output tok/s | TTFT mean (ms) | TTFT p95 (ms) | ITL mean (ms) | ITL p95 (ms) | Mean request latency (ms) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 32 | 1 | 100 | 77.47 | 235.62 | 1097.43 | 7.93 | 9.56 | 589.69 |
| 32 | 2 | 100 | 124.14 | 380.01 | 577.37 | 7.90 | 9.52 | 733.90 |
| 32 | 4 | 100 | 120.55 | 1138.91 | 1530.82 | 8.13 | 9.63 | 1503.06 |
| 32 | 8 | 100 | 129.69 | 2404.92 | 2996.88 | 7.52 | 8.79 | 2742.87 |
| 128 | 1 | 100 | 43.29 | 721.20 | 1096.00 | 7.73 | 9.03 | 1077.25 |
| 128 | 2 | 100 | 128.05 | 374.73 | 581.02 | 7.62 | 8.85 | 724.35 |
| 128 | 4 | 100 | 126.34 | 1105.90 | 1587.18 | 7.65 | 8.96 | 1459.36 |
| 128 | 8 | 100 | 127.22 | 2499.61 | 3071.33 | 7.64 | 8.91 | 2851.77 |

## Actual input composition

The generated datasets had 32 and 128 distinct inputs respectively. Measurement uses 100 requests per step, so the 128-input configuration used only 100 unique inputs per step. The per-concurrency input-set checksums were identical within each Job.

| Input setting | Unique inputs used per concurrency | Actual input / target output tokens | Requests per concurrency |
| ---: | ---: | --- | ---: |
| 32 | 32 | 93/32 | 57 |
| 32 | 32 | 285/64 | 43 |
| 128 | 100 | 93/32 | 54 |
| 128 | 100 | 285/64 | 46 |

### Output length mismatch

| Input setting | Concurrency | Over-target requests | Reported output tokens |
| ---: | --- | ---: | --- |
| 32 | 1, 2, 4, 8 | 0 each | Match target |
| 128 | 1 | 6 | 65 tokens, 6 requests |
| 128 | 2, 4, 8 | 6 each | 65 tokens × 5, 66 tokens × 1 per step |

All over-length requests had a 64-token output target. Throughput keeps the original AIPerf measurement based on the server's `usage.completion_tokens`. The 128-input configuration did not fully pass fixed-output-length validation, so interpret it separately from request success.

The current server counts sampled token IDs when reporting usage. The run image's llama-cpp-python code has a path that generates the next token before the output-limit check when handling incomplete UTF-8 bytes. This is a possible cause of the observed excess, but per-request token flow was not collected, so it is not confirmed as the direct cause. Mismatched request IDs and reported lengths are stored in each input configuration's `run.json`.

The 32-input configuration repeats inputs within a measurement. The 128-input configuration uses 100 unique inputs within a step but resends the same inputs at the next concurrency, so cache reuse can occur. Actual length ratios and cache state differ, so the difference cannot be attributed solely to the unique input count.

Each condition was run once, and cache hit counts or per-layer restore times were not measured. The earlier 3-repetition experiment with 16 inputs restarted the inference Pod per concurrency, so its conditions differ from these results.

[Comparison with per-concurrency PVC and RAM clearing](../benchmark-cache-datasets-clear-20260920-151923/summary.md) summarizes the cleared condition measured with the same input sets.

## Stored results

- [Summary CSV](summary.csv), [32-input validation](entries-32/run.json), [128-input validation](entries-128/run.json).
- Each `entries-*/c*/artifacts/` stores the AIPerf summary JSON and console output.
- Job manifests and Pod records retain node placement, image, and resource settings.
