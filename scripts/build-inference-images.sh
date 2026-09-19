#!/bin/sh
# Build the CPU inference image. The GGUF model stays outside the image
# and is mounted from the kind node at deploy time.
set -eu
umask 022

die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
[ "$#" -le 1 ] || die "Usage: $0 [base]"
variant=${1:-base}
[ "$variant" = "base" ] || die "Unknown variant: $variant (only 'base' exists)."
command -v docker >/dev/null 2>&1 || die "Missing docker."

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
tag=${IMAGE_TAG:-0.1.0}
docker build --no-cache -t "local/llama-base:$tag" "$ROOT/src/base"
printf 'Image ready: local/llama-base:%s\n' "$tag"
