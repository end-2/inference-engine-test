#!/bin/sh
set -eu

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
sandbox=$(mktemp -d "${TMPDIR:-/tmp}/download-model-test.XXXXXX")
trap 'rm -rf "$sandbox"' 0
trap 'exit 130' INT
trap 'exit 143' TERM
mkdir -p "$sandbox/scripts" "$sandbox/config/models" "$sandbox/bin"
cp "$ROOT/scripts/download-model.sh" "$sandbox/scripts/"
export MODEL_FIXTURE="$sandbox/fixture" CURL_TRACE="$sandbox/curl-trace"
printf 'test model\n' > "$MODEL_FIXTURE"
if command -v sha256sum >/dev/null 2>&1; then
    digest=$(sha256sum "$MODEL_FIXTURE")
else
    digest=$(shasum -a 256 "$MODEL_FIXTURE")
fi
cat > "$sandbox/config/models/qwen2.5-0.5b-gguf.env" <<EOF_CONFIG
MODEL_ID=example/model
MODEL_FILE=model.gguf
MODEL_REVISION=test-commit
MODEL_SHA256=${digest%% *}
MODEL_DIRECTORY=test
EOF_CONFIG
cat > "$sandbox/bin/curl" <<'EOF_CURL'
#!/bin/sh
set -eu
printf '%s\n' "$@" >> "$CURL_TRACE"
previous=
for arg in "$@"; do
    if [ "$previous" = --output ]; then output=$arg; fi
    previous=$arg
done
if [ "${MOCK_FAIL:-0}" = 1 ]; then
    printf 'partial' > "$output"
    exit 18
fi
if [ "${MOCK_CORRUPT:-0}" = 1 ]; then
    printf 'corrupt' > "$output"
else
    cp "$MODEL_FIXTURE" "$output"
fi
EOF_CURL
chmod +x "$sandbox/bin/curl"
export PATH="$sandbox/bin:$PATH" LOCAL_K8S_MODELS_DIR="$sandbox/models with spaces"
script="$sandbox/scripts/download-model.sh"
target="$LOCAL_K8S_MODELS_DIR/test/model.gguf"
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
reject() { if sh "$script" > "$sandbox/output" 2>&1; then fail 'Unexpected success'; fi; }

MOCK_FAIL=1; export MOCK_FAIL
reject
[ -f "$target.part" ] && [ ! -f "$target" ] || fail 'Partial download must stay resumable'
unset MOCK_FAIL
sh "$script" > "$sandbox/output"
cmp "$target" "$MODEL_FIXTURE"
grep -Fq '/resolve/test-commit/model.gguf' "$CURL_TRACE" || fail 'Revision is not pinned'
: > "$CURL_TRACE"
sh "$script" > "$sandbox/output"
[ ! -s "$CURL_TRACE" ] || fail 'Valid existing file was downloaded again'
printf 'corrupt' > "$target"
reject
[ ! -s "$CURL_TRACE" ] || fail 'Corrupt existing file was overwritten'
rm "$target"
MOCK_CORRUPT=1; export MOCK_CORRUPT
reject
[ ! -f "$target" ] && [ ! -f "$target.part" ] || fail 'Corrupt download was retained'
printf 'PASS: model checksum, pinned revision, existing files, and resumable downloads\n'
