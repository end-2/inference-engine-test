#!/bin/sh
set -eu

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
TEST_SHELL=${TEST_SHELL:-sh}
sandbox=$(mktemp -d "${TMPDIR:-/tmp}/local-k8s-test.XXXXXX")
# Normalize // that appears when TMPDIR has a trailing slash (e.g. macOS),
# so path comparisons match the pwd-resolved paths used by the script.
sandbox=$(CDPATH='' cd -- "$sandbox" && pwd)
trap 'rm -rf "$sandbox"' 0
trap 'exit 130' INT
trap 'exit 143' TERM
project="$sandbox/repository with spaces"
mkdir -p "$project" "$sandbox/mocks" "$sandbox/data"
cp -R "$ROOT/scripts" "$ROOT/config" "$project/"
export MOCK_ROOT="$sandbox/data" MOCK_TRACE="$sandbox/trace"
export LOCAL_K8S_BIN_DIR="$sandbox/mocks" LOCAL_K8S_STATE_DIR="$sandbox/state with spaces"
export KIND_EXPERIMENTAL_PROVIDER=auto
export KUBECONFIG="$sandbox/unrelated-kubeconfig"
unset CLUSTER_NAME KIND_CONFIG KIND_NODE_IMAGE WAIT_TIMEOUT
printf 'unrelated context\n' > "$KUBECONFIG"
: > "$MOCK_TRACE"

cat > "$sandbox/mocks/runtime" <<'EOF'
#!/bin/sh
set -eu
runtime=${0##*/}
{
    printf 'runtime[%s]' "$runtime"
    printf ' <%s>' "$@"
    printf '\n'
} >> "$MOCK_TRACE"
[ ! -f "$MOCK_ROOT/offline-$runtime" ]
case "$*" in
    info) ;;
    'info --format {{.DriverStatus}}')
        if [ -f "$MOCK_ROOT/containerd-store" ]; then printf 'io.containerd.snapshotter.v1\n'; fi
        ;;
    'info --format {{.Architecture}}') printf '%s\n' "${MOCK_RUNTIME_ARCH:-x86_64}" ;;
    'image save --help') printf '%s\n' '--platform' ;;
    'image save '*)
        [ ! -f "$MOCK_ROOT/fail-save" ] || exit 1
        previous=
        for arg in "$@"; do
            if [ "$previous" = --output ]; then printf 'image archive\n' > "$arg"; fi
            previous=$arg
        done
        ;;
    'inspect '*)
        # Report the expected read-only /models mount unless disabled.
        case "$*" in
            *-worker2) [ ! -f "$MOCK_ROOT/no-worker-mount" ] || exit 0 ;;
        esac
        if [ ! -f "$MOCK_ROOT/no-models-mount" ]; then
            printf '%s:false\n' "${LOCAL_K8S_MODELS_DIR:-}"
        fi
        ;;
    *) exit 2 ;;
esac
EOF
cp "$sandbox/mocks/runtime" "$sandbox/mocks/docker"
cat > "$sandbox/mocks/kind" <<'EOF'
#!/bin/sh
set -eu
{
    printf 'kind[%s] kubeconfig[%s]' "$KIND_EXPERIMENTAL_PROVIDER" "$KUBECONFIG"
    printf ' <%s>' "$@"
    printf '\n'
} >> "$MOCK_TRACE"
name=
config=
previous=
for arg in "$@"; do
    if [ "$previous" = --name ]; then name=$arg; fi
    if [ "$previous" = --config ]; then config=$arg; fi
    previous=$arg
done
clusters="$MOCK_ROOT/clusters-$KIND_EXPERIMENTAL_PROVIDER"
case "$*" in
    version) printf 'kind mock\n' ;;
    'get clusters')
        [ ! -f "$MOCK_ROOT/fail-list" ] || exit 1
        if [ -f "$clusters" ]; then cat "$clusters"; fi
        ;;
    'create cluster '*)
        printf '%s\n' "$name" >> "$clusters"
        [ ! -f "$MOCK_ROOT/fail-create" ] || exit 1
        printf '%s-control-plane\n' "$name" > "$MOCK_ROOT/nodes-$name"
        case $config in
            *kind-multi-node.yaml)
                printf '%s-worker\n%s-worker2\n' "$name" "$name" >> "$MOCK_ROOT/nodes-$name"
                ;;
        esac
        printf 'test kubeconfig\n' > "$KUBECONFIG"
        ;;
    'get nodes '*) cat "$MOCK_ROOT/nodes-$name" ;;
    'export kubeconfig '*) printf 'test kubeconfig\n' > "$KUBECONFIG" ;;
    'delete cluster '*)
        [ ! -f "$MOCK_ROOT/fail-delete" ] || exit 1
        if [ -f "$clusters" ]; then
            awk -v name="$name" '$0 != name' "$clusters" > "$clusters.next"
            mv "$clusters.next" "$clusters"
        fi
        rm -f "$MOCK_ROOT/nodes-$name"
        ;;
    'load image-archive '*) [ "$#" -eq 6 ] ;;
    'load docker-image '*|'export logs '*) ;;
    *) exit 2 ;;
esac
EOF
cat > "$sandbox/mocks/kubectl" <<'EOF'
#!/bin/sh
set -eu
{
    printf kubectl
    printf ' <%s>' "$@"
    printf '\n'
} >> "$MOCK_TRACE"
[ ! -f "$MOCK_ROOT/fail-ready" ] || exit 1
case "$*" in
    *'wait --for=condition=Complete '*) [ ! -f "$MOCK_ROOT/fail-job" ] ;;
esac
EOF
chmod +x "$sandbox/mocks/"*

fail() { printf 'FAIL: %s\n' "$*" >&2; cat "$sandbox/output" >&2; exit 1; }
run() { "$TEST_SHELL" "$project/scripts/local-k8s.sh" "$@" > "$sandbox/output" 2>&1; }
ok() { run "$@" || fail "$*"; }
reject() { if run "$@"; then fail "Unexpected success: $*"; fi; }
contains() { grep -Fq -- "$1" "$2" || fail "Missing expected text: $1"; }

# Run outside the checkout to exercise script-relative config and spaced paths.
# NOTE: VAR=value cannot prefix a shell function portably (the assignment
# may persist in some shells). Save and restore around such cases instead.
cd "$sandbox"
ok help
reject invalid-command
reject up extra-argument
saved_cluster=${CLUSTER_NAME-unset}
export CLUSTER_NAME='../escape'; reject down
if [ "$saved_cluster" = unset ]; then unset CLUSTER_NAME; else CLUSTER_NAME=$saved_cluster; fi
export KIND_EXPERIMENTAL_PROVIDER=auto
KIND_EXPERIMENTAL_PROVIDER=invalid; reject doctor
export KIND_EXPERIMENTAL_PROVIDER=auto
KIND_EXPERIMENTAL_PROVIDER=podman; reject up
export KIND_EXPERIMENTAL_PROVIDER=auto
ok doctor
ok up
export CLUSTER_NAME=local-k8s
isolated="$LOCAL_K8S_STATE_DIR/$CLUSTER_NAME/kubeconfig"
[ -s "$isolated" ] || fail 'Isolated kubeconfig not created'
contains '<--config> <'"$project"'/config/cluster/kind.yaml>' "$MOCK_TRACE"
contains '<--for=condition=Ready> <nodes> <--all>' "$MOCK_TRACE"
contains '<deployment/coredns>' "$MOCK_TRACE"
contains '<--name> <local-k8s>' "$MOCK_TRACE"
[ "$(cat "$sandbox/output")" != '' ] || fail 'up printed no output'
ok kubeconfig
[ "$(cat "$sandbox/output")" = "$isolated" ] || fail 'Unexpected kubeconfig path'

rm "$isolated"
ok up
[ "$(grep -c '<create> <cluster>' "$MOCK_TRACE")" -eq 1 ] || fail 'up recreated an existing cluster'
[ -s "$isolated" ] || fail 'up did not recover kubeconfig'
touch "$MOCK_ROOT/no-models-mount"
reject up
rm "$MOCK_ROOT/no-models-mount"
ok status
ok kubectl get pods -l 'app in (a,b)'
contains '<--kubeconfig> <'"$isolated"'> <--context> <kind-local-k8s> <get> <pods> <-l> <app in (a,b)>' "$MOCK_TRACE"
ok test
contains '<create> <job>' "$MOCK_TRACE"
contains 'nslookup kubernetes.default.svc.cluster.local' "$MOCK_TRACE"
touch "$MOCK_ROOT/fail-job"
reject test
rm "$MOCK_ROOT/fail-job"
touch "$MOCK_ROOT/fail-ready"
reject up
rm "$MOCK_ROOT/fail-ready"
ok load-image example:test another:test
contains '<load> <docker-image> <--name> <local-k8s> <--> <example:test> <another:test>' "$MOCK_TRACE"
touch "$sandbox/image one.tar" "$sandbox/image two.tar"
ok load-archive "$sandbox/image one.tar" "$sandbox/image two.tar"
[ "$(grep -c '<load> <image-archive>' "$MOCK_TRACE")" -eq 2 ] || fail 'Archives must load separately'
reject load-archive "$sandbox/missing.tar"
ok logs "$sandbox/log directory"

touch "$MOCK_ROOT/containerd-store"
ok load-image example:test
contains 'runtime[docker] <image> <save> <--platform> <linux/amd64>' "$MOCK_TRACE"
export MOCK_RUNTIME_ARCH=aarch64; ok load-image example:test
unset MOCK_RUNTIME_ARCH
contains 'runtime[docker] <image> <save> <--platform> <linux/arm64>' "$MOCK_TRACE"
export MOCK_RUNTIME_ARCH=riscv64; reject load-image example:test
unset MOCK_RUNTIME_ARCH
touch "$MOCK_ROOT/fail-save"
loads=$(grep -c '<load> <image-archive>' "$MOCK_TRACE")
reject load-image example:test
[ "$(grep -c '<load> <image-archive>' "$MOCK_TRACE")" -eq "$loads" ] || fail 'Failed save triggered image loading'
rm "$MOCK_ROOT/containerd-store" "$MOCK_ROOT/fail-save"

touch "$MOCK_ROOT/offline-docker"
reject up
KIND_EXPERIMENTAL_PROVIDER=podman; reject down
export KIND_EXPERIMENTAL_PROVIDER=auto
rm "$MOCK_ROOT/offline-docker"
touch "$MOCK_ROOT/fail-delete"
reject down
[ -s "$isolated" ] || fail 'Failed deletion removed kubeconfig'
rm "$MOCK_ROOT/fail-delete"
ok down
[ ! -f "$isolated" ] || fail 'down left kubeconfig behind'
ok down
reject status

touch "$MOCK_ROOT/fail-list"
creates=$(grep -c '<create> <cluster>' "$MOCK_TRACE")
reject up
[ "$(grep -c '<create> <cluster>' "$MOCK_TRACE")" -eq "$creates" ] || fail 'List failure triggered cluster creation'
rm "$MOCK_ROOT/fail-list"
touch "$MOCK_ROOT/fail-create"
reject up
contains 'creation failed' "$sandbox/output"
[ ! -f "$isolated" ] || fail 'Failed creation produced kubeconfig'
rm "$MOCK_ROOT/fail-create"
ok down

saved_kind_config=${KIND_CONFIG-unset}
export KIND_CONFIG="$project/config/cluster/kind-multi-node.yaml"; ok up
if [ "$saved_kind_config" = unset ]; then unset KIND_CONFIG; else KIND_CONFIG=$saved_kind_config; fi
contains 'docker' "$LOCAL_K8S_STATE_DIR/$CLUSTER_NAME/provider"
contains '<--config> <'"$project"'/config/cluster/kind-multi-node.yaml>' "$MOCK_TRACE"
touch "$MOCK_ROOT/no-worker-mount"
reject up
rm "$MOCK_ROOT/no-worker-mount"
ok down
touch "$MOCK_ROOT/offline-docker"
reject doctor
rm "$MOCK_ROOT/offline-docker"

[ "$(cat "$KUBECONFIG")" = 'unrelated context' ] || fail 'Unrelated kubeconfig changed'
if grep -Fq "$KUBECONFIG" "$MOCK_TRACE"; then fail 'A command used the unrelated kubeconfig'; fi
printf 'PASS: CPU lifecycle, reuse, smoke test, image loading, isolation, and argument handling (%s)\n' "$TEST_SHELL"
