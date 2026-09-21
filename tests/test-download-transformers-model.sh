#!/bin/sh
set -eu

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
sandbox=$(mktemp -d "${TMPDIR:-/tmp}/download-transformers-model-test.XXXXXX")
trap 'rm -rf "$sandbox"' 0
trap 'exit 130' INT
trap 'exit 143' TERM
mkdir -p "$sandbox/scripts" "$sandbox/config/models" "$sandbox/bin" "$sandbox/fixtures"
cp "$ROOT/scripts/download-transformers-model.sh" "$sandbox/scripts/"
export MODEL_FIXTURES="$sandbox/fixtures" CURL_TRACE="$sandbox/curl-trace"
checksums="$sandbox/config/models/smollm2-135m-transformers.sha256"
for file in model.safetensors tokenizer_config.json; do
    printf 'fixture for %s\n' "$file" > "$MODEL_FIXTURES/$file"
    if command -v sha256sum >/dev/null 2>&1; then
        digest=$(sha256sum "$MODEL_FIXTURES/$file")
    else
        digest=$(shasum -a 256 "$MODEL_FIXTURES/$file")
    fi
    printf '%s  %s\n' "${digest%% *}" "$file" >> "$checksums"
done
cat > "$sandbox/config/models/smollm2-135m-transformers.env" <<'EOF_CONFIG'
MODEL_ID=example/model
MODEL_REVISION=test-commit
MODEL_DIRECTORY=model/weights
EOF_CONFIG
cat > "$sandbox/bin/curl" <<'EOF_CURL'
#!/bin/sh
set -eu
previous=
for arg in "$@"; do
    if [ "$previous" = --output ]; then output=$arg; fi
    previous=$arg
done
file=${arg##*/}
printf '%s\n' "$arg" >> "$CURL_TRACE"
if [ "${MOCK_FAIL:-}" = "$file" ]; then
    printf 'partial' > "$output"
    exit 18
fi
if [ "${MOCK_CORRUPT:-}" = "$file" ]; then
    printf 'corrupt' > "$output"
else
    cp "$MODEL_FIXTURES/$file" "$output"
fi
EOF_CURL
chmod +x "$sandbox/bin/curl"
export PATH="$sandbox/bin:$PATH" LOCAL_K8S_MODELS_DIR="$sandbox/models with spaces"
script="$sandbox/scripts/download-transformers-model.sh"
target="$LOCAL_K8S_MODELS_DIR/model/weights"
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
reject() { if sh "$script" > "$sandbox/output" 2>&1; then fail 'Unexpected success'; fi; }

MOCK_FAIL=tokenizer_config.json; export MOCK_FAIL
reject
[ ! -d "$target" ] || fail 'Incomplete model was exposed'
[ -f "$target.part/model.safetensors" ] || fail 'Verified progress was lost'
unset MOCK_FAIL
: > "$CURL_TRACE"
sh "$script" > "$sandbox/output"
[ "$(wc -l < "$CURL_TRACE" | tr -d ' ')" -eq 1 ] || fail 'Verified file was downloaded again'
grep -Fq '/resolve/test-commit/tokenizer_config.json' "$CURL_TRACE" || fail 'Revision is not pinned'
[ ! -d "$target.part" ] || fail 'Staging directory remains'
for file in model.safetensors tokenizer_config.json; do cmp "$target/$file" "$MODEL_FIXTURES/$file"; done
: > "$CURL_TRACE"
sh "$script" > "$sandbox/output"
[ ! -s "$CURL_TRACE" ] || fail 'Existing model was downloaded again'
printf 'corrupt' > "$target/model.safetensors"
reject
[ ! -s "$CURL_TRACE" ] || fail 'Corrupt existing model was overwritten'
rm "$target/tokenizer_config.json"
reject
rm -r "$target"
MOCK_CORRUPT=model.safetensors; export MOCK_CORRUPT
reject
[ ! -d "$target" ] || fail 'Corrupt model was exposed'
[ ! -f "$target.part/model.safetensors.part" ] || fail 'Corrupt download was retained'
unset MOCK_CORRUPT
sh "$script" > "$sandbox/output"
[ -f "$target/tokenizer_config.json" ] || fail 'Retry failed'
printf 'PASS: model checksums, atomic publication, retries, and offline reuse\n'
