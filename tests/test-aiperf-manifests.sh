#!/bin/sh
set -eu

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
BENCH="$ROOT/k8s/aiperf"
# shellcheck source=../config/models/qwen2.5-0.5b-gguf.env
. "$ROOT/config/models/qwen2.5-0.5b-gguf.env"
# shellcheck source=../config/models/qwen2.5-0.5b-tokenizer.env
. "$ROOT/config/models/qwen2.5-0.5b-tokenizer.env"

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
if [ -x "$ROOT/.bin/kubectl" ]; then
    KUBECTL="$ROOT/.bin/kubectl"
elif command -v kubectl >/dev/null 2>&1; then
    KUBECTL=kubectl
else
    fail "Missing kubectl. Run ./scripts/local-k8s.sh install or add it to PATH."
fi

rendered=$(mktemp -d "${TMPDIR:-/tmp}/aiperf-manifests.XXXXXX")
trap 'rm -rf "$rendered"' 0
trap 'exit 130' INT
trap 'exit 143' TERM
"$KUBECTL" kustomize "$BENCH" > "$rendered/all.yaml" || fail 'kustomize failed'
[ "$(grep -c '^kind: Job$' "$rendered/all.yaml")" -eq 1 ] || fail 'Sweep must use one Job'
awk 'BEGIN { RS="---" } /kind: Job/ { print }' "$rendered/all.yaml" > "$rendered/job.yaml"
out="$rendered/job.yaml"

grep -Fq 'image: local/aiperf:' "$out" || fail 'Missing aiperf image'
grep -Fq 'imagePullPolicy: Never' "$out" || fail 'Local image must use Never'
model=$(awk '/name: MODEL_ID$/ { getline; print $2 }' "$out")
[ "$model" = "$SERVED_MODEL_NAME" ] || fail 'Benchmark model does not match served model'
[ "$TOKENIZER_ID" = "$SERVED_MODEL_NAME" ] || fail 'Tokenizer does not match served model'
if grep -Fq 'nvidia.com' "$rendered/all.yaml"; then fail 'Benchmark must remain CPU-only'; fi
[ "$(grep -Fc 'cpu: "1"' "$out")" -eq 2 ] || fail 'CPU requests must equal limits'
[ "$(grep -Fc 'memory: 1Gi' "$out")" -eq 2 ] || fail 'Memory requests must equal limits'

values=$(awk '/name: CONCURRENCIES$/ { getline; print $2 }' "$out" | tr -d '"')
[ "$values" = '1,2,4,8' ] || fail 'Unexpected sweep values'
argument=$(awk '/- --concurrency$/ { getline; print $2 }' "$out")
[ "$argument" = '$(CONCURRENCIES)' ] || fail 'Concurrency list is not passed to AIPerf'
argument=$(awk '/- --workers-max$/ { getline; print $2 }' "$out" | tr -d '"')
[ "$argument" = 1 ] || fail 'Keep client worker count fixed across variations'
grep -Fq -- '--parameter-sweep-same-seed' "$out" || fail 'Sweep must reuse the dataset seed'
argument=$(awk '/- --request-count$/ { getline; print $2 }' "$out" | tr -d '"')
[ "$argument" = 100 ] || fail 'Each condition must measure 100 requests'
grep -Fq -- 'ignore_eos:true' "$out" || fail 'Fixed-length measurements must suppress EOS'
argument=$(awk '/- --tokenizer$/ { getline; print $2 }' "$out")
[ "$argument" = /tokenizer ] || fail 'Tokenizer must use its local mount'
grep -Fq "path: /models/$TOKENIZER_DIRECTORY" "$out" || fail 'Wrong tokenizer host path'
grep -Fq 'type: Directory' "$out" || fail 'Missing tokenizer must not create an empty directory'
awk '/- mountPath:/ { tokenizer=($3 == "/tokenizer") }
     tokenizer && /readOnly: true/ { ro=1 } END { exit !ro }' "$out" || \
    fail 'Tokenizer must be mounted read-only'
grep -Fq '/results/$(POD_NAME)' "$out" || fail 'Separate results by Pod'
deadline=$(awk '/activeDeadlineSeconds:/ { print $2 }' "$out")
[ "$deadline" -ge 14400 ] || fail 'Deadline must accommodate all four variations'

model=$(awk '/- --served-model-name$/ { getline; print $2 }' "$ROOT/k8s/llama-base/deployment.yaml")
[ "$model" = "$SERVED_MODEL_NAME" ] || fail 'Deployment model does not match model config'
grep -Fq 'kind: PersistentVolumeClaim' "$rendered/all.yaml" || fail 'Missing results PVC'
grep -Fq 'kind: Pod' "$rendered/all.yaml" || fail 'Missing results reader Pod'
printf 'PASS: single sweep Job, fixed seed, local tokenizer, results, and CPU resources\n'
