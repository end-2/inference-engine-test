#!/bin/sh
# Switch the selected comparison topology after releasing its MPS slots.
set -eu
ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
[ "$#" -eq 1 ] || die "Usage: $0 aggregated|disaggregated"
mode=$1
case $mode in aggregated|disaggregated) ;; *) die "Unknown PD mode: $mode" ;; esac
GPU_SHARING=${GPU_SHARING:-mps}
# shellcheck source=scripts/lib/gpu-settings.sh
. "$ROOT/scripts/lib/gpu-settings.sh"
[ "$GPU_SHARING" = mps ] || die "PD comparison requires GPU_SHARING=mps"
# shellcheck source=scripts/lib/pd-settings.sh
. "$ROOT/scripts/lib/pd-settings.sh"
k() { "$ROOT/scripts/local-k8s-gpu.sh" kubectl "$@"; }
# Fail on invalid values before releasing the active topology's GPU slots.
rendered=$(mktemp -d "${TMPDIR:-/tmp}/pd-manifests.XXXXXX")
trap 'rm -rf "$rendered"' 0
trap 'exit 130' INT
trap 'exit 143' TERM
values="$PD_VALUES_PREFIX-$mode.yaml"
"$ROOT/scripts/render-k8s.sh" "$values" > "$rendered/resources.yaml"
"$ROOT/scripts/render-k8s.sh" "$values" --show-only templates/namespace.yaml > "$rendered/namespace.yaml"
slots=$(k get nodes -l nvidia.com/mps.capable=true -o 'jsonpath={.items[*].status.allocatable.nvidia\.com/gpu\.shared}')
[ "$slots" = "$GPU_REPLICAS" ] || die "Expected one worker with $GPU_REPLICAS MPS slots; select the matching MPS cluster"
k apply -f "$rendered/namespace.yaml"
active=$(k -n "$PD_NAMESPACE" get jobs -l app=pd-benchmark -o 'jsonpath={.items[*].status.active}')
case $active in *[1-9]*) die "A PD benchmark is running; wait for it before switching modes" ;; esac
k -n "$PD_NAMESPACE" delete deployment pd-router pd-prefill pd-decode --ignore-not-found --wait=true
k -n "$PD_NAMESPACE" delete statefulset pd-aggregate pd-decode --ignore-not-found --wait=true
k -n "$PD_NAMESPACE" wait --for=delete pod -l app.kubernetes.io/part-of=pd-comparison --timeout=180s
k apply -f "$rendered/resources.yaml"
if [ "$PD_SCHEDULER" = token-budget ]; then
    if [ "$mode" = aggregated ]; then
        k -n "$PD_NAMESPACE" set env statefulset/pd-aggregate --containers=worker TOKEN_BUDGET="${PD_TOKEN_BUDGET:-256}"
    else
        k -n "$PD_NAMESPACE" set env deployment/pd-prefill "$PD_DECODE_WORKLOAD" --containers=worker TOKEN_BUDGET="${PD_TOKEN_BUDGET:-256}"
    fi
fi
if [ "$mode" = aggregated ]; then
    k -n "$PD_NAMESPACE" rollout status statefulset/pd-aggregate --timeout=300s
else
    k -n "$PD_NAMESPACE" rollout status deployment/pd-prefill --timeout=300s
    k -n "$PD_NAMESPACE" rollout status "$PD_DECODE_WORKLOAD" --timeout=300s
fi
k -n "$PD_NAMESPACE" rollout status deployment/pd-router --timeout=300s
printf 'PD comparison ready: %s, %s MPS slots, service pd-router in namespace %s\n' "$mode" "$GPU_REPLICAS" "$PD_NAMESPACE"
