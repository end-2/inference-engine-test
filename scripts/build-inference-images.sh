#!/bin/sh
# Build the CPU inference image. The GGUF model stays outside the image
# and is mounted from the kind node at deploy time.
set -eu
umask 022

die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
[ "$#" -le 1 ] || die "Usage: $0 [base|base-metric|enhanced-batch|enhanced-cache]"
variant=${1:-base}
case "$variant" in
  base|base-metric|enhanced-batch|enhanced-cache) ;;
  *) die "Unknown variant: $variant" ;;
esac
command -v docker >/dev/null 2>&1 || die "Missing docker."

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
tag=${IMAGE_TAG:-0.1.0}
docker build --no-cache --target "$variant" -t "local/llama-$variant:$tag" "$ROOT/src"
printf 'Image ready: local/llama-%s:%s\n' "$variant" "$tag"
