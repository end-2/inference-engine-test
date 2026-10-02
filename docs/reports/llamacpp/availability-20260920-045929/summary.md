> Korean version: [한국어](summary-KR.md)

# Engine node freeze (pause), NoExecute toleration 300s

## 1. Experiment summary

Injected a freeze (pause) fault into one engine node. The Service ready endpoint decrease was observed **45.1s** after the fault, and a replacement Pod on a surviving node became Ready at **349.8s**. Replacement Pod creation to Ready took **5s**.

The AIPerf result over the fixed observation window is **196 successes, 7 errors (3.45%)**. A replacement replica was secured before node recovery, and no automatic redistribution appeared during the post-recovery observation period.

## 2. Experiment environment

| Item | Condition |
| --- | --- |
| Observation window | 2026-09-20 04:59:29.798–05:11:10.660 UTC (KST=UTC+9) |
| Cluster | kind `local-k8s`, Kubernetes v1.36.4, 1 control-plane + 3 workers |
| Placement | 1 monitor worker with AIPerf, Prometheus, Grafana, kube-state-metrics; 2 engine workers with 1 inference Pod each |
| Inference | `local/llama-base-metric:0.1.0`, model `Qwen/Qwen2.5-0.5B-Instruct`, 2 replicas, 2 CPU / 2Gi per Pod, 2 threads |
| Load | `local/aiperf:0.12.0`, concurrency 4, streaming, new connection per request, 30s timeout, input/output distribution `64,32:50;256,64:50` |
| Toleration | Pod `not-ready` and `unreachable`, both `NoExecute`, `tolerationSeconds: 300` |
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
| 05:02:06.213 | 0.0s | Docker pause complete: node process frozen |
| 05:02:23.724 | 17.5s | First client timeout |
| 05:02:50.000 | 43.8s | Node Ready=Unknown (kubectl: NotReady) |
| 05:02:51.000 | 44.8s | unreachable:NoExecute taint recorded |
| 05:02:51.316 | 45.1s | Faulted endpoint ready=false, Service ready 2→1 observed |
| 05:03:18.731 | 72.5s | Last client timeout |
| 05:07:51.000 | 344.8s | Replacement Pod created on surviving engine node |
| 05:07:56.000 | 349.8s | Replacement Pod Ready=True |
| 05:07:57.857 | 351.6s | Service ready endpoint 1→2 observed |
| 05:09:28.153 | 441.9s | docker unpause complete |
| 05:09:31.893 | 445.7s | Existing faulted Pod API object deletion observed |
| 05:09:39.999 | 453.8s | Faulted node Ready recovery observed |
| 05:11:10.660 | 544.4s | Observation end |

The interval from NoExecute taint record to controller delete request was about 300.0s. A new Pod was created while the existing faulted Pod remained Terminating, and the existing object was cleaned up after node recovery.

### Pod changes and Kubernetes state

| Category | Pod name | Normal | During fault | After node return |
| --- | --- | --- | --- | --- |
| A: faulted | `llama-base-metric-779584f79b-c5n9v` | local-k8s-worker2, Ready | Ready=False → Terminating | Deleted |
| B: surviving | `llama-base-metric-779584f79b-cjdbd` | local-k8s-worker3, Ready | Kept serving | Stayed on same node |
| C: replacement | `llama-base-metric-779584f79b-smlkg` | None | Newly created on local-k8s-worker3, then Ready | Stayed on same node |

Replacement Pod C has UID `a60de0a2-9ba0-47bd-9fa9-23e9e3f61d95`. Pod C was newly created on the surviving node.

### Client impact

Successes are grouped by AIPerf request completion time and errors by ERROR log time. Latency and TTFT are distributions over successful requests only, and the failure-rate denominator is the sum of successful completions and errors within each window.

| Window | Length | Success / Error | Failure rate | Success req/s | Latency p50 / p95 | TTFT p50 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Normal | 156.4s | 52 / 0 | 0.00% | 0.332 | 13.95 / 21.94s | 12.42s |
| Fault→Node NotReady | 43.8s | 4 / 4 | 50.00% | 0.091 | 9.44 / 15.11s | 8.28s |
| NotReady→replacement Pod Ready | 306.0s | 67 / 3 | 4.29% | 0.219 | 16.94 / 21.97s | 16.13s |
| Replacement Pod Ready→node recovery command | 92.2s | 33 / 0 | 0.00% | 0.358 | 12.06 / 21.93s | 11.25s |
| Node recovery command→observation end | 102.5s | 40 / 0 | 0.00% | 0.390 | 8.62 / 17.27s | 7.78s |

| Error type (full AIPerf run) | Count |
| --- | ---: |
| `TimeoutError` | 7 |

The full AIPerf run had 245 successes and 7 errors, covering warmup and shutdown handling, so its scope differs from the fixed observation window. The maximum gap between successful response completions was **27.03s**.

The graph below aligns this experiment's per-request AIPerf results, error logs, Prometheus EndpointSlice, and kubelet CPU on the same time axis. Blue dots are successful request latency, orange dots are successful request TTFT, and the x-axis is seconds from fault injection. Red × marks actual error log times, and **the marker height of 32 is not a latency value**. CPU has duplicate cached samples removed.

![AIPerf request latency, TTFT, error times with EndpointSlice and CPU](figures/observed-timeline.png)

### Representative logs

Excerpted errors, eviction, and replacement server startup, excluding repeated probe and scrape logs. Long error messages are shortened.

```text
05:02:23.724  AIPerf      TimeoutError()
05:03:18.731  AIPerf      TimeoutError()
05:07:51.043  Controller  "Deleting pod" controller="taint-eviction-controller" [Pod A]
05:07:52.172  Server C    Application startup complete.
05:07:59.428  Server C    "POST /v1/chat/completions HTTP/1.1" 200 OK
```

## 4. Interpretation

**The replacement Pod took 349.8s to become Ready.** Node Ready turned Unknown 43.8s after the fault, and the controller delete request took about 300.0s after the NoExecute taint record. Replacement Pod creation to Ready took 5s.

**Request errors occurred even while 1 ready endpoint remained.** 7 errors were recorded in the fixed observation window, and there were 0 errors from replacement Pod Ready until the end of observation.

Successful throughput in the NotReady→replacement Pod Ready window fell 34.1% versus normal, from 0.332 to 0.219 req/s. Median TTFT went from 12.42 to 16.13s.

**Two replicas were secured on the surviving node before node recovery.** The replacement Pod was placed on `local-k8s-worker3`, and the surviving Pod and replacement Pod stayed on the same node after the faulted node returned. No automatic redistribution appeared during the post-return observation period.
