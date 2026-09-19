#!/bin/sh
# Load the CPU inference image into the kind nodes.
set -eu
umask 022

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)

die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
[ "$#" -le 1 ] || die "Usage: $0 [base|enhanced-batch|enhanced-cache]"
variant=${1:-base}
case "$variant" in
  base|enhanced-batch|enhanced-cache) ;;
  *) die "Unknown variant: $variant" ;;
esac

tag=${IMAGE_TAG:-0.1.0}
image="local/llama-$variant:$tag"
# no-cache for load: remove stale image from nodes before kind load
for node in $(kind get nodes --name "${CLUSTER_NAME:-local-k8s}" 2>/dev/null); do
  docker exec "$node" crictl rmi "$image" >/dev/null 2>&1 || true
  docker exec "$node" ctr -n k8s.io images rm "$image" >/dev/null 2>&1 || true
done
"$ROOT/scripts/local-k8s.sh" load-image "$image"
