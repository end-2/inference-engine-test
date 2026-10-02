> Korean version: [한국어](summary-KR.md)

# Router Memory Limit Hardening Verification

Limited the lifetime of large Router KV bodies not only on normal completion but also on failure and cancellation, and limited concurrently created states to 2. 768 real HTTP requests all succeeded under Kubernetes' 1 GiB memory limit. Router cgroup memory peak was **258.5 MiB**, with **0** OOMs and container restarts.

## Applied Limits

| Setting | Value | Scope |
| --- | --- | --- |
| `MAX_PENDING` | 8 | Total requests accepted until streaming completes |
| `MAX_STATE_TRANSFERS` | 2 | From pre-Prefill request until Decode response header receipt |
| `MAX_STATE_MIB` | 64 | Per-request state size cap |
| Upload chunk | 64 KiB | Size handed to the HTTP transfer buffer at once |
| Router memory request / limit | 512 MiB / 1 GiB | Manifest shared by both modes |

Requests waiting for a slot have not yet run Prefill and therefore hold no KV state. Maximum concurrent raw-state size is 128 MiB, plus in-flight copies, HTTP buffers, and Python memory. Bodies and slots are released even when a transfer fails before starting or is cancelled after the first chunk. Slot waits return HTTP 504 after 120 seconds; over-capacity returns HTTP 429.

The new `state_queue_ms` metric records Router transfer-slot wait. It is separated so wait time is not mistaken for Prefill compute or Decode wait. Non-streaming requests can hold slots longer because Decode completes before response headers arrive.

## Real HTTP Stress Test

Ran a CPU Router with mock Prefill and Decode on a separate namespace of the existing kind GPU worker node. Mocks send states of the requested size and verify received bytes, and Decode reads the body with a small delay. No GPU model inference was run.

| State Size | Concurrency | Successful Requests | Errors | Elapsed s |
| --- | ---: | ---: | ---: | ---: |
| 17,120,000 bytes, about 16.33 MiB | 8 | 512 | 0 | 44.75 |
| 67,108,864 bytes, 64 MiB | 8 | 256 | 0 | 79.82 |

Both loads ran consecutively without Router restart. The memory peak is 271,007,744 bytes from that container's `/sys/fs/cgroup/memory.peak`, not periodic RSS samples. `max`, `oom`, and `oom_kill` in `memory.events` were all 0 with a 1,073,741,824-byte memory limit. These results verify the above configuration and load; they do not cover environments with larger state limits or more concurrent transfers.

The first check mounted the modified Router source via ConfigMap on the existing runtime image. Afterwards, built the modified inference image, loaded it on the kind worker, and verified normal 64 MiB request forwarding in a separate Pod without source mounts. Also verified that Router and worker source SHA-256 inside the image match the working directory.

## Regression Checks and Application Status

26 PD-related tests passed. Covered body release on normal responses, pre-transfer-start failures, partial-upload failures, cancellation, cancellation while waiting for slots, timeouts, state-size overruns, HTTP 429, and slot reuse. Existing small-Llama-model output equivalence and Prefill/Decode overlap checks also passed.

Aggregated and Disaggregated manifests passed Kubernetes server dry-run after rendering with the test namespace swapped in. Loaded the `local/transformers-pd-gpu:0.1.0` image on `local-k8s-gpu-worker`. Cleaned up the test namespace and temporary builder while keeping existing GPU services. To deploy a real PD inference configuration and adjust limits, follow the [comparison guide](../../../../guides/prefill-decode.md).

The full GPU performance matrix was not rerun with the modified code. The earlier [performance cause analysis](../benchmark-20260930/analysis.md) and [post-existing-body-lifetime-fix GPU check](../memory-fix-20260930/summary.md) remain results for the code at each measurement time.

[Verification JSON](validation.json) contains source hashes, image identifiers, cgroup metrics, and Pod status. Test manifests, mocks and load scripts, and logs are kept in `reports/pd/router-memory-20261001/` in storage. Raw paths are excluded from Git.
