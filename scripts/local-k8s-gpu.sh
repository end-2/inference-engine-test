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
die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
# shellcheck source=scripts/lib/gpu-settings.sh
. "$ROOT/scripts/lib/gpu-settings.sh"
LOCAL_K8S_STATE_DIR=${LOCAL_K8S_STATE_DIR:-$ROOT/.local-k8s}
case $LOCAL_K8S_STATE_DIR in /*) ;; *) LOCAL_K8S_STATE_DIR="$PWD/$LOCAL_K8S_STATE_DIR" ;; esac
export CLUSTER_NAME LOCAL_K8S_STATE_DIR
STATE_DIR="$LOCAL_K8S_STATE_DIR/$CLUSTER_NAME"
KUBECONFIG="$STATE_DIR/kubeconfig"
export KUBECONFIG
MODELS_DIR=${LOCAL_K8S_MODELS_DIR:-$ROOT/.models}

require() { command -v "$1" >/dev/null 2>&1 || die "Missing $1"; }
kube() { "$ROOT/scripts/local-k8s.sh" kubectl "$@"; }
# shellcheck source=scripts/lib/mps-smoke.sh
. "$ROOT/scripts/lib/mps-smoke.sh"

usage() {
    cat <<'EOF'
Usage: scripts/local-k8s-gpu.sh COMMAND [ARGS]

  install, doctor, up, down, status, test
  kubeconfig, kubectl ARGS..., load-image IMAGE..., load-archive TAR...
  load-image-node NODE IMAGE, logs [DIRECTORY]

GPU_SHARING=none uses local-k8s-gpu with one nvidia.com/gpu resource.
GPU_SHARING=mps uses local-k8s-gpu-mps with two nvidia.com/gpu.shared resources.
MPS_REPLICAS=4 selects four shares and the separate local-k8s-gpu-mps4 cluster.
CLUSTER_NAME overrides the selected name. GPU 0 is mounted on one worker.
See docs/guides/gpu-mps.md for MPS setup and profile selection.
EOF
}

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
    if [ "$GPU_SHARING" = mps ]; then
        count=$(kube get node "$node" -o 'jsonpath={.status.allocatable.nvidia\.com/gpu\.shared}') || return 1
    else
        count=$(kube get node "$node" -o 'jsonpath={.status.allocatable.nvidia\.com/gpu}') || return 1
    fi
    [ "$count" = "$GPU_REPLICAS" ]
}

check_sharing_mode() {
    mode=$(kube get node "$CLUSTER_NAME-worker" -o 'jsonpath={.metadata.labels.inference-engine-test\.gpu-sharing}')
    if [ -z "$mode" ]; then
        capable=$(kube get node "$CLUSTER_NAME-worker" -o 'jsonpath={.metadata.labels.nvidia\.com/mps\.capable}')
        mode=none
        [ "$capable" != true ] || mode=mps
    fi
    [ "$mode" = "$GPU_SHARING" ] || die "Cluster $CLUSTER_NAME uses GPU_SHARING=$mode. Select that mode or a different CLUSTER_NAME."
    if [ "$GPU_SHARING" = mps ]; then
        replicas=$(kube get node "$CLUSTER_NAME-worker" -o 'jsonpath={.metadata.labels.inference-engine-test\.mps-replicas}')
        # Older clusters have no replica label, but their allocation still identifies the profile.
        if [ -z "$replicas" ]; then
            replicas=$(kube get node "$CLUSTER_NAME-worker" -o 'jsonpath={.status.allocatable.nvidia\.com/gpu\.shared}')
        fi
        case $replicas in
            ''|0) [ "$GPU_REPLICAS" = 2 ] || die "Cluster $CLUSTER_NAME has no MPS replica identity; select a new cluster name" ;;
            *) [ "$replicas" = "$GPU_REPLICAS" ] || die "Cluster $CLUSTER_NAME uses MPS_REPLICAS=$replicas. Select that profile or a different CLUSTER_NAME." ;;
        esac
    fi
}

mps_pod() {
    pods=$(kube get pods -n nvidia --field-selector=status.phase=Running \
        -o 'jsonpath={range .items[*]}{.metadata.name}{" "}{.metadata.deletionTimestamp}{"\n"}{end}') || return 1
    printf '%s\n' "$pods" | awk '$1 ~ /^nvidia-device-plugin-mps-control-daemon-/ && NF == 1 {print $1; exit}'
}

mps_control() {
    printf '%s\n' "$1" | kube exec -i -n nvidia "$mps_daemon" -c mps-control-daemon-ctr -- \
        env CUDA_MPS_PIPE_DIRECTORY=/mps/nvidia.com/gpu.shared/pipe nvidia-cuda-mps-control
}

check_mps() {
    mps_daemon=$(mps_pod)
    [ -n "$mps_daemon" ] || die "MPS control daemon is not running"
    percentage=$(mps_control get_default_active_thread_percentage)
    expected_percentage=$((100 / GPU_REPLICAS))
    [ "$percentage" = "$expected_percentage.0" ] || [ "$percentage" = "$expected_percentage" ] || die "Unexpected MPS thread percentage: $percentage"
    memory_limit=$(mps_control 'get_default_device_pinned_mem_limit 0')
    printf 'MPS: thread limit %s%%, memory limit %s per CUDA client\n' "$percentage" "$memory_limit"
}

check_gpu_idle() {
    processes=$(nvidia-smi -i 0 --query-compute-apps=pid --format=csv,noheader)
    [ -z "$processes" ] || die "GPU 0 has active CUDA processes ($processes). Stop its workloads before starting the MPS cluster."
}

install_plugin() {
    require helm
    helm repo add nvdp https://nvidia.github.io/k8s-device-plugin --force-update >/dev/null
    helm repo update nvdp >/dev/null
    set --
    if [ "$GPU_SHARING" = mps ]; then
        set -- --set-file "config.map.mps=$ROOT/config/cluster/$GPU_MPS_CONFIG" --set config.default=mps
    fi
    helm upgrade --install nvidia-device-plugin nvdp/nvidia-device-plugin \
        --version "$DEVICE_PLUGIN_VERSION" --kubeconfig "$KUBECONFIG" \
        --kube-context "kind-$CLUSTER_NAME" --namespace nvidia --create-namespace \
        --set runtimeClassName=nvidia --set failOnInitError=true "$@" --wait --timeout 5m
    if [ "$GPU_SHARING" = mps ]; then
        kube label node "$CLUSTER_NAME-worker" nvidia.com/mps.capable=true --overwrite
        kube -n nvidia rollout status daemonset/nvidia-device-plugin-mps-control-daemon --timeout=180s
    fi
    attempts=0
    until check_allocation; do
        attempts=$((attempts + 1))
        [ "$attempts" -lt 30 ] || die "GPU allocation was not registered on $CLUSTER_NAME-worker"
        sleep 2
    done
}

gpu_smoke() {
    if [ "$GPU_SHARING" = mps ]; then
        mps_smoke
        return
    fi
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
    help|-h|--help) usage ;;
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
        case ${KIND_EXPERIMENTAL_PROVIDER:-docker} in
            docker|auto) export KIND_EXPERIMENTAL_PROVIDER=docker ;;
            *) die "GPU clusters require the Docker kind provider" ;;
        esac
        clusters=$(kind get clusters) || die "Failed to list kind clusters"
        if ! printf '%s\n' "$clusters" | grep -Fxq "$CLUSTER_NAME" && [ "$GPU_SHARING" = mps ]; then
            check_gpu_idle
        fi
        (umask 022; mkdir -p "$MODELS_DIR")
        mkdir -p "$STATE_DIR"
        MODELS_DIR=$(CDPATH='' cd -- "$MODELS_DIR" && pwd)
        created=false
        if printf '%s\n' "$clusters" | grep -Fxq "$CLUSTER_NAME"; then
            kind export kubeconfig --name "$CLUSTER_NAME" --kubeconfig "$KUBECONFIG"
        else
            created=true
            printf 'modelsDir: %s\n' "$MODELS_DIR" > "$STATE_DIR/nvkind-values.yaml"
            printf 'gpuSharing: %s\n' "$GPU_SHARING" >> "$STATE_DIR/nvkind-values.yaml"
            if [ "$GPU_SHARING" = mps ]; then
                printf 'mpsReplicas: %s\n' "$GPU_REPLICAS" >> "$STATE_DIR/nvkind-values.yaml"
            fi
            LOCAL_K8S_DOCKER=$(command -v docker)
            export LOCAL_K8S_DOCKER
            (
                # nvkind parses combined kind output; an explicit provider adds a diagnostic.
                unset KIND_EXPERIMENTAL_PROVIDER
                PATH="$ROOT/scripts/lib/gpu-docker:$PATH" nvkind cluster create \
                    --name "$CLUSTER_NAME" --image "$KIND_NODE_IMAGE" \
                    --config-template "$ROOT/config/cluster/nvkind-gpu.yaml" \
                    --config-values "$STATE_DIR/nvkind-values.yaml" \
                    --kubeconfig "$KUBECONFIG" --wait 180s --retain
            )
        fi
        chmod 600 "$KUBECONFIG"
        check_mounts
        kube wait --for=condition=Ready nodes --all --timeout=180s
        check_sharing_mode
        plugin_ready=true
        check_allocation || plugin_ready=false
        if [ "$GPU_SHARING" = mps ] && [ -z "$(mps_pod)" ]; then
            check_gpu_idle
            plugin_ready=false
        fi
        if [ "$plugin_ready" = false ]; then
            install_plugin
        fi
        if [ "$GPU_SHARING" = mps ]; then check_mps; fi
        if [ "$created" = true ]; then gpu_smoke; fi
        printf 'Cluster %s is ready: %s=%s\n' "$CLUSTER_NAME" "$GPU_RESOURCE" "$GPU_REPLICAS"
        ;;
    down)
        [ "$#" -eq 0 ] || die "down takes no arguments"
        if [ -s "$KUBECONFIG" ] && kube get node "$CLUSTER_NAME-worker" --request-timeout=5s >/dev/null 2>&1; then
            check_sharing_mode
            if [ "$GPU_SHARING" = mps ]; then
                mps_daemon=$(mps_pod)
                kube drain "$CLUSTER_NAME-worker" --ignore-daemonsets --delete-emptydir-data \
                    --force --disable-eviction --grace-period=30 --timeout=120s
                kube label node "$CLUSTER_NAME-worker" nvidia.com/mps.capable- --overwrite
                if [ -n "$mps_daemon" ]; then
                    kube wait --for=delete "pod/$mps_daemon" -n nvidia --timeout=120s
                fi
            fi
        fi
        exec "$ROOT/scripts/local-k8s.sh" down
        ;;
    status)
        [ "$#" -eq 0 ] || die "status takes no arguments"
        "$ROOT/scripts/local-k8s.sh" status
        kube get nodes -o 'custom-columns=NAME:.metadata.name,GPU:.status.allocatable.nvidia\.com/gpu,MPS:.status.allocatable.nvidia\.com/gpu\.shared'
        ;;
    kubeconfig|kubectl|load-image|load-archive|logs)
        exec "$ROOT/scripts/local-k8s.sh" "$command" "$@"
        ;;
    load-image-node)
        load_image_node "$@"
        ;;
    test)
        [ "$#" -eq 0 ] || die "test takes no arguments"
        check_sharing_mode
        check_allocation || die "GPU allocation is unavailable"
        if [ "$GPU_SHARING" = mps ]; then check_mps; fi
        gpu_smoke
        ;;
    *) die "Usage: $0 {install|doctor|up|down|status|kubeconfig|kubectl|load-image|load-archive|logs|test}" ;;
esac
