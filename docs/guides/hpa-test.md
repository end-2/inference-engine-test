> Korean version: [한국어](hpa-test-KR.md)

# CPU HPA test

Send AIPerf load to a SmolLM2 Transformers CPU base server and verify CPU HPA scale-out from 1 to 4 and scale-in from 4 to 1. Check actual Ready Pods, Service endpoints, and successful requests together.

The default procedure uses Transformers CPU. For llama.cpp, apply the [per-engine changes](#llamacpp); observation and pass criteria are the same.

For inference implementation and API, see the [inference engine guide](inference-engine.md); for manifest and ConfigMap handling, see [manifest management](manifests.md).

## Preparation and deployment

Use 1 control-plane, 1 monitor worker, 2 engine workers, and the `transformers-base-metric` image. Resources and threads are set in the [deployment manifests](../../k8s/hpa-test-transformers/) with `requests=limits` kept.

Reserve inference capacity based on per-Pod resource requests and max replica count, plus extra resources for the monitor and Kubernetes system.

Docker, a POSIX shell, and Python 3.10 or later are required. Prepare the model, cluster, and images from the repository root.

```sh
export CLUSTER_NAME=transformers-tests
export PATH="$PWD/.bin:$PATH"
./scripts/local-k8s.sh install
./scripts/download-transformers-model.sh
KIND_CONFIG=config/cluster/kind-multi-node.yaml ./scripts/local-k8s.sh up
./scripts/build-inference-images.sh transformers-base-metric
./scripts/load-inference-images.sh transformers-base-metric
./scripts/build-benchmark-images.sh
./scripts/load-benchmark-images.sh
```

`up` does not change an existing cluster topology. If a single-node cluster with the same name exists, pick a new name. Run all commands with the same `CLUSTER_NAME`.

If the availability test is deployed, export its results then clean up with `./scripts/local-k8s.sh kubectl delete -f k8s/availability-test-transformers`. This command also deletes that test's PVC. Do not run it together with other load experiments.

```sh
export CLUSTER_NAME=transformers-tests
./scripts/local-k8s.sh kubectl apply -f k8s/metrics-server
./scripts/local-k8s.sh kubectl -n kube-system rollout status deployment/metrics-server --timeout=180s
./scripts/local-k8s.sh kubectl wait --for=condition=Available apiservice/v1beta1.metrics.k8s.io --timeout=180s
./scripts/local-k8s.sh kubectl apply -f k8s/hpa-test-transformers/namespace.yaml
./scripts/local-k8s.sh kubectl apply -f k8s/hpa-test-transformers
for deployment in transformers-base-metric prometheus kube-state-metrics grafana; do
  ./scripts/local-k8s.sh kubectl -n hpa-test-transformers rollout status "deployment/$deployment" --timeout=300s
done
./scripts/local-k8s.sh kubectl -n hpa-test-transformers wait --for=condition=Ready pod/aiperf-results --timeout=120s
./scripts/local-k8s.sh kubectl -n hpa-test-transformers wait \
  --for=jsonpath='{.status.currentMetrics[0].resource.current.averageUtilization}' \
  hpa/transformers-base-metric --timeout=180s
./scripts/local-k8s.sh kubectl -n hpa-test-transformers top pods
```

New Pods need time until first metric collection even after becoming Ready. Wait for the HPA CPU reading, then run `top`.

If a Metrics Server already exists, use that Metrics API. The repository `--kubelet-insecure-tls` setting is for kind experiments. Metrics Server is for HPA control; Prometheus is for observation.

| Item | Default |
| --- | --- |
| HPA | `autoscaling/v2`, min 1, max 4, 50% average of CPU request |
| Scale-out policy | 0s stabilization, 1 Pod per 30s |
| Scale-in policy | 120s stabilization, 1 Pod per 30s |
| High load | AIPerf concurrency 8, 1 worker, 30s timeout |
| Low load | Concurrency 1, constant 0.02 req/s |
| Decision | 600s limit per phase, hold 60s after reaching scale-out and scale-in targets |

The CPU target is utilization relative to Pod CPU request. The inference Deployment replicas are managed by HPA; AIPerf and the renderer start at 0.

The model is a fixed SmolLM2-135M-Instruct FP32 snapshot; server and AIPerf use that snapshot's tokenizer. Input and output length distribution is `64,32:50;256,64:50`, 16 inputs, seed 42, sequential, `ignore_eos:true`.

The [HPA manifests](../../k8s/hpa-test-transformers/) define namespace, RBAC, dashboard, and load independently.

## Run

```sh
python3 scripts/run-hpa-test-transformers.py --scenario scale-out-in --dry-run
python3 scripts/run-hpa-test-transformers.py --scenario scale-out-in
# To verify scale-out only, run separately
python3 scripts/run-hpa-test-transformers.py --scenario scale-out
```

The default scenario of `run-hpa-test-transformers.py` is `scale-out-in`. `--cluster` defaults to `CLUSTER_NAME` or `transformers-tests`.

The runner checks for 2 engine workers and 1 monitor worker, and blocks duplicate runs with a lock shared with the availability test.

The runner verifies the no-load minimum-replica state for 30s, then starts high load. Scale-out is accepted only when HPA current/desired, Deployment replicas/available, Ready Pods, and ready endpoints matching them all reach the target count and new Pods have joined. Pending Pods or desired-count increase alone do not pass.

After scale-out-in stops high load, it restarts the AIPerf Pod under low-load conditions. Scale-in is accepted only when CPU is below target, actual Pods and endpoints are both 1, terminating Pods are 0. It passes only with at least one successful request started and finished inside the following 60s hold window. Client shutdown and initialization time between the two load phases is also recorded.

`--target-replicas` adjusts the scale-out decision target without changing the HPA maximum. `--timeout` adjusts the phase limit; `--hold-seconds` adjusts the hold time.

The scale-out-in `--low-request-rate` adjusts the low-load arrival rate. Concurrency 1 alone may not lower CPU enough.

On failure and Ctrl+C, it still attempts load shutdown, original client argument restore, and data collection.

Start with AIPerf and the renderer stopped, and do not manually change inference replicas during measurement. Timeouts and collection failures are recorded as `status=failed`.

## Observation and results

```sh
./scripts/local-k8s.sh kubectl -n hpa-test-transformers get hpa,pods -o wide
./scripts/local-k8s.sh kubectl -n hpa-test-transformers top pods
./scripts/local-k8s.sh kubectl -n hpa-test-transformers port-forward service/grafana 3000:3000
```

Check CPU, HPA replicas, endpoints, and `transformers_*` request metrics on the Grafana `hpa-test-transformers` dashboard. If CPU shows `<unknown>`, check the Metrics API and CPU request; if Pods are Pending, check engine worker reserved resources, image, and model mount.

Originals are stored in `reports/transformers/hpa-<UTC>/`. This includes the `run.json` scenario, phase times and request counts, 5s samples in `observations.csv`, Kubernetes originals, `aiperf/high/`, `aiperf/low/`, and Prometheus series.

Pass or fail is judged by request success in the high- and low-load intervals; error rate and latency are interpreted separately. The summary is in the [Transformers result list](../reports/transformers/README.md).

## Validation and cleanup

```sh
python3 -m unittest discover -s tests -p 'test_hpa_runner_transformers.py'
sh tests/test-hpa-manifests-transformers.sh
# After collecting results, delete workloads and PVC
./scripts/local-k8s.sh kubectl delete -f k8s/hpa-test-transformers
# When this Metrics Server is only used for this experiment
./scripts/local-k8s.sh kubectl delete -f k8s/metrics-server
```

## llama.cpp

Change the following values in the procedure above. Use the selected `CLUSTER_NAME` in every terminal.

| Item | Transformers default | llama.cpp |
| --- | --- | --- |
| Cluster example | `transformers-tests` | `hpa-test-llamacpp` |
| Model preparation | `./scripts/download-transformers-model.sh` | `./scripts/download-model-llamacpp.sh` and `./scripts/download-tokenizer-llamacpp.sh` |
| Inference image and Deployment | `transformers-base-metric` | `base-metric-llamacpp` |
| Manifests | `k8s/hpa-test-transformers` | `k8s/hpa-test-llamacpp` |
| Namespace and dashboard | `hpa-test-transformers` | `hpa-test-llamacpp` |
| Runner script | `scripts/run-hpa-test-transformers.py` | `scripts/run-hpa-test-llamacpp.py` |
| Result root | `reports/transformers/` | `reports/llamacpp/` |

The model uses the [Qwen GGUF settings](../../config/models/qwen2.5-0.5b-gguf-llamacpp.env); match the server and AIPerf model and tokenizer. Use the [llama.cpp manifests](../../k8s/hpa-test-llamacpp/) for resources and load settings. When cleaning up another test on the same cluster, select that engine's namespace and manifests.

```sh
export CLUSTER_NAME=hpa-test-llamacpp
python3 scripts/run-hpa-test-llamacpp.py --scenario scale-out-in --dry-run
python3 scripts/run-hpa-test-llamacpp.py --scenario scale-out-in
# When verifying scale-out only
python3 scripts/run-hpa-test-llamacpp.py --scenario scale-out
```

If forced termination skipped cleanup, stop the load, copy results, then restore defaults. For Transformers, replace with that namespace and result root for recovery.

```sh
./scripts/local-k8s.sh kubectl -n hpa-test-llamacpp scale deployment/aiperf --replicas=0
./scripts/local-k8s.sh kubectl -n hpa-test-llamacpp wait --for=delete pod -l app=aiperf --timeout=150s
mkdir -p reports/llamacpp/hpa-manual
./scripts/local-k8s.sh kubectl -n hpa-test-llamacpp cp aiperf-results:/results reports/llamacpp/hpa-manual/aiperf
./scripts/local-k8s.sh kubectl apply -f k8s/hpa-test-llamacpp/namespace.yaml
./scripts/local-k8s.sh kubectl apply -f k8s/hpa-test-llamacpp
```

Use the following commands for llama.cpp runner and manifest validation.

```sh
python3 -m unittest discover -s tests -p 'test_hpa_runner_llamacpp.py'
sh tests/test-hpa-manifests-llamacpp.sh
```

Reports and Grafana PNGs are not generated automatically. If scale-in is delayed, check the low-load request rate, scale-in stabilization time, and terminating Pods.
