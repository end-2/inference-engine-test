#!/bin/sh
set -eu
umask 077
ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
# shellcheck source-path=SCRIPTDIR
# shellcheck source=../config/versions.env
. "$ROOT/config/versions.env"
NVKIND_VERSION=c57050497cffee36f10c8b918d2727c4f26d886e
DEVICE_PLUGIN_VERSION=0.20.1
BIN_DIR=${LOCAL_K8S_BIN_DIR:-$ROOT/.bin}
PATH="$BIN_DIR:$PATH"
export PATH
CLUSTER_NAME=${CLUSTER_NAME:-local-k8s-gpu}
LOCAL_K8S_STATE_DIR=${LOCAL_K8S_STATE_DIR:-$ROOT/.local-k8s}
export CLUSTER_NAME LOCAL_K8S_STATE_DIR
STATE_DIR="$LOCAL_K8S_STATE_DIR/$CLUSTER_NAME"
KUBECONFIG="$STATE_DIR/kubeconfig"
export KUBECONFIG
MODELS_DIR=${LOCAL_K8S_MODELS_DIR:-$ROOT/.models}

die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
[ "$CLUSTER_NAME" != local-k8s ] || die "GPU cluster name must differ from the CPU cluster"
require() { command -v "$1" >/dev/null 2>&1 || die "Missing $1"; }
kube() { "$ROOT/scripts/local-k8s.sh" kubectl "$@"; }

check_runtime() {
    require docker
    require nvidia-smi
    docker info >/dev/null || die "Docker is unavailable"
    docker info --format '{{json .Runtimes}}' | grep -q '"nvidia"' || die "Docker has no NVIDIA runtime"
    nvidia-smi -L | grep -q '^GPU 0:' || die "NVIDIA GPU 0 is unavailable"
    docker run --rm --runtime=nvidia -e NVIDIA_VISIBLE_DEVICES=all ubuntu:22.04 nvidia-smi -L >/dev/null || die "NVIDIA Docker runtime cannot access the GPU"
    docker run --rm --runtime=nvidia -v /dev/null:/var/run/nvidia-container-devices/0 ubuntu:22.04 nvidia-smi -L >/dev/null || die "NVIDIA volume mount injection is disabled. Enable accept-nvidia-visible-devices-as-volume-mounts in the toolkit configuration."
}

check_mounts() {
    for node in "$CLUSTER_NAME-control-plane" "$CLUSTER_NAME-worker"; do
        mount=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/models"}}{{.Source}}:{{.RW}}{{end}}{{end}}' "$node")
        [ "$mount" = "$MODELS_DIR:false" ] || die "Node $node lacks the read-only $MODELS_DIR model mount"
    done
}

check_allocation() {
    node="$CLUSTER_NAME-worker"
    count=$(kube get node "$node" -o 'jsonpath={.status.allocatable.nvidia\.com/gpu}')
    [ "$count" = 1 ]
}

install_plugin() {
    require helm
    helm repo add nvdp https://nvidia.github.io/k8s-device-plugin --force-update >/dev/null
    helm repo update nvdp >/dev/null
    helm upgrade --install nvidia-device-plugin nvdp/nvidia-device-plugin \
        --version "$DEVICE_PLUGIN_VERSION" --kubeconfig "$KUBECONFIG" \
        --kube-context "kind-$CLUSTER_NAME" --namespace nvidia --create-namespace \
        --set runtimeClassName=nvidia --set failOnInitError=true --wait --timeout 5m
    attempts=0
    until check_allocation; do
        attempts=$((attempts + 1))
        [ "$attempts" -lt 30 ] || die "GPU allocation was not registered on $CLUSTER_NAME-worker"
        sleep 2
    done
}

gpu_smoke() {
    kube delete job gpu-smoke --ignore-not-found=true --wait=true >/dev/null
    cat <<'EOF' | kube apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: gpu-smoke
spec:
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      runtimeClassName: nvidia
      nodeSelector:
        nvidia.com/gpu.present: "true"
      containers:
        - name: check
          image: ubuntu:22.04
          command: ["nvidia-smi", "-L"]
          resources:
            limits:
              nvidia.com/gpu: 1
EOF
    kube wait --for=condition=Complete job/gpu-smoke --timeout=180s
    kube logs job/gpu-smoke
    kube delete job gpu-smoke --wait=true >/dev/null
}

load_image_node() {
    [ "$#" -eq 2 ] || die "load-image-node requires NODE IMAGE"
    node=$1
    image=$2
    case $node in
        "$CLUSTER_NAME-control-plane"|"$CLUSTER_NAME-worker") ;;
        *) die "Node $node does not belong to $CLUSTER_NAME" ;;
    esac
    require docker
    require kind
    mkdir -p "$STATE_DIR"
    staging=$(mktemp -d "$STATE_DIR/image-load.XXXXXX")
    trap 'rm -rf "$staging"' EXIT
    docker image save --platform linux/amd64 --output "$staging/image.tar" "$image"
    kind load image-archive --name "$CLUSTER_NAME" --nodes "$node" "$staging/image.tar"
}

command=${1:-help}
[ "$#" -eq 0 ] || shift
case "$command" in
    install)
        [ "$#" -eq 0 ] || die "install takes no arguments"
        "$ROOT/scripts/local-k8s.sh" install
        require go
        mkdir -p "$BIN_DIR"
        GOBIN="$BIN_DIR" go install "github.com/NVIDIA/nvkind/cmd/nvkind@$NVKIND_VERSION"
        ;;
    doctor)
        [ "$#" -eq 0 ] || die "doctor takes no arguments"
        check_runtime
        require nvkind
        require kind
        require kubectl
        require helm
        ;;
    up)
        [ "$#" -eq 0 ] || die "up takes no arguments"
        check_runtime
        require nvkind
        require kind
        require kubectl
        mkdir -p "$MODELS_DIR" "$STATE_DIR"
        MODELS_DIR=$(CDPATH='' cd -- "$MODELS_DIR" && pwd)
        created=false
        if kind get clusters | grep -Fxq "$CLUSTER_NAME"; then
            kind export kubeconfig --name "$CLUSTER_NAME" --kubeconfig "$KUBECONFIG"
        else
            created=true
            printf 'modelsDir: %s\n' "$MODELS_DIR" > "$STATE_DIR/nvkind-values.yaml"
            LOCAL_K8S_DOCKER=$(command -v docker)
            export LOCAL_K8S_DOCKER
            PATH="$ROOT/scripts/lib/gpu-docker:$PATH" nvkind cluster create \
                --name "$CLUSTER_NAME" --image "$KIND_NODE_IMAGE" \
                --config-template "$ROOT/config/cluster/nvkind-gpu.yaml" \
                --config-values "$STATE_DIR/nvkind-values.yaml" \
                --kubeconfig "$KUBECONFIG" --wait 180s --retain
        fi
        chmod 600 "$KUBECONFIG"
        check_mounts
        kube wait --for=condition=Ready nodes --all --timeout=180s
        if ! check_allocation; then
            install_plugin
        fi
        if [ "$created" = true ]; then gpu_smoke; fi
        ;;
    down|status|kubeconfig|kubectl|load-image|load-archive|logs)
        exec "$ROOT/scripts/local-k8s.sh" "$command" "$@"
        ;;
    load-image-node)
        load_image_node "$@"
        ;;
    test)
        check_allocation || die "GPU allocation is unavailable"
        gpu_smoke
        ;;
    *) die "Usage: $0 {install|doctor|up|down|status|kubeconfig|kubectl|load-image|load-archive|logs|test}" ;;
esac
