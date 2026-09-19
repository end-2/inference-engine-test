#!/bin/sh
set -eu

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
SCRIPT="$ROOT/scripts/local-k8s.sh"
test_dir=$(mktemp -d "${TMPDIR:-/tmp}/local-k8s-smoke.XXXXXX")
export LOCAL_K8S_STATE_DIR="$test_dir/state"
CLUSTER_NAME="local-k8s-smoke-$(date +%s)-$$"
export CLUSTER_NAME
SMOKE_IMAGE=${SMOKE_IMAGE:-docker.io/library/busybox:1.37.0}

cleanup() {
    result=$?
    trap - 0
    if [ "$result" -ne 0 ]; then
        "$SCRIPT" logs "$test_dir/logs" || true
    fi
    if "$SCRIPT" down; then
        if [ "$result" -eq 0 ]; then
            rm -rf "$test_dir"
        else
            printf 'Test diagnostics: %s\n' "$test_dir" >&2
        fi
    else
        printf 'Cleanup failed. Retry with CLUSTER_NAME=%s LOCAL_K8S_STATE_DIR=%s\n' \
            "$CLUSTER_NAME" "$LOCAL_K8S_STATE_DIR" >&2
        result=1
    fi
    exit "$result"
}
trap cleanup 0
trap 'exit 130' INT
trap 'exit 143' TERM

"$SCRIPT" up
"$SCRIPT" up
"$SCRIPT" status
"$SCRIPT" test
provider=$(cat "$LOCAL_K8S_STATE_DIR/$CLUSTER_NAME/provider")
"$provider" pull "$SMOKE_IMAGE"
"$SCRIPT" load-image "$SMOKE_IMAGE"
"$SCRIPT" kubectl run dns-check --image="$SMOKE_IMAGE" --image-pull-policy=Never \
    --restart=Never --command -- sh -ec 'nslookup kubernetes.default.svc.cluster.local'
"$SCRIPT" kubectl wait --for=jsonpath='{.status.phase}'=Succeeded pod/dns-check --timeout=120s
"$SCRIPT" kubectl logs dns-check
printf 'PASS: real cluster readiness, reuse, image loading, and DNS\n'
