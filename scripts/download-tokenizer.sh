#!/bin/sh
# Stage and verify the complete tokenizer before exposing its final directory.
set -eu
umask 022

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
# shellcheck source-path=SCRIPTDIR
# shellcheck source=../config/models/qwen2.5-0.5b-tokenizer.env
. "$ROOT/config/models/qwen2.5-0.5b-tokenizer.env"
checksums="$ROOT/config/models/qwen2.5-0.5b-tokenizer.sha256"

die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
[ "$#" -eq 0 ] || die "Usage: $0 (LOCAL_K8S_MODELS_DIR overrides .models)"
if command -v sha256sum >/dev/null 2>&1; then
    hasher=sha256sum
elif command -v shasum >/dev/null 2>&1; then
    hasher=shasum
else
    die "Missing sha256sum or shasum."
fi

verify() {
    [ -f "$1" ] || return 1
    if [ "$hasher" = sha256sum ]; then
        digest=$(sha256sum "$1")
    else
        digest=$(shasum -a 256 "$1")
    fi
    [ "${digest%% *}" = "$2" ]
}

models_dir=${LOCAL_K8S_MODELS_DIR:-$ROOT/.models}
case $models_dir in *:*) die "LOCAL_K8S_MODELS_DIR must not contain a colon." ;; esac
mkdir -p "$models_dir"
models_dir=$(CDPATH='' cd -- "$models_dir" && pwd)
target="$models_dir/$TOKENIZER_DIRECTORY"

if [ -d "$target" ]; then
    while read -r expected file; do
        verify "$target/$file" "$expected" || \
            die "Missing file or checksum mismatch: $target/$file. Move $target aside and rerun."
    done < "$checksums"
    printf 'Tokenizer ready: %s\n' "$target"
    exit 0
fi

command -v curl >/dev/null 2>&1 || die "Missing curl."
staging="$target.part"
mkdir -p "$staging"
while read -r expected file; do
    if verify "$staging/$file" "$expected"; then
        continue
    fi
    printf 'Downloading %s at %s: %s\n' "$TOKENIZER_ID" "$TOKENIZER_REVISION" "$file"
    curl --fail --location --silent --show-error --retry 3 \
        --connect-timeout 15 --max-time 300 \
        --output "$staging/$file.part" \
        "https://huggingface.co/$TOKENIZER_ID/resolve/$TOKENIZER_REVISION/$file"
    if ! verify "$staging/$file.part" "$expected"; then
        rm -f "$staging/$file.part"
        die "Downloaded tokenizer checksum mismatch: $file. Rerun the download."
    fi
    mv "$staging/$file.part" "$staging/$file"
done < "$checksums"
mv "$staging" "$target"
printf 'Tokenizer ready: %s\n' "$target"
