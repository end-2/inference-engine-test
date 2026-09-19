#!/bin/sh
# Load the CPU inference image into the kind nodes.
set -eu
umask 022

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)

die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
[ "$#" -le 1 ] || die "Usage: $0 [base]"
variant=${1:-base}
[ "$variant" = "base" ] || die "Unknown variant: $variant (only 'base' exists)."

tag=${IMAGE_TAG:-0.1.0}
"$ROOT/scripts/local-k8s.sh" load-image "local/llama-base:$tag"
