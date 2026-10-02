> Korean version: [한국어](stability-KR.md)

# Measurement Interruption and Router Memory Verification

The [performance report](summary.md) aggregates only the first repetition that completed the full workload with pre-fix code. 2,560 requests succeeded across 40 conditions, 32 per mode per condition. The originally planned 3 repetitions were not completed.

## Cause of Interruption

On the second repetition, disaggregated, synthetic input 704 tokens, output 256 tokens, and concurrency 1, the router exceeded its 1 GiB memory limit. Actual input is 734 tokens. Kubernetes recorded `OOMKilled`, exit code 137, at 2026-09-30 18:55:46 UTC. Of 32 requests in that condition, 1 succeeded and 31 failed with connection termination or refusal. Prefill and Decode worker restart counts were 0.

The entire second repetition is excluded from the main performance aggregation. The original run failure status and errors are preserved in [summary.json](summary.json), and the completed repetition is recorded separately in [completed-summary.json](completed-summary.json). Pod status and memory inspection values are in [stability.json](stability.json).

## Memory Lifetime Fix

When the Router passes a `bytes` body to HTTPX, the request object tied to the response can retain the full KV data. While the request-metadata reference is held, the large body can be held with it. The Router now passes the body with an async iterator and explicit `Content-Length`, so transmitted data can be released once the iterator is exhausted. The Prefill→Router→Decode path, state format, GPU compute, and resource limits are unchanged.

A separate HTTP check transferred 17,120,000 bytes per request. Bundles of 32 requests each ran at concurrency 1, 2, 4, and 8, repeated 4 times. Verified transfer size and response completion for 512 total requests.

| Router | Max RSS Observed Just After Request Bundle Completion |
| --- | ---: |
| Before fix | 866.1 MiB |
| After fix | 148.2 MiB |

RSS is sampled from `/proc/<pid>/status` just after each request bundle. This is a check of large-HTTP-body lifetime without GPU inference, not the peak over every moment of execution.

A regression test retains 24 completed request metadata entries and checks whether each 1 MiB body accumulates. The old router fails and the fixed router passes. The runner periodically checks for inference Pod restarts, and on detection stops measurement while preserving current and previous container logs.

Pre- and post-fix performance data use different code, so they are not combined into one repetition statistic.

## Post-Fix GPU Verification

Reran input 64 and 704 tokens with output 16 and 256 tokens plus mixed load at concurrency 1 and 8. 8 requests per mode per condition, 160 total requests, all succeeded, and payloads and actual token distributions matched between modes. Two representative requests also matched GPU generation results and usage.

There were no inference Pod restarts. The disaggregated router cgroup `memory.peak` was 88.3 MiB with the 1 GiB memory limit retained. This value uses different measurement and load than the earlier CPU HTTP check. 22 tests including memory regression checks and benchmark aggregation checks also passed.

Details are in the [post-fix measurement report](../memory-fix-20260930/summary.md) and [memory, image, and execution environment verification](../memory-fix-20260930/environment-validation.json). After measurement, restored the existing Deployment configuration and Helm values; one `base-llamacpp` is Ready and GPU compute mode is `Default`.

## Concurrent Transfer and Failure-Path Limits

The current Router limits KV-state transfer slots to 2, with 64 KiB chunk uploads and explicit body release on failure and cancellation. Memory request is 512 MiB and limit is 1 GiB. 768 follow-up HTTP checks including up to 64 MiB states all succeeded with a cgroup memory peak of 258.5 MiB. This check is separate from GPU performance re-measurement, with configuration and measurement scope in the [follow-up verification report](../router-memory-20261001/summary.md).
