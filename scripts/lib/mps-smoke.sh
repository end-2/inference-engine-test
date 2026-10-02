#!/bin/sh

cleanup_mps_smoke() {
    kube delete job gpu-mps-smoke --ignore-not-found=true --wait=true --timeout=30s >/dev/null 2>&1 || true
    kube delete configmap gpu-mps-smoke --ignore-not-found=true >/dev/null 2>&1 || true
}

finish_mps_smoke() {
    smoke_status=$1
    cleanup_mps_smoke
    exit "$smoke_status"
}

mps_smoke() {
    cleanup_mps_smoke
    trap 'finish_mps_smoke $?' 0
    trap 'exit 130' INT
    trap 'exit 143' TERM
    kube create configmap gpu-mps-smoke --from-file="probe.py=$ROOT/scripts/check-mps-cuda.py"
    smoke_manifest=$(kube patch --local -f "$ROOT/config/cluster/mps-smoke.yaml" --type=merge \
        -p "{\"spec\":{\"parallelism\":$GPU_REPLICAS,\"completions\":$GPU_REPLICAS}}" -o yaml)
    printf '%s\n' "$smoke_manifest" | kube apply -f -
    attempts=0
    while :; do
        smoke_pods=$(kube get pods -l job-name=gpu-mps-smoke -o name)
        smoke_count=$(printf '%s\n' "$smoke_pods" | awk 'NF {n++} END {print n+0}')
        [ "$smoke_count" != "$GPU_REPLICAS" ] || break
        attempts=$((attempts + 1))
        [ "$attempts" -lt 30 ] || die "MPS smoke Job did not create $GPU_REPLICAS Pods"
        sleep 2
    done
    # All contexts stay alive until the controller releases the Pods.
    for smoke_pod in $smoke_pods; do
        if ! kube wait --for=condition=Ready "$smoke_pod" --timeout=180s; then
            kube describe "$smoke_pod" >&2 || true
            kube logs "$smoke_pod" >&2 || true
            die "MPS CUDA smoke failed; $GPU_REPLICAS unused shared GPU resources are required"
        fi
    done
    servers=$(mps_control get_server_list)
    [ -n "$servers" ] || die "No MPS server accepted the CUDA smoke clients"
    all_clients=false
    for server in $servers; do
        case $server in *[!0-9]*) die "Unexpected MPS server response: $server" ;; esac
        clients=$(mps_control "get_client_list $server")
        client_count=$(printf '%s\n' "$clients" | awk 'NF {n++} END {print n+0}')
        if [ "$client_count" = "$GPU_REPLICAS" ]; then all_clients=true; fi
    done
    [ "$all_clients" = true ] || die "The $GPU_REPLICAS CUDA Pods did not connect to the same MPS server"
    for smoke_pod in $smoke_pods; do
        kube exec "$smoke_pod" -- touch /tmp/mps-release
    done
    kube wait --for=condition=Complete job/gpu-mps-smoke --timeout=60s
    for smoke_pod in $smoke_pods; do kube logs "$smoke_pod"; done
    cleanup_mps_smoke
    trap - 0 INT TERM
    printf 'MPS smoke passed: %s concurrent CUDA clients on one MPS server\n' "$GPU_REPLICAS"
}
