> Korean version: [한국어](summary-KR.md)

# Engine node force kill (SIGKILL), NoExecute toleration 60s

## 1. Experiment summary

Injected a force-kill (SIGKILL) fault into one engine node. The Service ready endpoint decrease was observed **43.9s** after the fault, and a replacement Pod on a surviving node became Ready at **108.9s**. Replacement Pod creation to Ready took **6s**.

The AIPerf result over the fixed observation window is **140 successes, 16 errors (10.26%)**. A replacement replica was secured before node recovery, and no automatic redistribution appeared during the post-recovery observation period.

## 2. Experiment environment

| Item | Condition |
| --- | --- |
| Observation window | 2026-09-20 06:21:23.781–06:28:48.553 UTC (KST=UTC+9) |
| Cluster | kind `local-k8s`, Kubernetes v1.36.4, 1 control-plane + 3 workers |
| Placement | 1 monitor worker with AIPerf, Prometheus, Grafana, kube-state-metrics; 2 engine workers with 1 inference Pod each |
| Inference | `local/llama-base-metric:0.1.0`, model `Qwen/Qwen2.5-0.5B-Instruct`, 2 replicas, 2 CPU / 2Gi per Pod, 2 threads |
| Load | `local/aiperf:0.12.0`, concurrency 4, streaming, new connection per request, 30s timeout, input/output distribution `64,32:50;256,64:50` |
| Toleration | Pod `not-ready` and `unreachable`, both `NoExecute`, `tolerationSeconds: 60` |
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
| 06:23:54.130 | 0.0s | Docker kill event: signal=9 |
| 06:23:54.174 | 0.0s | First client error |
| 06:24:37.000 | 42.9s | Node Ready=Unknown (kubectl: NotReady) |
| 06:24:37.000 | 42.9s | unreachable:NoExecute taint recorded |
| 06:24:37.990 | 43.9s | Faulted endpoint ready=false, Service ready 2→1 observed |
| 06:24:39.179 | 45.0s | Last client error |
| 06:25:37.000 | 102.9s | Replacement Pod created on surviving engine node |
| 06:25:43.000 | 108.9s | Replacement Pod Ready=True |
| 06:25:43.607 | 109.5s | Service ready endpoint 1→2 observed |
| 06:27:15.046 | 200.9s | Node recovery command complete |
| 06:27:17.319 | 203.2s | Faulted node Ready recovery observed |
| 06:27:19.296 | 205.2s | Existing faulted Pod API object deletion observed |
| 06:28:48.553 | 294.4s | Observation end |

The interval from NoExecute taint record to controller delete request was about 60.9s. A new Pod was created while the existing faulted Pod remained Terminating, and the existing object was cleaned up after node recovery.

### Pod changes and Kubernetes state

| Category | Pod name | Normal | During fault | After node return |
| --- | --- | --- | --- | --- |
| A: faulted | `llama-base-metric-7c6d46685b-6clln` | local-k8s-worker2, Ready | Ready=False → Terminating | Deleted |
| B: surviving | `llama-base-metric-7c6d46685b-9hvx6` | local-k8s-worker3, Ready | Kept serving | Stayed on same node |
| C: replacement | `llama-base-metric-7c6d46685b-pldfh` | None | Newly created on local-k8s-worker3, then Ready | Stayed on same node |

Replacement Pod C has UID `f38c9c3c-497e-48ef-9bd9-be58fd4c404f`. Pod C was newly created on the surviving node.

### Client impact

Successes are grouped by AIPerf request completion time and errors by ERROR log time. Latency and TTFT are distributions over successful requests only, and the failure-rate denominator is the sum of successful completions and errors within each window.

| Window | Length | Success / Error | Failure rate | Success req/s | Latency p50 / p95 | TTFT p50 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Normal | 150.3s | 51 / 0 | 0.00% | 0.339 | 11.13 / 22.14s | 10.24s |
| Fault→Node NotReady | 42.9s | 5 / 14 | 73.68% | 0.117 | 19.36 / 26.79s | 17.74s |
| NotReady→replacement Pod Ready | 66.0s | 14 / 2 | 12.50% | 0.212 | 17.22 / 22.32s | 16.36s |
| Replacement Pod Ready→node recovery command | 92.0s | 37 / 0 | 0.00% | 0.402 | 9.18 / 19.42s | 8.34s |
| Node recovery command→observation end | 93.5s | 33 / 0 | 0.00% | 0.353 | 11.21 / 19.79s | 9.55s |

| Error type (full AIPerf run) | Count |
| --- | ---: |
| `ServerDisconnectedError` | 3 |
| `ClientPayloadError` | 1 |
| `ClientConnectorError` | 12 |

The full AIPerf run had 169 successes and 16 errors, covering warmup and shutdown handling, so its scope differs from the fixed observation window. The maximum gap between successful response completions was **8.16s**.

The graph below aligns this experiment's per-request AIPerf results, error logs, Prometheus EndpointSlice, and kubelet CPU on the same time axis. Blue dots are successful request latency, orange dots are successful request TTFT, and the x-axis is seconds from fault injection. Red × marks actual error log times, and **the marker height of 32 is not a latency value**. CPU has duplicate cached samples removed.

![AIPerf request latency, TTFT, error times with EndpointSlice and CPU](figures/observed-timeline.png)

### Representative logs

Excerpted errors, eviction, and replacement server startup, excluding repeated probe and scrape logs. Long error messages are shortened.

```text
06:23:54.174  AIPerf      ServerDisconnectedError('Server disconnected')
06:23:54.175  AIPerf      ClientPayloadError("Response payload is not completed: <TransferEncodingError: 400, message='Not enough data to satisfy transfer length header.'>")
06:23:54.178  AIPerf      ClientConnectorError(ConnectionKey(host='llama-base-metric', port=8000, is_ssl=False, ssl=True, proxy=None, proxy_auth=None, proxy_headers_hash=None), ConnectionRefusedError(111, "Connect call failed
06:24:39.179  AIPerf      ClientConnectorError(ConnectionKey(host='llama-base-metric', port=8000, is_ssl=False, ssl=True, proxy=None, proxy_auth=None, proxy_headers_hash=None), OSError(113, "Connect call failed ('10.96.150.242
06:25:37.945  Controller  "Deleting pod" controller="taint-eviction-controller" [Pod A]
06:25:39.107  Server C    Application startup complete.
06:25:45.753  Server C    "POST /v1/chat/completions HTTP/1.1" 200 OK
```

## 4. Interpretation

**The replacement Pod took 108.9s to become Ready.** Node Ready turned Unknown 42.9s after the fault, and the controller delete request took about 60.9s after the NoExecute taint record. Replacement Pod creation to Ready took 6s.

**Request errors occurred even while 1 ready endpoint remained.** 16 errors were recorded in the fixed observation window, and there were 0 errors from replacement Pod Ready until the end of observation.

Successful throughput in the NotReady→replacement Pod Ready window fell 37.5% versus normal, from 0.339 to 0.212 req/s. Median TTFT went from 10.24 to 16.36s.

**Two replicas were secured on the surviving node before node recovery.** The replacement Pod was placed on `local-k8s-worker3`, and the surviving Pod and replacement Pod stayed on the same node after the faulted node returned. No automatic redistribution appeared during the post-return observation period.
