#!/bin/sh
set -eu

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
BENCH="$ROOT/k8s/aiperf"
. "$ROOT/config/models/smollm2-135m-transformers.env"

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }

. "$ROOT/tests/lib/manifests.sh"

rendered=$(mktemp -d "${TMPDIR:-/tmp}/aiperf-manifests.XXXXXX")
trap 'rm -rf "$rendered"' 0
trap 'exit 130' INT
trap 'exit 143' TERM
read_manifests "$BENCH" > "$rendered/all.yaml" || fail 'Cannot read manifests'
[ "$(grep -c '^kind: Job$' "$rendered/all.yaml")" -eq 1 ] || fail 'Sweep must use one Job'
awk 'BEGIN { RS="---" } /kind: Job/ { print }' "$rendered/all.yaml" > "$rendered/job.yaml"
out="$rendered/job.yaml"

grep -Fq 'image: local/aiperf:' "$out" || fail 'Missing aiperf image'
grep -Fq 'imagePullPolicy: Never' "$out" || fail 'Local image must use Never'
model=$(awk '/name: MODEL_ID$/ { getline; print $2 }' "$out")
[ "$model" = "$SERVED_MODEL_NAME" ] || fail 'Benchmark model does not match served model'
api=$(awk '/name: API_URL$/ { getline; print $2 }' "$out")
[ "$api" = 'http://transformers-base:8000' ] || fail 'Wrong default inference Service'
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
grep -Fq "path: /models/$MODEL_DIRECTORY" "$out" || fail 'Wrong tokenizer host path'
grep -Fq 'type: Directory' "$out" || fail 'Missing tokenizer must not create an empty directory'
awk '/- mountPath:/ { tokenizer=($3 == "/tokenizer") }
     tokenizer && /readOnly: true/ { ro=1 } END { exit !ro }' "$out" || \
    fail 'Tokenizer must be mounted read-only'
grep -Fq '/results/$(POD_NAME)' "$out" || fail 'Separate results by Pod'
deadline=$(awk '/activeDeadlineSeconds:/ { print $2 }' "$out")
[ "$deadline" -ge 14400 ] || fail 'Deadline must accommodate all four variations'

model=$(awk '/- --served-model-name$/ { getline; print $2 }' "$ROOT/k8s/transformers-base/deployment.yaml")
[ "$model" = "$SERVED_MODEL_NAME" ] || fail 'Deployment model does not match model config'
grep -Fq 'kind: PersistentVolumeClaim' "$rendered/all.yaml" || fail 'Missing results PVC'
grep -Fq 'kind: Pod' "$rendered/all.yaml" || fail 'Missing results reader Pod'
entries=$(awk '/name: DATASET_ENTRIES$/ { getline; print $2 }' "$out" | tr -d '"')
[ "$entries" = 16 ] || fail 'Default dataset size must remain 16'
argument=$(awk '/- --num-dataset-entries$/ { getline; print $2 }' "$out")
[ "$argument" = '$(DATASET_ENTRIES)' ] || fail 'Dataset size must use its environment setting'

. "$ROOT/config/models/qwen2.5-0.5b-gguf-llamacpp.env"
. "$ROOT/config/models/qwen2.5-0.5b-tokenizer-llamacpp.env"
for profile_name in qwen2.5 32-qwen2.5 128-qwen2.5; do
    size=${profile_name%-qwen2.5}
    suffix="-$profile_name"
    if [ "$profile_name" = qwen2.5 ]; then size=16; fi
    read_manifests "$ROOT/k8s/aiperf-$profile_name" > "$rendered/profile.yaml" || fail "Cannot render profile $profile_name"
    [ "$(grep -c '^kind: Job$' "$rendered/profile.yaml")" -eq 1 ] || fail 'Each profile must use one Job'
    awk 'BEGIN { RS="---" } /kind: Job/ { print }' "$rendered/profile.yaml" > "$rendered/profile-job.yaml"
    profile="$rendered/profile-job.yaml"
    entries=$(awk '/name: DATASET_ENTRIES$/ { getline; print $2 }' "$profile" | tr -d '"')
    [ "$entries" = "$size" ] || fail "Wrong dataset size for profile $size"
    grep -Fq "name: aiperf$suffix" "$profile" || fail 'Each profile needs a distinct Job name'
    grep -Fq "claimName: aiperf-results$suffix" "$profile" || fail 'Job must use its profile results PVC'
    [ "$(grep -c "name: aiperf-results$suffix$" "$rendered/profile.yaml")" -eq 2 ] || fail 'Missing profile PVC or reader'
    model=$(awk '/name: MODEL_ID$/ { getline; print $2 }' "$profile")
    [ "$model" = "$SERVED_MODEL_NAME" ] || fail 'llama profile model must remain Qwen2.5'
    [ "$TOKENIZER_ID" = "$SERVED_MODEL_NAME" ] || fail 'llama tokenizer and model differ'
    grep -Fq "path: /models/$TOKENIZER_DIRECTORY" "$profile" || fail 'llama tokenizer path changed'
    grep -Fq 'value: http://base-llamacpp:8000' "$profile" || fail 'llama Service changed'
    argument=$(awk '/- --sequence-distribution$/ { getline; print $2 }' "$profile" | tr -d '"')
    [ "$argument" = '64,32:50;256,64:50' ] || fail 'Dataset size profiles must keep token lengths'
    argument=$(awk '/- --request-count$/ { getline; print $2 }' "$profile" | tr -d '"')
    [ "$argument" = 100 ] || fail 'Dataset size profiles must keep the request count'
    values=$(awk '/name: CONCURRENCIES$/ { getline; print $2 }' "$profile" | tr -d '"')
    [ "$values" = '1,2,4,8' ] || fail 'Dataset size profiles must keep concurrency levels'
    [ "$(grep -Fc 'cpu: "1"' "$profile")" -eq 2 ] || fail 'Profile CPU requests must equal limits'
    [ "$(grep -Fc 'memory: 1Gi' "$profile")" -eq 2 ] || fail 'Profile memory requests must equal limits'
done
printf 'PASS: default SmolLM2 and explicit llama profiles, fixed load, separate results and Guaranteed resources\n'
