> Korean version: [한국어](summary-KR.md)

# AIPerf CPU benchmark

- Image: `local/llama-enhanced-cache:0.1.0`
- Image ID: `sha256:0bf4b86be3de5000cb50eb88d18752978a95525f7291a2f46a9c7370e2a55f3f`
- Started (UTC): 2026-09-20T09:00:17.970694+00:00
- Status: complete
- PVC cache policy: `clear-per-concurrency` (clear before each condition's warmup).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 94.50 | 106.83 | 443.73 | 8.22 | 10.67 | 335.71 | 579.02 | 13251.99 | 442.54 |
| 2 | 100.00 | 95.50 | 548.55 | 1855.91 | 7.89 | 9.53 | 325.96 | 583.93 | 449.14 | 874.50 |
| 4 | 100.00 | 96.44 | 1400.32 | 3388.12 | 7.83 | 9.40 | 323.22 | 543.32 | 140.38 | 1723.54 |
| 8 | 100.00 | 97.35 | 3039.13 | 6970.53 | 7.87 | 9.41 | 319.83 | 535.43 | 60.79 | 3358.96 |

Full AIPerf exports, request CSV, resource JSONL/CSV, and logs are saved locally under each `c<concurrency>/` directory; per-request data, resource time series, and logs are excluded from Git.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.

## Run conditions

This is the command that runs the same cache policy under the current image name. The image and ID at measurement time are recorded above.

```sh
make benchmark VARIANT=enhanced-cache-llamacpp CACHE_POLICY=clear-per-concurrency INFERENCE_CONTEXT=
```

With `INFERENCE_CONTEXT=`, the existing inference image was reused. Each of concurrency 1, 2, 4, 8 ran 2 warmup and 100 measured requests; all 400 measured requests succeeded with no short or over-length outputs. The 4 inference Pods have distinct UIDs and Guaranteed QoS.

Input/output distribution, 16 datasets, seed 42, warmup, request count, and CPU and memory settings are the same as the previous run. Inference Pods use 12 CPU and 16 GiB, AIPerf uses 1 CPU and 1 GiB, with requests equal to limits.

## PVC cache clear verification

Before each condition's warmup, the inference Pod termination and cache flush were awaited, then `/cache` contents were deleted. The PVC was retained. Deletion records are in each `c*/cache-clear.json` and `run.json`.

| Concurrency | Deleted files | Deleted size (MiB) | Entries after delete |
| --- | ---: | ---: | ---: |
| 1 | 1 | 0.00 | 0 |
| 2 | 19 | 32.85 | 0 |
| 4 | 19 | 32.85 | 0 |
| 8 | 19 | 32.85 | 0 |

The first condition only deleted the empty lock file of the new PVC. Later conditions deleted the cache saved by the previous step. The cache refills and is reused within warmup and measurement, so this is not an experiment that makes every request a cache miss.

## Comparison with previous cache-preserved run

Values compared against the [previous result](../bench-20260919-172027-036026-local-llama-enhanced-cache-0.1.0/summary.md). Change rate is `(current / previous - 1) × 100`.

| Concurrency | Preserved output tok/s | Cleared output tok/s | Throughput change | Preserved TTFT avg (ms) | Cleared TTFT avg (ms) |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 103.21 | 94.50 | -8.4% | 106.21 | 106.83 |
| 2 | 138.85 | 95.50 | -31.2% | 311.44 | 548.55 |
| 4 | 144.59 | 96.44 | -33.3% | 865.25 | 1400.32 |
| 8 | 142.90 | 97.35 | -31.9% | 1985.35 | 3039.13 |

In this run, throughput at concurrency 2, 4, 8 was about 31–33% lower than before, with higher mean TTFT. Note the previous run used 1 node while this run used 4 nodes with existing availability/HPA workloads also deployed. These inference Pods were placed on `local-k8s-worker` and AIPerf on `local-k8s-worker2`. They share 15 CPUs and about 24 GiB on the same Docker VM, so more nodes do not add physical resources.

The inference image ID is the same as before. AIPerf was rebuilt with the same 0.12.0 version and same Dockerfile source hash, so its image ID differs. Each run was executed once, so the difference above cannot be attributed solely to PVC cache clearing.

- Previous AIPerf image ID: `sha256:903ad977cf6f8ca82d18fc978436414fd1d7434a26ec87f2bab7dbcdf18c36fc`
- Current AIPerf image ID: `sha256:e916ca4e164739cd9a0d334faf73ea02dbb5f98aa77000ead84ab50ac7df8371`
