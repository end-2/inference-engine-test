> Korean version: [한국어](summary-KR.md)

# Per-unique-input cache-clear performance

For 32 and 128 unique inputs, ran one sweep each that clears the PVC cache before measuring concurrency 1, 2, 4, 8. All 800 measured and 16 warmup requests succeeded. There were no short outputs, and 24 requests used more than the target.

## Measurement conditions

- Run date: 2026-09-20 UTC (2026-09-21 Korea time). [Run timestamps and image IDs](run.json).
- Image `local/llama-enhanced-cache:0.1.0`, model Qwen2.5-0.5B-Instruct Q4_K_M.
- Inference Pod 12 CPU and 16 GiB, AIPerf Pod 1 CPU and 1 GiB. Requests and limits set equal.
- RAM cache 64 MiB, disk cache 1,024 MiB, minimum prefix 32 tokens.
- Before each concurrency, terminated the inference Pod, waited for the shutdown flush, then deleted all cache files on the dedicated PVC. Verified the empty PVC, then started a new inference Pod, which also reset RAM.
- Ran 2 warmup then 100 measured requests. Within each step the cache can fill and be reused.
- Input/output targets 64/32 and 256/64 tokens, 50% each, seed 42, sequential inputs, streaming, `ignore_eos=true`.
- No separate client load was generated; existing monitoring services were running.

## Cleared-condition measurement results

| Unique input setting | Concurrency | Successful requests | Output tok/s | TTFT mean (ms) | TTFT p95 (ms) | ITL mean (ms) | ITL p95 (ms) | Over-length outputs |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 32 | 1 | 100 | 78.39 | 233.11 | 1081.72 | 7.73 | 9.36 | 0 |
| 32 | 2 | 100 | 76.99 | 831.36 | 2143.77 | 7.85 | 9.30 | 0 |
| 32 | 4 | 100 | 77.90 | 1987.64 | 5002.72 | 7.74 | 8.98 | 0 |
| 32 | 8 | 100 | 78.90 | 4215.94 | 8715.84 | 7.61 | 8.84 | 0 |
| 128 | 1 | 100 | 42.86 | 724.70 | 1108.21 | 7.92 | 9.44 | 6 |
| 128 | 2 | 100 | 43.07 | 1795.22 | 2728.23 | 7.87 | 9.28 | 6 |
| 128 | 4 | 100 | 43.13 | 3914.44 | 5254.54 | 7.92 | 9.10 | 6 |
| 128 | 8 | 100 | 43.18 | 8088.31 | 10487.41 | 7.92 | 9.50 | 6 |

## Comparison with cache-preserved condition

The [cache-preserved result](../benchmark-cache-datasets-20260920-145858/summary.md) started from an empty cache only before the Job and retained the same Pod's RAM and PVC between concurrency steps. Each value below is a single measurement; input-set checksums were confirmed equal across the two runs.

| Unique input setting | Concurrency | Preserved output tok/s | Cleared output tok/s | Preserved TTFT mean (ms) | Cleared TTFT mean (ms) |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 32 | 1 | 77.47 | 78.39 | 235.62 | 233.11 |
| 32 | 2 | 124.14 | 76.99 | 380.01 | 831.36 |
| 32 | 4 | 120.55 | 77.90 | 1138.91 | 1987.64 |
| 32 | 8 | 129.69 | 78.90 | 2404.92 | 4215.94 |
| 128 | 1 | 43.29 | 42.86 | 721.20 | 724.70 |
| 128 | 2 | 128.05 | 43.07 | 374.73 | 1795.22 |
| 128 | 4 | 126.34 | 43.13 | 1105.90 | 3914.44 |
| 128 | 8 | 127.22 | 43.18 | 2499.61 | 8088.31 |

The first concurrency starts from an empty cache in both conditions. At later concurrency steps the cleared condition cannot reuse the previous step's cache. RAM retention and Pod lifetime also differ from the preserved condition, so this is not isolated to a PVC-only effect. These are single measurements, so small differences should not be generalized.

The 32-input configuration repeats 32 inputs across 100 measured requests, and the 128-input configuration uses 100 unique inputs per step. Actual input/target-output 93/32 and 285/64 request counts are 57/43 and 54/46 respectively, matching the preserved condition.

## Output length and validation records

- 128 unique inputs, concurrency 1: six 65-token outputs against the 64-token target.
- 128 unique inputs, concurrency 2: six 65-token outputs against the 64-token target.
- 128 unique inputs, concurrency 4: six 65-token outputs against the 64-token target.
- 128 unique inputs, concurrency 8: six 65-token outputs against the 64-token target.

Throughput uses the server-reported usage as-is. Over-length outputs are recorded separately from request errors, and the affected conditions are not treated as fully passing fixed-output-length validation. [32-input validation](entries-32/run.json) and [128-input validation](entries-128/run.json) store the PVC deletion results, input checksums, and mismatched request IDs.

The summary is in [CSV](summary.csv); each concurrency's AIPerf summary is in `entries-*/c*/artifacts/profile_export_aiperf.json`. Run manifests and Pod records are in each concurrency folder.
