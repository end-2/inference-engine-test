> Korean version: [한국어](summary-KR.md)

# Engine node force kill (SIGKILL), NoExecute toleration 300s

## 1. Experiment summary

Injected a force-kill (SIGKILL) fault into one engine node. The Service ready endpoint decrease was observed **50.2s** after the fault, and a replacement Pod on a surviving node became Ready at **354.5s**. Replacement Pod creation to Ready took **6s**.

The AIPerf result over the fixed observation window is **206 successes, 11 errors (5.07%)**. A replacement replica was secured before node recovery, and no automatic redistribution appeared during the post-recovery observation period.

## 2. Experiment environment

| Item | Condition |
| --- | --- |
| Observation window | 2026-09-20 05:37:15.961–05:48:48.880 UTC (KST=UTC+9) |
| Cluster | kind `local-k8s`, Kubernetes v1.36.4, 1 control-plane + 3 workers |
| Placement | 1 monitor worker with AIPerf, Prometheus, Grafana, kube-state-metrics; 2 engine workers with 1 inference Pod each |
| Inference | `local/llama-base-metric:0.1.0`, model `Qwen/Qwen2.5-0.5B-Instruct`, 2 replicas, 2 CPU / 2Gi per Pod, 2 threads |
| Load | `local/aiperf:0.12.0`, concurrency 4, streaming, new connection per request, 30s timeout, input/output distribution `64,32:50;256,64:50` |
| Toleration | Pod `not-ready` and `unreachable`, both `NoExecute`, `tolerationSeconds: 300` |
| Scheduling and termination | hostname preferred pod anti-affinity, `terminationGracePeriodSeconds: 60` |
| Fault target | `local-k8s-worker2` |
| Collection interval | Kubernetes objects and Docker state ~2s, Prometheus 5s, kubelet resources ~10s; Docker events, timestamped logs |

CPU and memory requests and limits were equal. The inference image and model were prepared on the engine nodes.

Confirmed Docker `kill(signal=9)` and `die(exitCode=137)` events with `Status=exited, Running=false, Paused=false, Pid=0, OOMKilled=false`. The Docker restart policy during the experiment was `no`.

## 3. Observations

### Rescheduling timeline

Relative times are measured from the Docker `kill(signal=9)` event. Condition and object timestamps are in seconds, and "observed" timestamps include delays from the object collection interval.

| UTC time | After fault | Observation |
| --- | ---: | --- |
| 05:39:47.458 | 0.0s | Docker kill event: signal=9 |
| 05:39:47.491 | 0.0s | First client error |
| 05:40:36.000 | 48.5s | Node Ready=Unknown (kubectl: NotReady) |
| 05:40:37.000 | 49.5s | unreachable:NoExecute taint recorded |
| 05:40:37.700 | 50.2s | Faulted endpoint ready=false, Service ready 2→1 observed |
| 05:40:37.809 | 50.4s | Last client error |
| 05:45:36.000 | 348.5s | Replacement Pod created on surviving engine node |
| 05:45:42.000 | 354.5s | Replacement Pod Ready=True |
| 05:45:42.936 | 355.5s | Service ready endpoint 1→2 observed |
| 05:47:14.136 | 446.7s | docker start complete |
| 05:47:17.637 | 450.2s | Existing faulted Pod API object deletion observed |
| 05:47:17.637 | 450.2s | Faulted node Ready recovery observed |
| 05:48:48.880 | 541.4s | Observation end |

The interval from NoExecute taint record to controller delete request was about 300.0s. A new Pod was created while the existing faulted Pod remained Terminating, and the existing object was cleaned up after node recovery.

### Pod changes and Kubernetes state

| Category | Pod name | Normal | During fault | After node return |
| --- | --- | --- | --- | --- |
| A: faulted | `llama-base-metric-6d9654fcdb-s6rvn` | local-k8s-worker2, Ready | Ready=False → Terminating | Deleted |
| B: surviving | `llama-base-metric-6d9654fcdb-r5jww` | local-k8s-worker3, Ready | Kept serving | Stayed on same node |
| C: replacement | `llama-base-metric-6d9654fcdb-5zdj8` | None | Newly created on local-k8s-worker3, then Ready | Stayed on same node |

Replacement Pod C has UID `3871db98-d8b8-4b46-b2e8-ab30d0276e5c`. Pod C was newly created on the surviving node.

### Client impact

Successes are grouped by AIPerf request completion time and errors by ERROR log time. Latency and TTFT are distributions over successful requests only, and the failure-rate denominator is the sum of successful completions and errors within each window.

| Window | Length | Success / Error | Failure rate | Success req/s | Latency p50 / p95 | TTFT p50 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Normal | 151.5s | 62 / 0 | 0.00% | 0.409 | 9.36 / 17.89s | 8.42s |
| Fault→Node NotReady | 48.5s | 7 / 10 | 58.82% | 0.144 | 11.27 / 16.94s | 9.56s |
| NotReady→replacement Pod Ready | 306.0s | 67 / 1 | 1.47% | 0.219 | 16.98 / 21.97s | 16.19s |
| Replacement Pod Ready→node recovery command | 92.1s | 35 / 0 | 0.00% | 0.380 | 9.25 / 18.42s | 8.44s |
| Node recovery command→observation end | 94.7s | 35 / 0 | 0.00% | 0.369 | 9.14 / 22.33s | 8.33s |

| Error type (full AIPerf run) | Count |
| --- | ---: |
| `ServerDisconnectedError` | 1 |
| `ClientPayloadError` | 1 |
| `ClientConnectorError` | 7 |
| `TimeoutError` | 2 |

The full AIPerf run had 233 successes and 11 errors, covering warmup and shutdown handling, so its scope differs from the fixed observation window. The maximum gap between successful response completions was **15.92s**.

The graph below aligns this experiment's per-request AIPerf results, error logs, Prometheus EndpointSlice, and kubelet CPU on the same time axis. Blue dots are successful request latency, orange dots are successful request TTFT, and the x-axis is seconds from fault injection. Red × marks actual error log times, and **the marker height of 32 is not a latency value**. CPU has duplicate cached samples removed.

![AIPerf request latency, TTFT, error times with EndpointSlice and CPU](figures/observed-timeline.png)

### Representative logs

Excerpted errors, eviction, and replacement server startup, excluding repeated probe and scrape logs. Long error messages are shortened.

```text
05:39:47.491  AIPerf      ServerDisconnectedError('Server disconnected')
05:39:47.491  AIPerf      ClientPayloadError("Response payload is not completed: <TransferEncodingError: 400, message='Not enough data to satisfy transfer length header.'>")
05:39:47.494  AIPerf      ClientConnectorError(ConnectionKey(host='llama-base-metric', port=8000, is_ssl=False, ssl=True, proxy=None, proxy_auth=None, proxy_headers_hash=None), ConnectionRefusedError(111, "Connect call failed
05:40:37.809  AIPerf      ClientConnectorError(ConnectionKey(host='llama-base-metric', port=8000, is_ssl=False, ssl=True, proxy=None, proxy_auth=None, proxy_headers_hash=None), TimeoutError(110, "Connect call failed ('10.96.15
05:45:36.979  Controller  "Deleting pod" controller="taint-eviction-controller" [Pod A]
05:45:38.113  Server C    Application startup complete.
05:45:47.774  Server C    "POST /v1/chat/completions HTTP/1.1" 200 OK
```

## 4. Interpretation

**The replacement Pod took 354.5s to become Ready.** Node Ready turned Unknown 48.5s after the fault, and the controller delete request took about 300.0s after the NoExecute taint record. Replacement Pod creation to Ready took 6s.

**Request errors occurred even while 1 ready endpoint remained.** 11 errors were recorded in the fixed observation window, and there were 0 errors from replacement Pod Ready until the end of observation.

Successful throughput in the NotReady→replacement Pod Ready window fell 46.5% versus normal, from 0.409 to 0.219 req/s. Median TTFT went from 8.42 to 16.19s.

**Two replicas were secured on the surviving node before node recovery.** The replacement Pod was placed on `local-k8s-worker3`, and the surviving Pod and replacement Pod stayed on the same node after the faulted node returned. No automatic redistribution appeared during the post-return observation period.

The object collector in this run was restarted after a fix for empty EndpointSlice handling during the normal window, producing one ~9.7s sample gap. The maximum object sample gap after fault injection was ~2.2s, and Prometheus and AIPerf logs were collected separately throughout.
