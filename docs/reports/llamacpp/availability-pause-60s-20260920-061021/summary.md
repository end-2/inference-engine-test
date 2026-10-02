> Korean version: [한국어](summary-KR.md)

# Engine node freeze (pause), NoExecute toleration 60s

## 1. Experiment summary

Injected a freeze (pause) fault into one engine node. The Service ready endpoint decrease was observed **54.0s** after the fault, and a replacement Pod on a surviving node became Ready at **118.8s**. Replacement Pod creation to Ready took **6s**.

The AIPerf result over the fixed observation window is **155 successes, 7 errors (4.32%)**. A replacement replica was secured before node recovery, and no automatic redistribution appeared during the post-recovery observation period.

## 2. Experiment environment

| Item | Condition |
| --- | --- |
| Observation window | 2026-09-20 06:11:58.791–06:19:41.980 UTC (KST=UTC+9) |
| Cluster | kind `local-k8s`, Kubernetes v1.36.4, 1 control-plane + 3 workers |
| Placement | 1 monitor worker with AIPerf, Prometheus, Grafana, kube-state-metrics; 2 engine workers with 1 inference Pod each |
| Inference | `local/llama-base-metric:0.1.0`, model `Qwen/Qwen2.5-0.5B-Instruct`, 2 replicas, 2 CPU / 2Gi per Pod, 2 threads |
| Load | `local/aiperf:0.12.0`, concurrency 4, streaming, new connection per request, 30s timeout, input/output distribution `64,32:50;256,64:50` |
| Toleration | Pod `not-ready` and `unreachable`, both `NoExecute`, `tolerationSeconds: 60` |
| Scheduling and termination | hostname preferred pod anti-affinity, `terminationGracePeriodSeconds: 60` |
| Fault target | `local-k8s-worker2` |
| Collection interval | Kubernetes objects and Docker state ~2s, Prometheus 5s, kubelet resources ~10s; Docker events, timestamped logs |

CPU and memory requests and limits were equal. The inference image and model were prepared on the engine nodes.

The fault was injected with `docker pause`, and during the fault the Docker state was `Running=true, Paused=true`.

## 3. Observations

### Rescheduling timeline

Relative times are measured from `docker pause` completion. Condition and object timestamps are in seconds, and "observed" timestamps include delays from the object collection interval.

| UTC time | After fault | Observation |
| --- | ---: | --- |
| 06:14:29.195 | 0.0s | Docker pause complete: node process frozen |
| 06:14:52.692 | 23.5s | First client error |
| 06:15:22.000 | 52.8s | Node Ready=Unknown (kubectl: NotReady) |
| 06:15:22.000 | 52.8s | unreachable:NoExecute taint recorded |
| 06:15:23.218 | 54.0s | Faulted endpoint ready=false, Service ready 2→1 observed |
| 06:15:47.694 | 78.5s | Last client error |
| 06:16:22.000 | 112.8s | Replacement Pod created on surviving engine node |
| 06:16:28.000 | 118.8s | Replacement Pod Ready=True |
| 06:16:28.826 | 119.6s | Service ready endpoint 1→2 observed |
| 06:17:59.591 | 210.4s | Node recovery command complete |
| 06:18:02.992 | 213.8s | Existing faulted Pod API object deletion observed |
| 06:18:11.121 | 221.9s | Faulted node Ready recovery observed |
| 06:19:41.980 | 312.8s | Observation end |

The interval from NoExecute taint record to controller delete request was about 60.7s. A new Pod was created while the existing faulted Pod remained Terminating, and the existing object was cleaned up after node recovery.

### Pod changes and Kubernetes state

| Category | Pod name | Normal | During fault | After node return |
| --- | --- | --- | --- | --- |
| A: faulted | `llama-base-metric-7c6d46685b-xqtm8` | local-k8s-worker2, Ready | Ready=False → Terminating | Deleted |
| B: surviving | `llama-base-metric-7c6d46685b-2kn9h` | local-k8s-worker3, Ready | Kept serving | Stayed on same node |
| C: replacement | `llama-base-metric-7c6d46685b-dtgkg` | None | Newly created on local-k8s-worker3, then Ready | Stayed on same node |

Replacement Pod C has UID `8d5454cc-9103-4417-8462-d2077d45d64b`. Pod C was newly created on the surviving node.

### Client impact

Successes are grouped by AIPerf request completion time and errors by ERROR log time. Latency and TTFT are distributions over successful requests only, and the failure-rate denominator is the sum of successful completions and errors within each window.

| Window | Length | Success / Error | Failure rate | Success req/s | Latency p50 / p95 | TTFT p50 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Normal | 150.4s | 58 / 0 | 0.00% | 0.386 | 11.28 / 17.59s | 9.51s |
| Fault→Node NotReady | 52.8s | 7 / 4 | 36.36% | 0.133 | 9.13 / 11.28s | 7.47s |
| NotReady→replacement Pod Ready | 66.0s | 14 / 3 | 17.65% | 0.212 | 13.20 / 22.09s | 11.98s |
| Replacement Pod Ready→node recovery command | 91.6s | 33 / 0 | 0.00% | 0.360 | 11.70 / 22.15s | 10.77s |
| Node recovery command→observation end | 102.4s | 43 / 0 | 0.00% | 0.420 | 9.32 / 14.37s | 8.44s |

| Error type (full AIPerf run) | Count |
| --- | ---: |
| `TimeoutError` | 7 |

The full AIPerf run had 186 successes and 7 errors, covering warmup and shutdown handling, so its scope differs from the fixed observation window. The maximum gap between successful response completions was **18.79s**.

The graph below aligns this experiment's per-request AIPerf results, error logs, Prometheus EndpointSlice, and kubelet CPU on the same time axis. Blue dots are successful request latency, orange dots are successful request TTFT, and the x-axis is seconds from fault injection. Red × marks actual error log times, and **the marker height of 32 is not a latency value**. CPU has duplicate cached samples removed.

![AIPerf request latency, TTFT, error times with EndpointSlice and CPU](figures/observed-timeline.png)

### Representative logs

Excerpted errors, eviction, and replacement server startup, excluding repeated probe and scrape logs. Long error messages are shortened.

```text
06:14:52.692  AIPerf      TimeoutError()
06:15:47.694  AIPerf      TimeoutError()
06:16:22.730  Controller  "Deleting pod" controller="taint-eviction-controller" [Pod A]
06:16:23.897  Server C    Application startup complete.
06:16:33.372  Server C    "POST /v1/chat/completions HTTP/1.1" 200 OK
```

## 4. Interpretation

**The replacement Pod took 118.8s to become Ready.** Node Ready turned Unknown 52.8s after the fault, and the controller delete request took about 60.7s after the NoExecute taint record. Replacement Pod creation to Ready took 6s.

**Request errors occurred even while 1 ready endpoint remained.** 7 errors were recorded in the fixed observation window, and there were 0 errors from replacement Pod Ready until the end of observation.

Successful throughput in the NotReady→replacement Pod Ready window fell 45.0% versus normal, from 0.386 to 0.212 req/s. Median TTFT went from 9.51 to 11.98s.

**Two replicas were secured on the surviving node before node recovery.** The replacement Pod was placed on `local-k8s-worker3`, and the surviving Pod and replacement Pod stayed on the same node after the faulted node returned. No automatic redistribution appeared during the post-return observation period.
