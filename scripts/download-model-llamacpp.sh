#!/bin/sh
# Download the pinned GGUF model file for node mounting and local runs.
set -eu
umask 022

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
# shellcheck source-path=SCRIPTDIR
# shellcheck source=../config/models/qwen2.5-0.5b-gguf-llamacpp.env
. "$ROOT/config/models/qwen2.5-0.5b-gguf-llamacpp.env"

die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
[ "$#" -eq 0 ] || die "Usage: $0 (LOCAL_K8S_MODELS_DIR overrides .models)"
command -v curl >/dev/null 2>&1 || die "Missing curl."
if command -v sha256sum >/dev/null 2>&1; then
    hasher=sha256sum
elif command -v shasum >/dev/null 2>&1; then
    hasher=shasum
else
    die "Missing sha256sum or shasum."
fi

verify() {
    if [ "$hasher" = sha256sum ]; then
        digest=$(sha256sum "$1")
    else
        digest=$(shasum -a 256 "$1")
    fi
    [ "${digest%% *}" = "$MODEL_SHA256" ]
}

models_dir=${LOCAL_K8S_MODELS_DIR:-$ROOT/.models}
case $models_dir in *:*) die "LOCAL_K8S_MODELS_DIR must not contain a colon." ;; esac
(umask 022; mkdir -p "$models_dir")
models_dir=$(CDPATH='' cd -- "$models_dir" && pwd)
model_dir="$models_dir/$MODEL_DIRECTORY"
(umask 022; mkdir -p "$model_dir")
target="$model_dir/$MODEL_FILE"

if [ -f "$target" ]; then
    verify "$target" || die "Checksum mismatch: $target. Move it aside and rerun the download."
    printf 'Model ready: %s\n' "$target"
    exit 0
fi

printf 'Downloading %s at %s: %s\n' "$MODEL_ID" "$MODEL_REVISION" "$MODEL_FILE"
curl --fail --location --silent --show-error --retry 3 \
    --connect-timeout 15 --max-time 3600 --continue-at - \
    --output "$target.part" \
    "https://huggingface.co/$MODEL_ID/resolve/$MODEL_REVISION/$MODEL_FILE"
if ! verify "$target.part"; then
    rm -f "$target.part"
    die "Downloaded model checksum mismatch; rerun the download."
fi
mv "$target.part" "$target"
printf 'Model ready: %s\n' "$target"
