#!/bin/sh
# Shared cluster selection for GPU lifecycle and image loaders.
GPU_SHARING=${GPU_SHARING:-none}
case $GPU_SHARING in
    none)
        GPU_CLUSTER_DEFAULT=local-k8s-gpu
        GPU_RESOURCE=nvidia.com/gpu
        GPU_REPLICAS=1
        ;;
    mps)
        MPS_REPLICAS=${MPS_REPLICAS:-2}
        case $MPS_REPLICAS in
            2) GPU_CLUSTER_DEFAULT=local-k8s-gpu-mps; GPU_MPS_CONFIG=mps.yaml ;;
            4) GPU_CLUSTER_DEFAULT=local-k8s-gpu-mps4; GPU_MPS_CONFIG=mps-4.yaml ;;
            *) die "MPS_REPLICAS must be 2 or 4" ;;
        esac
        GPU_RESOURCE=nvidia.com/gpu.shared
        GPU_REPLICAS=$MPS_REPLICAS
        ;;
    *) die "GPU_SHARING must be none or mps" ;;
esac
CLUSTER_NAME=${CLUSTER_NAME:-$GPU_CLUSTER_DEFAULT}
case $CLUSTER_NAME in
    *[!a-z0-9-]*|''|-*|*-) die "CLUSTER_NAME must contain lowercase letters, digits, or interior hyphens" ;;
esac
[ "${#CLUSTER_NAME}" -le 63 ] || die "CLUSTER_NAME must be at most 63 characters"
[ "$CLUSTER_NAME" != local-k8s ] || die "GPU cluster name must differ from the CPU cluster"
export CLUSTER_NAME GPU_SHARING GPU_RESOURCE GPU_REPLICAS GPU_MPS_CONFIG MPS_REPLICAS
