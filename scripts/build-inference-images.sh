#!/bin/sh
# Build the CPU inference image. Model weights stay outside the image
# and are mounted from the kind node at deploy time.
set -eu
umask 022

die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
[ "$#" -le 1 ] || die "Usage: $0 [base-llamacpp|base-metric-llamacpp|enhanced-batch-llamacpp|enhanced-cache-llamacpp|transformers-base|transformers-base-metric|transformers-enhanced-batch|transformers-enhanced-cache]"
variant=${1:-transformers-base}
case "$variant" in
  base-llamacpp|base-metric-llamacpp|enhanced-batch-llamacpp|enhanced-cache-llamacpp) image_name="$variant" ;;
  transformers-base|transformers-base-metric|transformers-enhanced-batch|transformers-enhanced-cache) image_name="$variant" ;;
  *) die "Unknown variant: $variant" ;;
esac
command -v docker >/dev/null 2>&1 || die "Missing docker."

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
tag=${IMAGE_TAG:-0.1.0}
docker build --no-cache --target "$variant" -t "local/$image_name:$tag" "$ROOT/src"
printf 'Image ready: local/%s:%s\n' "$image_name" "$tag"
