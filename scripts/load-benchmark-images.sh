#!/bin/sh
set -eu
umask 077

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)

die() { printf 'Error: %s\n' "$*" >&2; exit 1; }

usage() {
    cat <<'EOF'
Usage: ./scripts/load-benchmark-images.sh

Environment:
  AIPERF_IMAGE_TAG  Image tag for the AIPerf benchmark image (default: 0.12.0)
  DEVICE            cpu or gpu (default: cpu)
  TMPDIR            Temporary directory for the image archive.
                    Default: .local-k8s/image-tmp in this repository.

Examples:
  ./scripts/load-benchmark-images.sh
  AIPERF_IMAGE_TAG=0.12.0 ./scripts/load-benchmark-images.sh
EOF
}

case ${1:-} in
    -h|--help|help) usage; exit 0 ;;
esac
[ "$#" -eq 0 ] || { usage >&2; die "load-benchmark-images.sh takes no arguments."; }

AIPERF_IMAGE_TAG=${AIPERF_IMAGE_TAG:-0.12.0}
case $AIPERF_IMAGE_TAG in
    ''|*[!a-zA-Z0-9_.-]*|.*|*-) die "AIPERF_IMAGE_TAG must be a valid docker tag." ;;
esac

image="local/aiperf:$AIPERF_IMAGE_TAG"
case ${DEVICE:-cpu} in
    cpu) cluster_name=${CLUSTER_NAME:-local-k8s}; cluster_script="$ROOT/scripts/local-k8s.sh" ;;
    gpu)
        . "$ROOT/scripts/lib/gpu-settings.sh"
        cluster_name=$CLUSTER_NAME; cluster_script="$ROOT/scripts/local-k8s-gpu.sh"
        ;;
    *) die "DEVICE must be cpu or gpu" ;;
esac

command -v docker >/dev/null 2>&1 || die "Missing docker."
docker image inspect "$image" >/dev/null 2>&1 || \
    die "Missing local image: $image. Build it first with ./scripts/build-benchmark-images.sh."

# no-cache for load: remove stale image from nodes before kind load
if [ "${DEVICE:-cpu}" = gpu ]; then
  nodes="$cluster_name-control-plane"
else
  nodes=$(kind get nodes --name "$cluster_name" 2>/dev/null)
fi
for node in $nodes; do
  docker exec "$node" crictl rmi "$image" >/dev/null 2>&1 || true
  docker exec "$node" ctr -n k8s.io images rm "$image" >/dev/null 2>&1 || true
done

# local-k8s.sh load-image stages a temporary archive under TMPDIR.
case ${TMPDIR:-} in
    '') TMPDIR="$ROOT/.local-k8s/image-tmp" ;;
    *) case $TMPDIR in *:*) die "TMPDIR must not contain a colon." ;; esac ;;
esac
(umask 022; mkdir -p "$TMPDIR")
export TMPDIR

if [ "${DEVICE:-cpu}" = gpu ]; then
  exec "$cluster_script" load-image-node "$cluster_name-control-plane" "$image"
fi
exec "$cluster_script" load-image "$image"
