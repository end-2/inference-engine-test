#!/bin/sh
# Build the selected inference image. Model weights stay outside the image
# and are mounted from the kind node at deploy time.
set -eu
umask 022

die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
[ "$#" -le 1 ] || die "Usage: $0 [base-llamacpp|base-metric-llamacpp|enhanced-batch-llamacpp|enhanced-cache-llamacpp|transformers-base|transformers-base-metric|transformers-enhanced-batch|transformers-enhanced-cache|transformers-mamba-base|transformers-mamba-cache]"
variant=${1:-transformers-base}
case "$variant" in
  base-llamacpp|base-metric-llamacpp|enhanced-batch-llamacpp|enhanced-cache-llamacpp) image_name="$variant" ;;
  transformers-base|transformers-base-metric|transformers-enhanced-batch|transformers-enhanced-cache|transformers-mamba-base|transformers-mamba-cache) image_name="$variant" ;;
  *) die "Unknown variant: $variant" ;;
esac
command -v docker >/dev/null 2>&1 || die "Missing docker."

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
tag=${IMAGE_TAG:-0.1.0}
case ${DEVICE:-cpu} in
  cpu) target=$variant; image="local/$image_name:$tag"; dockerfile="$ROOT/src/Dockerfile"; cache_flag=--no-cache ;;
  gpu) target="$variant-gpu"; image="local/$image_name-gpu:$tag"; dockerfile="$ROOT/src/Dockerfile.gpu"; cache_flag= ;;
  *) die "DEVICE must be cpu or gpu" ;;
esac
docker build ${cache_flag:+$cache_flag} -f "$dockerfile" --target "$target" -t "$image" "$ROOT/src"
printf 'Image ready: %s\n' "$image"
