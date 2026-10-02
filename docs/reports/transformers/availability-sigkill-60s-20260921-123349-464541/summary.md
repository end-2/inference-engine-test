> Korean version: [한국어](summary-KR.md)

# SmolLM2 multi-node availability, SIGKILL, toleration 60s

SIGKILLed one engine worker in the `transformers-tests` kind cluster on 2026-09-21 and verified the replacement Pod, node restart, and restoration of the original Docker restart policy. The procedure completed, with 8 request errors in the observation window.

Model, image, topology, CPU, and AIPerf conditions are the same as the [pause experiment](../availability-pause-60s-20260921-122415-594492/summary.md#measurement-conditions). The SmolLM2 FP32 Pods on both engine workers use 2 CPUs, 2Gi memory, and 2 threads each, with AIPerf concurrency 4. Docker auto-restart was stopped just before SIGKILL and the original policy was restored after recovery.

| Item | Time |
| --- | ---: |
| Fault request → Node NotReady observed | 51.1s |
| Fault request → replacement Pod Ready observed | 115.9s |
| Node restart request → Node Ready observed | 1.6s |
| Pod initialization through collection and redistribution complete | 560.8s |

Terminated `transformers-tests-worker2`, and a replacement Pod became ready on `worker3`. After termination, restarted worker2 and redistributed the inference Pods across both workers. The 60s value is the Pod NoExecute toleration; node-failure detection time is separate.

| Aggregation scope | Success | Error | Success rate | Mean successful-request latency |
| --- | ---: | ---: | ---: | ---: |
| Requests started in the observation window | 428 | 8 | 98.17% | 3.704s |
| Full AIPerf, including warmup and shutdown wait | 520 | 8 | 98.48% | 3.723s |

The observation window covers requests started in `run.json`'s `[collection_start, experiment_complete)`, including completions after the window. Errors are 2 TimeoutError and 6 ClientConnectorError. Procedure completion and user-request error rate should be interpreted separately. The kind workers share the same Docker host resources.

## Observed time series

Endpoints, request latency/TTFT, and CPU over the observation window are plotted on the same time axis. x-axis 0 is the fault request time; successes plot at completion time and errors at AIPerf error-log time. The red × height of 10 is not a latency value. CPU deduplicates kubelet sample times.

![SmolLM2 request latency, TTFT, error times with ready endpoints and CPU](figures/observed-timeline.png)

[Re-run guide](../../../guides/availability-test.md), [run timestamps](run.json).
