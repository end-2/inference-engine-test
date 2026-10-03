> Korean version: [한국어](manifests-KR.md)

# Kubernetes manifests with Helm

Every directory directly under `k8s/` is a Helm chart. Each chart keeps shared defaults in `values.yaml`; charts with workload variants keep overrides in `profiles/*.yaml`. `make install` installs the pinned Helm version from [versions.env](../../config/versions.env). Charts have no external chart dependencies.

```text
k8s/
  inference/
  aiperf/
  experiment/
  inference-distributed/
  metrics-server/
```

Each chart includes `Chart.yaml`, `values.yaml` and `templates/`. Experiment configuration and patches live in `experiment/files/` and `experiment/scenarios/`.

| Chart | Profiles | Shared defaults |
| --- | --- | --- |
| Inference | CPU, GPU, Mamba and MPS servers | [inference/values.yaml](../../k8s/inference/values.yaml) |
| AIPerf | Model and dataset profiles, PD benchmark | [aiperf/values.yaml](../../k8s/aiperf/values.yaml) |
| Experiment | Availability and HPA, both engines | [experiment/values.yaml](../../k8s/experiment/values.yaml) |
| inference-distributed | Two or four MPS slots, serial or token-budget scheduling | [inference-distributed/values.yaml](../../k8s/inference-distributed/values.yaml) |
| Metrics Server | Local kind metrics | [components.yaml](../../k8s/metrics-server/templates/components.yaml) |

## Rendering and applying

Run from the repository root. Rendering works without a cluster. Scripts accept a chart directory or a values file inside a chart. The apply helper renders completely before calling kubectl against the isolated local kubeconfig. It does not create Helm releases.

```sh
./scripts/render-k8s.sh k8s/inference/profiles/transformers-base-cpu.yaml
./scripts/k8s.sh apply k8s/inference/profiles/transformers-base-cpu.yaml
./scripts/k8s.sh apply k8s/experiment/profiles/hpa-transformers.yaml

# Select a GPU cluster using the existing cluster wrapper.
LOCAL_K8S_SCRIPT=./scripts/local-k8s-gpu.sh ./scripts/k8s.sh apply k8s/inference/profiles/transformers-base-gpu.yaml
```

The `experiment` and `inference-distributed` charts include their namespaces. `experiment/scenarios/` contains kubectl patches for experiments and is excluded from rendering. To switch PD topologies, use `make pd-deploy PD_MODE=aggregated` or `PD_MODE=disaggregated`; the script releases old GPU slots before applying the selected profile.

`make render` and `make deploy` accept the same `VARIANT`, `DEVICE` and `IMAGE_TAG` as image build commands. Benchmark `--manifests` accepts a values file inside a chart or a chart directory. Custom plain manifest files and directories are also supported.

```sh
make render VARIANT=transformers-enhanced-cache DEVICE=gpu
make deploy VARIANT=transformers-base IMAGE_TAG=0.1.0
./scripts/k8s.sh delete k8s/experiment/profiles/hpa-transformers.yaml
```

Deleting an experiment profile also deletes its namespace and PVCs. Export results before cleanup.

## Configuration

Change shared defaults in the chart, and workload differences in the profile. Additional `-f` files and `--set` options follow the profile argument. Lists such as `container.args` and `pod.volumes` replace the whole list.

```sh
./scripts/render-k8s.sh k8s/inference/profiles/transformers-base-cpu.yaml --set-string container.image=local/transformers-base:test
./scripts/render-k8s.sh k8s/inference-distributed/profiles/mps-4-disaggregated.yaml

# Equivalent direct Helm rendering
./.bin/helm template inference-test k8s/inference -f k8s/inference/profiles/transformers-base-cpu.yaml
```

Prometheus rules, Grafana dashboards, provisioning and AIPerf scripts are in [experiment/files](../../k8s/experiment/files/). Experiment ConfigMap names are fixed. Stop the experiment, apply changed configuration and restart its consumer. An AIPerf Deployment with zero replicas reads it on the next run.

```sh
./scripts/k8s.sh apply k8s/experiment/profiles/hpa-transformers.yaml --show-only templates/prometheus-config-configmap.yaml
./scripts/local-k8s.sh kubectl -n hpa-test-transformers rollout restart deployment/prometheus
./scripts/local-k8s.sh kubectl -n hpa-test-transformers rollout status deployment/prometheus
```

PD settings use a content hash in the ConfigMap name so changes update worker references. The HPA results collector reads queries from the deployed `grafana-dashboard` ConfigMap.

## Verification

```sh
./.bin/helm lint k8s/*
python3 -m unittest discover -s tests -p 'test_helm_manifests.py'
sh tests/test-aiperf-manifests.sh
sh tests/test-hpa-manifests-llamacpp.sh
sh tests/test-hpa-manifests-transformers.sh
```

Manifest tests use the existing PyYAML test dependency. `sh tests/test-transformers-manifests.sh` additionally validates through the local kubeconfig and kubectl.
