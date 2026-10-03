#!/bin/sh
# Keep namespaces and workload selection separate for the two MPS profiles.
case $GPU_REPLICAS in
    2)
        PD_NAMESPACE=pd-comparison
        PD_VALUES_PREFIX="$ROOT/k8s/inference-distributed/profiles/mps-2"
        PD_DECODE_WORKLOAD=deployment/pd-decode
        ;;
    4)
        PD_NAMESPACE=pd-comparison-4
        PD_VALUES_PREFIX="$ROOT/k8s/inference-distributed/profiles/mps-4"
        PD_DECODE_WORKLOAD=statefulset/pd-decode
        ;;
    *) die "PD comparison requires two or four MPS slots" ;;
esac
PD_SCHEDULER=${PD_SCHEDULER:-serial}
case $PD_SCHEDULER in
    serial) ;;
    token-budget)
        [ "$GPU_REPLICAS" = 4 ] || die "The token-budget profile requires four MPS slots"
        PD_NAMESPACE=pd-comparison-4-scheduled
        PD_VALUES_PREFIX="$ROOT/k8s/inference-distributed/profiles/mps-4-scheduled"
        case ${PD_TOKEN_BUDGET:-256} in ''|*[!0-9]*|0) die "PD_TOKEN_BUDGET must be a positive integer" ;; esac
        [ "${PD_TOKEN_BUDGET:-256}" -gt 0 ] || die "PD_TOKEN_BUDGET must be a positive integer"
        ;;
    *) die "Unknown PD_SCHEDULER: $PD_SCHEDULER" ;;
esac
export PD_NAMESPACE PD_VALUES_PREFIX PD_DECODE_WORKLOAD
