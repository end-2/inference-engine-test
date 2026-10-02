> Korean version: [한국어](manifests-KR.md)

# Kubernetes Manifest Management

Each deployment directory under `k8s/` contains complete Kubernetes manifests. Edit the YAML in the directory directly and apply with `kubectl apply -f`. When changing shared model or experiment settings, apply the same change to the related directories.

## Applying

```sh
./scripts/local-k8s.sh kubectl apply -f k8s/transformers-base/
```

Availability and HPA tests create the namespace first.

```sh
./scripts/local-k8s.sh kubectl apply -f k8s/hpa-test-transformers/namespace.yaml
./scripts/local-k8s.sh kubectl apply -f k8s/hpa-test-transformers/
```

Files under `scenarios/` are patches used during experiments, so do not apply directories recursively with `-R`.

To delete deployment resources, run `kubectl delete -f` against the same deployment directory. Running it against a test directory also deletes namespaces and PVCs.

## Changing configuration

Prometheus configuration and rules, Grafana dashboards and provisioning settings, and AIPerf run scripts are defined in each directory's `*-configmap.yaml`. ConfigMap names are fixed, and applying a configuration does not automatically restart Deployment Pods.

Stop the experiment, apply the ConfigMap, and restart the Deployment that uses it. After changing the HPA test Prometheus configuration, run:

```sh
./scripts/local-k8s.sh kubectl apply -f k8s/hpa-test-transformers/prometheus-config-configmap.yaml
./scripts/local-k8s.sh kubectl -n hpa-test-transformers rollout restart deployment/prometheus
./scripts/local-k8s.sh kubectl -n hpa-test-transformers rollout status deployment/prometheus
```

Apply Grafana settings to `deployment/grafana`, and AIPerf run scripts to `deployment/aiperf`. An AIPerf instance with 0 replicas reads the new configuration on the next run.

The HPA results collector reads queries from the cluster's `grafana-dashboard` ConfigMap.

## Verification

Run from the repository root. The last check uses the local kubeconfig and kubectl.

```sh
sh tests/test-aiperf-manifests.sh
sh tests/test-hpa-manifests-llamacpp.sh
sh tests/test-hpa-manifests-transformers.sh
sh tests/test-transformers-manifests.sh
```
