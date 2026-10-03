> Korean version: [한국어](availability-test-KR.md)

# Multi-node service availability test

Send AIPerf load to two Transformers CPU base servers for SmolLM2 while pausing or SIGKILLing one engine worker. Collect node status, replacement Pod and Service endpoint recovery, and actual request results.

The default procedure uses Transformers CPU. For llama.cpp, apply the [per-engine changes](#llamacpp); observation and pass criteria are the same.

For inference implementation and API, see the [inference engine guide](inference-engine.md); for manifest and ConfigMap handling, see [manifest management](manifests.md).

## Configuration

| Item | Setting |
| --- | --- |
| kind | 1 control-plane, 1 monitor worker, 2 engine workers |
| Model | Fixed SmolLM2-135M-Instruct FP32 snapshot; server and AIPerf use the same tokenizer |
| Server | `transformers-base-metric`; resources and thread settings are managed in the deployment manifest |
| Placement | Spread across engine workers; allow replacement Pods on the surviving worker after failure |
| AIPerf | Monitor worker, concurrency 4, 1 worker, 30s timeout, new connection per request |
| Inputs and outputs | `64,32:50;256,64:50`, 16 inputs, seed 42, sequential, `ignore_eos:true` |
| Observation | Prometheus 5s scrape, kube-state-metrics, Grafana, `transformers_*` metrics from `/metrics` |

All measurement containers use CPU and memory `requests=limits`. Check resource requests in the deployment manifests; the surviving engine worker needs spare capacity for a replacement Pod after failure. Reserve additional resources for the monitor and Kubernetes system.

kind nodes share the same Docker host resources, so stop other load experiments during measurement.

Configuration sources are the [availability manifests](../../k8s/experiment/profiles/availability-transformers.yaml), [multi-node topology](../../config/cluster/kind-multi-node.yaml), and [model snapshot](../../config/models/smollm2-135m-transformers.env).

## Preparation

Docker, a POSIX shell, and Python 3.10 or later are required. Run from the repository root.

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

Create this separately from the default `local-k8s` single-node cluster. `up` does not change the topology of an existing cluster, so pick a new name if a single-node cluster with the same name exists.

The availability test runner checks for 2 engine workers and 1 monitor worker, and uses an isolated kubeconfig.

## Deploy and run

If you ran the HPA test on the same cluster, export its results first and clean up with `./scripts/k8s.sh delete k8s/experiment/profiles/hpa-transformers.yaml`. This command also deletes that test's PVC.

```sh
./scripts/k8s.sh apply k8s/experiment/profiles/availability-transformers.yaml
for deployment in transformers-base-metric prometheus kube-state-metrics grafana; do
  ./scripts/local-k8s.sh kubectl -n availability-test-transformers rollout status "deployment/$deployment" --timeout=300s
done
./scripts/local-k8s.sh kubectl -n availability-test-transformers wait --for=condition=Ready pod/aiperf-results --timeout=120s

python3 scripts/run-availability-test-transformers.py --scenario pause-60s --dry-run
python3 scripts/run-availability-test-transformers.py --scenario pause-60s
python3 scripts/run-availability-test-transformers.py --scenario sigkill-60s
```

`--scenario` supports `pause-60s`, `sigkill-60s`, `pause-300s`, and `sigkill-300s`. The number is the Pod `not-ready` and `unreachable` NoExecute toleration, not the failure duration. To compare all four conditions, run them sequentially with different scenarios.

Each run redistributes Pods, then observes a 90s warmup, a 150s healthy interval, node failure, 90s after the replacement Pod is Ready, and 90s after node recovery. Elapsed time varies with the environment and recovery state; actual timestamps are recorded in `run.json`.

The `--cluster` default is `CLUSTER_NAME` or `transformers-tests`. Without `--victim-node`, the first engine worker is selected.

The runner validates the Docker kind cluster and worker membership and never faults the control-plane. It disables Docker auto-restart during SIGKILL and restores the original policy. It attempts node recovery and AIPerf shutdown on failure and Ctrl+C.

The availability and HPA test runners share the same cluster lock, so they do not run at the same time.

Inference Pods spread with hostname-based preferred pod anti-affinity and can be co-located on the surviving worker after failure. Return of the node alone does not redistribute them, so the runner recreates Pods on exit.

If recovery did not run because of process SIGKILL or host shutdown, check the target node and original Docker policy in `run.json` and recover manually.

## Results and observation

Store originals in `reports/transformers/availability-<scenario>-<UTC>/`. This includes `run.json`, `actions.jsonl`, Kubernetes and Docker observations, server logs, `aiperf/` per-request JSONL and aggregates, and Prometheus series. The summary report is in the [Transformers result list](../reports/transformers/README.md).

Prometheus, Grafana, and AIPerf results are stored on the monitor node PVC. The default StorageClass and monitoring image downloads are required; PVC data is lost when the cluster is deleted. The runner does not generate reports or graphs automatically.

Judge failure rate, timeouts, TTFT, and ITL from per-request AIPerf results. Requests that never reached the server are not included in server metrics.

`status=complete` means the fault injection, replacement Pod, node recovery, and collection steps finished. Request errors such as timeouts during the failure can still occur, so check the AIPerf success rate separately.

Server HTTP 200 responses with SSE errors are recorded as `transformers_requests_total{outcome="error"}`. `/healthz`, `/readyz`, and `/metrics` are excluded from request metrics.

```sh
./scripts/local-k8s.sh kubectl -n availability-test-transformers get pods -o wide
./scripts/local-k8s.sh kubectl -n availability-test-transformers port-forward service/grafana 3000:3000
```

Use the Grafana `availability-test-transformers` dashboard. The renderer has 0 replicas by default and runs only after measurement ends. After shutdown the load Pod count is 0, and the 2 inference Pods spread across the two workers again.

| File and directory | Collected data |
| --- | --- |
| `run.json`, `actions.jsonl` | Experiment settings, fault and recovery times, run status |
| `aiperf/` | Per-request JSONL and AIPerf aggregates |
| `prometheus/`, `metric-range.json` | Request, latency, TTFT, node, Pod, and EndpointSlice series and query range |
| `kubernetes-snapshots.jsonl.gz`, `state-changes.jsonl` | Kubernetes object samples and state changes |
| `resources.jsonl.gz` | kubelet CPU and memory samples |
| `docker-events.jsonl`, `docker-states.jsonl` | Target node container events and states |
| `*.log`, per-step `*.txt`, `*-docker.json` | Client, server, and controller logs and per-step states |

## Validation and cleanup

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_transformers_metric.py'
python3 -m unittest discover -s tests -p 'test_availability_runner_transformers.py'
sh tests/test-hpa-manifests-transformers.sh
# After collecting original results, clean up the test namespace and PVC
./scripts/k8s.sh delete k8s/experiment/profiles/availability-transformers.yaml
```

The metric unit tests need the Transformers runtime and dependencies in `src/transformer/base_metric/requirements.txt`. To delete the cluster, run `./scripts/local-k8s.sh down` with the same `CLUSTER_NAME`. Host-collected results and models are kept.

## llama.cpp

Change the following values in the procedure above. Use the selected `CLUSTER_NAME` in every terminal.

| Item | Transformers default | llama.cpp |
| --- | --- | --- |
| Cluster example | `transformers-tests` | `availability-test-llamacpp` |
| Model preparation | `./scripts/download-transformers-model.sh` | `./scripts/download-model-llamacpp.sh` and `./scripts/download-tokenizer-llamacpp.sh` |
| Inference image and Deployment | `transformers-base-metric` | `base-metric-llamacpp` |
| Manifests | `k8s/experiment/profiles/availability-transformers.yaml` | `k8s/experiment/profiles/availability-llamacpp.yaml` |
| Namespace and dashboard | `availability-test-transformers` | `availability-test-llamacpp` |
| Runner script | `scripts/run-availability-test-transformers.py` | `scripts/run-availability-test-llamacpp.py` |
| Result root | `reports/transformers/` | `reports/llamacpp/` |

The model uses the [Qwen GGUF settings](../../config/models/qwen2.5-0.5b-gguf-llamacpp.env); match the server and AIPerf model and tokenizer. Use the [llama.cpp manifests](../../k8s/experiment/profiles/availability-llamacpp.yaml) for resources and load settings. When cleaning up another test on the same cluster, select that engine's namespace and manifests.

After initial deployment and before reruns, stop AIPerf and the renderer with the commands below. The llama.cpp AIPerf manifest defaults to 1 replica, so this step is needed even for the first run. Each scenario runs independently and does not depend on order.

```sh
export CLUSTER_NAME=availability-test-llamacpp
./scripts/local-k8s.sh kubectl -n availability-test-llamacpp scale deployment/aiperf --replicas=0
./scripts/local-k8s.sh kubectl -n availability-test-llamacpp wait --for=delete pod -l app=aiperf --timeout=150s
./scripts/local-k8s.sh kubectl -n availability-test-llamacpp scale deployment/grafana-renderer --replicas=0
python3 scripts/run-availability-test-llamacpp.py --scenario pause-60s --dry-run
python3 scripts/run-availability-test-llamacpp.py --scenario pause-60s
```

Use the following commands for llama.cpp metric validation.

```sh
python -m pip install -r src/llamacpp/base_metric/requirements.txt fastapi httpx
python -m unittest discover -s tests -p 'test_base_metric_llamacpp.py'
```
