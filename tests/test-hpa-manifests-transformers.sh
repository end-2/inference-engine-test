#!/bin/sh
set -eu

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
KUBECTL=${LOCAL_K8S_BIN_DIR:-$ROOT/.bin}/kubectl
if [ ! -x "$KUBECTL" ]; then KUBECTL=kubectl; fi
rendered=$(mktemp -d "${TMPDIR:-/tmp}/hpa-manifests.XXXXXX")
trap 'rm -rf "$rendered"' 0
trap 'exit 130' INT
trap 'exit 143' TERM
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }

"$KUBECTL" kustomize "$ROOT/k8s/availability-test-transformers" > "$rendered/availability.yaml"
"$KUBECTL" kustomize "$ROOT/k8s/hpa-test-transformers" > "$rendered/hpa.yaml"
"$KUBECTL" kustomize "$ROOT/k8s/metrics-server" > "$rendered/metrics.yaml"
# Namespace and RBAC rewrites must not leak into the availability experiment.
if grep -Fq 'availability-test-transformers' "$rendered/hpa.yaml"; then fail 'Stale availability namespace or RBAC'; fi
grep -Fq 'name: hpa-node-metrics-transformers' "$rendered/hpa.yaml" || fail 'Missing isolated node RBAC'
grep -Fq 'horizontalpodautoscalers' "$rendered/hpa.yaml" || fail 'Missing HPA metric permission'
grep -Fq 'kube_horizontalpodautoscaler_status_target_metric' "$rendered/hpa.yaml" || fail 'Missing CPU dashboard'

awk 'BEGIN { RS="---" } /kind: Deployment/ && /name: transformers-base-metric/ { print }' "$rendered/hpa.yaml" > "$rendered/engine.yaml"
if grep -q '^  replicas:' "$rendered/engine.yaml"; then fail 'HPA must own engine replicas'; fi
[ "$(grep -c 'cpu: "2"' "$rendered/engine.yaml")" -eq 2 ] || fail 'Engine CPU requests/limits changed'
[ "$(grep -c 'memory: 2Gi' "$rendered/engine.yaml")" -eq 2 ] || fail 'Engine memory requests/limits changed'
awk 'BEGIN { RS="---" } /kind: Deployment/ && /name: aiperf\n/ { print }' "$rendered/hpa.yaml" > "$rendered/load.yaml"
grep -q '^  replicas: 0$' "$rendered/load.yaml" || fail 'Load must start stopped'
concurrency=$(awk '/- --concurrency$/ { getline; print $2 }' "$rendered/load.yaml" | tr -d '"')
[ "$concurrency" = 8 ] || fail 'Wrong AIPerf concurrency'
grep -Fq -- '--connection-reuse-strategy' "$rendered/load.yaml" || fail 'Missing connection distribution setting'
awk 'BEGIN { RS="---" } /kind: HorizontalPodAutoscaler/ { print }' "$rendered/hpa.yaml" > "$rendered/autoscaler.yaml"
grep -Fq 'apiVersion: autoscaling/v2' "$rendered/autoscaler.yaml" || fail 'Wrong HPA API'
grep -Fq 'averageUtilization: 50' "$rendered/autoscaler.yaml" || fail 'Wrong CPU target'
grep -Fq 'minReplicas: 1' "$rendered/autoscaler.yaml" || fail 'Wrong minimum replicas'
grep -Fq 'maxReplicas: 4' "$rendered/autoscaler.yaml" || fail 'Wrong maximum replicas'
[ "$(grep -c 'cpu: 100m' "$rendered/metrics.yaml")" -eq 2 ] || fail 'Metrics Server CPU requests must equal limits'
[ "$(grep -c 'memory: 200Mi' "$rendered/metrics.yaml")" -eq 2 ] || fail 'Metrics Server memory requests must equal limits'
grep -Fq -- '--kubelet-insecure-tls' "$rendered/metrics.yaml" || fail 'Missing kind kubelet TLS setting'
for manifest in "$rendered/availability.yaml" "$rendered/hpa.yaml"; do
  if grep -Eq 'llama_|llamacpp|Qwen|qwen' "$manifest"; then fail 'Stale backend or model reference'; fi
  [ "$(grep -c 'HuggingFaceTB/SmolLM2-135M-Instruct' "$manifest")" -eq 2 ] || fail 'Engine and AIPerf models must match'
  [ "$(grep -c 'path: /models/smollm2-135m' "$manifest")" -eq 2 ] || fail 'Weights and tokenizer must use the same snapshot'
  grep -Fq 'transformers_time_to_first_token_seconds_bucket' "$manifest" || fail 'Missing Transformers metrics'
  grep -Fq 'workload: engine' "$manifest" || fail 'Missing engine placement'
  grep -Fq 'workload: monitor' "$manifest" || fail 'Missing monitor placement'
done
threads=$(awk '/- --n-threads$/ { getline; print $2 }' "$rendered/engine.yaml" | tr -d '"')
[ "$threads" = 2 ] || fail 'Wrong PyTorch thread count'
printf 'PASS: Transformers model, tokenizer, metrics, HPA, namespace isolation, monitoring, load configuration, and resource guarantees\n'
