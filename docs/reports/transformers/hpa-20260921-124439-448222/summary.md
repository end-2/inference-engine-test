> Korean version: [한국어](summary-KR.md)

# SmolLM2 multi-node CPU HPA, 1→4→1

In the `transformers-tests` kind cluster on 2026-09-21, verified HPA scale-up, high-load hold, scale-down, and a successful post-scale-down request. `status=complete`, with all 233 high-load and 5 low-load requests succeeding.

## Conditions and verdict

- 1 control-plane, 1 monitor worker, 2 engine workers, Kubernetes v1.36.4.
- SmolLM2-135M-Instruct FP32, Transformers 4.57.6, torch 2.10.0, `transformers-base-metric` image.
- 2 CPUs and 2Gi memory per inference Pod, 2 PyTorch threads, requests=limits.
- 50% of CPU request mean, min 1, max 4. Scale-up stabilization 0s, scale-down stabilization 120s, 1 Pod per 30s in each direction.
- AIPerf high load concurrency 8, low load concurrency 1 with constant 0.02 req/s. 1 worker, 30s timeout, streaming, new connection per request.
- Input/output distribution `64,32:50;256,64:50`, 16 inputs, seed 42, sequential, `ignore_eos:true`.
- 30s baseline and 60s hold after each target is reached. HPA current/desired, Deployment, Ready Pods, and ready endpoints are judged together.

## Results

| Item | Result |
| --- | ---: |
| High-load start request → 4 replicas, 4 Ready endpoints | 129.6s |
| Load reduction request → 1 replica, 1 Ready endpoint, no terminating Pods | 212.1s |
| Baseline wait through data collection complete | 536.2s, 8 min 56s |
| High-load success / error | 233 / 0 |
| Low-load success / error | 5 / 0 |
| Successful requests started and completed inside the post-scale-down hold window | 1 |

Scale-up time runs from `high_load_requested` to `scale_out_observed`; scale-down time from `load_reduction_requested` to `scale_in_observed`. Both include client setup and high-load teardown / low-load startup time. Request counts aggregate each AIPerf phase's full per-request records.

At 4 replicas, each engine worker held 2 Pods. After low load, replicas fell 4→3→2→1, and an actual request success was verified in the final 1-replica state. At exit, AIPerf and renderer were 0, the inference server was 1, and the original high-load arguments were restored. This verifies Pod scaling on kind sharing one Docker host, not node provisioning.

## Grafana panels

Exported actual Grafana panels pinned to **2026-09-21 12:44:39.449–12:53:35.605 UTC**. The high-load start request was at **12:45:42.421 UTC** and the low-load transition request at **12:48:54.496 UTC**. Export started at 13:52:14 UTC after the experiment ended, and the renderer was stopped after completion.

### CPU and replicas

The initial CPU gap and HPA desired 0 are the window before status metrics fill in. Actual available Pods and ready endpoints were each 1 during that time.

![Grafana: mean utilization versus CPU request with 50% target](figures/grafana-cpu.png)

![Grafana: HPA desired, current, and available Pods changing 1→4→1](figures/grafana-replicas.png)

### Endpoints and in-flight requests

![Grafana: Service ready endpoint growth and shrinkage](figures/grafana-endpoints.png)

![Grafana: per-Pod in-flight requests](figures/grafana-in-flight.png)

### Request throughput and TTFT

Request throughput is the 1-minute rate of the server's per-outcome counters, and TTFT p95 is the server histogram estimate over the same 1-minute window. Aggregation differs from AIPerf's per-request results.

![Grafana: per-outcome completed request throughput from the server](figures/grafana-requests.png)

![Grafana: server TTFT p95](figures/grafana-ttft.png)

[Re-run guide](../../../guides/hpa-test.md), [run timestamps and load arguments](run.json).
