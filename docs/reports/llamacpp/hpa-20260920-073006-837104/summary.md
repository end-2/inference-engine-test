> Korean version: [한국어](summary-KR.md)

# CPU HPA scale-out experiment

An HPA with a 50% CPU target grew inference replicas from **1 → 2 → 3 → 4** under AIPerf load. New Pod Ready state and Service endpoint inclusion were verified, and the target state was held for over 60s to complete automatic validation.

## Run conditions

- Run: 2026-09-20 07:30:06–07:34:02 UTC, `hpa-test` namespace on the `local-k8s` cluster.
- Environment: Kubernetes v1.36.4, 1 kind control-plane, 2 engine workers, 1 monitor worker. Shares 15 Docker host CPUs and about 23.9 GiB memory.
- Inference: `local/llama-base-metric:0.1.0`, Qwen2.5-0.5B-Instruct Q4_K_M, 2 threads and 2 CPU / 2 GiB memory per Pod (`requests=limits`).
- HPA: 50% average utilization of CPU request, 1–4 replicas, at most 1 Pod added per 30s. Used Metrics Server v0.8.1.
- Load: AIPerf 0.12.0, concurrency 8, streaming, new connection per request, 30s timeout. Used target input/output tokens `64/32` and `256/64` at 50% each.
- The existing availability-test inference Pods (2) and observation setup were on the same host; their AIPerf and renderer were stopped.

## Observations

Elapsed times use the AIPerf Deployment scale request at **07:30:38.420 UTC** as zero. They are first-observed times in 5s samples, so they differ from controller event times.

| Target replicas | Desired increase observed | HPA CPU at the time | Ready endpoint reached |
| ---: | ---: | ---: | ---: |
| 2 | +52.2s | 99% | +57.3s |
| 3 | +98.3s | 61% | +103.4s |
| 4 | +123.9s | 96% | +129.1s |

HPA current reached 4 at **+139.4s**. Desired/current, Deployment replicas/available, Ready Pods, and 4 endpoints were then held for about 62s. HPA events recorded `SuccessfulRescale` to replicas 2, 3, and 4 respectively for exceeding the CPU target.

At completion, the Prometheus successful-request counter had risen from a baseline of 0 to 83. The stored final AIPerf result at load stop is 84 successes out of 101 completed requests with 17 timeouts (16.83%). Successful requests had TTFT p95 26.51s and request latency p95 27.53s. The success counts differ by 1 because the two aggregations end at different times.

This result verifies **CPU-based replica growth and service inclusion**. Applying concurrency 8 to a single initial Pod produced timeouts, so it does not mean error-free serving or latency-target achievement. This is a single run on a shared host; scale-out time and serving performance can vary with resource contention.

## Grafana panels

The images below are PNG exports of actual panels from the `hpa-test` Grafana dashboard. All panels use a fixed data range of **2026-09-20 07:30:06.837–07:34:02.952 UTC**. Load started at 07:30:38.420, 4-replica validation at 07:32:57.861, and load stop at 07:34:01.609 UTC. Export started at 07:48:32 UTC the same day; the renderer ran only after load measurement ended.

### CPU and replicas

In the CPU panel, `observed` is the request-relative mean utilization last evaluated by the HPA, and `target` is the configured 50%. The replica panel shows desired/current together with Deployment available.

![Grafana: mean utilization versus CPU request with 50% target](figures/grafana-cpu.png)

![Grafana: HPA desired/current and available Pods growing 1→4](figures/grafana-replicas.png)

### Service inclusion and request distribution

Compares the ready-endpoint 1→4 growth with per-Pod in-flight requests. Endpoint-growth and HPA current update times differ by collection and control intervals.

![Grafana: inference Service ready endpoint count](figures/grafana-endpoints.png)

![Grafana: per-Pod in-flight requests](figures/grafana-in-flight.png)

### Server throughput and TTFT

Completed-request throughput is the server-recorded per-outcome value and does not map one-to-one to client timeout counts. TTFT is the server histogram's trailing-1-minute p95, which differs in location and aggregation range from the AIPerf full-window successful-request TTFT p95 above.

![Grafana: per-outcome completed request throughput from the server](figures/grafana-requests.png)

![Grafana: server TTFT p95](figures/grafana-ttft.png)

## Reproduction and evidence

Follow [preparation and the run guide](../../../guides/hpa-test.md#llamacpp) to deploy, keep the same `CLUSTER_NAME`, and run the [HPA script](../../../../scripts/run-hpa-test-llamacpp.py) from the repository root. Stop the load after the target replicas are confirmed held.

```sh
python3 scripts/run-hpa-test-llamacpp.py --scenario scale-out --target-replicas 4 --hold-seconds 60
```

Observations are summarized in the tables above and the Grafana PNGs under `figures/`.
