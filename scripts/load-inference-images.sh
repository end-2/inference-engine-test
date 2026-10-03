#!/bin/sh
# Load the selected inference image into the kind nodes.
set -eu
umask 022

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
PATH="${LOCAL_K8S_BIN_DIR:-$ROOT/.bin}:$PATH"
export PATH

die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
[ "$#" -le 1 ] || die "Usage: $0 [base-llamacpp|base-metric-llamacpp|enhanced-batch-llamacpp|enhanced-cache-llamacpp|transformers-base|transformers-base-metric|transformers-enhanced-batch|transformers-enhanced-cache|transformers-mamba-base|transformers-mamba-cache|transformers-hybrid|transformers-pd]"
variant=${1:-transformers-base}
case "$variant" in
  base-llamacpp|base-metric-llamacpp|enhanced-batch-llamacpp|enhanced-cache-llamacpp) image_name="$variant" ;;
  transformers-base|transformers-base-metric|transformers-enhanced-batch|transformers-enhanced-cache|transformers-mamba-base|transformers-mamba-cache|transformers-hybrid|transformers-pd) image_name="$variant" ;;
  *) die "Unknown variant: $variant" ;;
esac

tag=${IMAGE_TAG:-0.1.0}
case ${DEVICE:-cpu} in
  cpu) image="local/$image_name:$tag"; cluster_script="$ROOT/scripts/local-k8s.sh"; cluster_name=${CLUSTER_NAME:-local-k8s} ;;
  gpu)
    . "$ROOT/scripts/lib/gpu-settings.sh"
    image="local/$image_name-gpu:$tag"; cluster_script="$ROOT/scripts/local-k8s-gpu.sh"; cluster_name=$CLUSTER_NAME
    ;;
  *) die "DEVICE must be cpu or gpu" ;;
esac
# no-cache for load: remove stale image from nodes before kind load
if [ "${DEVICE:-cpu}" = gpu ]; then
  nodes="$cluster_name-worker"
else
  nodes=$(kind get nodes --name "$cluster_name")
fi
for node in $nodes; do
  docker exec "$node" crictl rmi "$image" >/dev/null 2>&1 || true
  docker exec "$node" ctr -n k8s.io images rm "$image" >/dev/null 2>&1 || true
done
if [ "${DEVICE:-cpu}" = gpu ]; then
  exec "$cluster_script" load-image-node "$nodes" "$image"
fi
"$cluster_script" load-image "$image"
