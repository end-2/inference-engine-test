> Korean version: [한국어](local-k8s-KR.md)

# Local Kubernetes guide

Use `scripts/local-k8s.sh` to create a Docker-based kind cluster and manage workloads and images. The cluster is CPU-only.
For a separate environment using 2 shared GPU resources, see the [MPS cluster guide](gpu-mps.md).

Run the commands below from the repository root. See `./scripts/local-k8s.sh help` for the full command list.

## Environment preparation

A running local Docker daemon and POSIX shell are required. Install tools, check Docker connectivity, create the cluster, and test. Supported platforms and per-workload resource conditions are in [minimum requirements](requirements.md).

```sh
./scripts/local-k8s.sh install
./scripts/local-k8s.sh doctor
./scripts/local-k8s.sh up
./scripts/local-k8s.sh test
```

For offline use, prepare tools and node images in advance. `load` the node image into Docker and specify the same reference as `KIND_NODE_IMAGE`. Prepare workload images the same way. For details, see the [kind offline guide](https://kind.sigs.k8s.io/docs/user/working-offline/).

## Cluster settings

The default [kind config](../../config/cluster/kind.yaml) uses a CPU-only single node, default CNI, and storage. The API server is exposed on a random port on `127.0.0.1`. `up` waits for nodes and CoreDNS readiness.

Versions and node image digests are managed in [versions.env](../../config/versions.env). On change, use the kind and node image combination stated in [kind releases](https://github.com/kubernetes-sigs/kind/releases) and match the kubectl version.

`install` downloads kind, kubectl and Helm and validates their SHA-256 checksums. The script searches `.bin/` before PATH when running tools.

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `CLUSTER_NAME` | `local-k8s` | Cluster name |
| `KIND_CONFIG` | `config/cluster/kind.yaml` | kind YAML to use |
| `KIND_EXPERIMENTAL_PROVIDER` | `docker` | Use Docker. `auto` also selects Docker |
| `WAIT_TIMEOUT` | `180s` | Wait time for creation and each readiness check |
| `KIND_NODE_IMAGE` | See `config/versions.env` | Node image |
| `KIND_VERSION`, `KUBECTL_VERSION`, `HELM_VERSION` | See `config/versions.env` | Tool versions to install |
| `LOCAL_K8S_STATE_DIR` | `.local-k8s/` | kubeconfig, runtime selection records, and log storage |
| `LOCAL_K8S_BIN_DIR` | `.bin/` | Tool install and priority search location |

Default paths are repository-relative; custom relative paths are relative to the directory where the command runs. Use lowercase, numbers, and hyphens for cluster names, and avoid overlap with other clusters.

To use 1 control-plane and 3 workers, select the [multi-node config](../../config/cluster/kind-multi-node.yaml). Workers are 1 `workload=monitor` and 2 `workload=engine`. Measurement workloads use this label as node selector to place inference servers and monitoring tools.

```sh
KIND_CONFIG=config/cluster/kind-multi-node.yaml ./scripts/local-k8s.sh up
./scripts/local-k8s.sh status
```

`up` reuses a cluster with the same name and does not change existing node configuration or images. To change node configuration or images, recreate the cluster. Back up needed node data, run `down`, then `up` with the wanted settings.

Keep the Docker context and `DOCKER_HOST` the same as at creation. It must connect to the local Docker daemon.

## Kubernetes commands and image use

The kubeconfig is stored at `.local-k8s/<cluster name>/kubeconfig` with mode `600`. Existing `~/.kube/config` and external `KUBECONFIG` are not changed. Rerunning `up` can restore the kubeconfig.

```sh
./scripts/local-k8s.sh kubectl apply -f path/to/workload.yaml

# When using the installed kubectl directly
export KUBECONFIG="$(./scripts/local-k8s.sh kubeconfig)"
./.bin/kubectl get pods -A
```

Builds and kind use the same Docker daemon. For workloads using loaded images, set `imagePullPolicy: IfNotPresent` or `Never`, and use an explicit tag instead of `latest`.

```sh
docker build -t inference:test /path/to/application
./scripts/local-k8s.sh load-image inference:test

# Use an archive created with the runtime save command
./scripts/local-k8s.sh load-archive ./inference.tar

# Connect to a deployed Service
./scripts/local-k8s.sh kubectl port-forward service/inference 8080:80
```

Replace application paths and Service names with real values. Ingress and LoadBalancer implementations are not included in the default install.

## Troubleshooting

On creation failure, nodes can be kept to check logs. Fix the cause, run `down`, and recreate. `down` also deletes persistent volume data inside nodes.

```sh
./scripts/local-k8s.sh logs
./scripts/local-k8s.sh down
```

| Symptom | Checks |
| --- | --- |
| Docker connection failure | Docker service and current user access |
| `keychain cannot be accessed` on macOS | Whether the Docker credential helper used for image downloads can access the login keychain |
| Readiness timeout | Logs and allocated resources. Adjust with `WAIT_TIMEOUT=300s` if needed |
| `no space left on device` | Free space on Docker data path and temp directory. Set temp file location with `TMPDIR` |
| VPN and Pod or Service CIDR conflict | Adjust `podSubnet` and `serviceSubnet` in a custom kind YAML |
| `content digest ... not found` on image load | Docker version and single-platform image archive |

On image digest errors, update Docker or use a single-platform image archive. Image loading needs temp disk space for the archive size.

## Validation

Script tests mocking external commands run without container runtime or network.

```sh
sh tests/test-local-k8s.sh
sh tests/test-install-tools.sh
```

Real integration tests check node readiness, reuse, image loading, and DNS on a temp cluster, then delete it. Image download connectivity is required; on failure they print diagnostics log paths.

```sh
./tests/test-cluster.sh
KIND_CONFIG=config/cluster/kind-multi-node.yaml ./tests/test-cluster.sh
```
