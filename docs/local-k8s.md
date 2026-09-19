# 로컬 Kubernetes 사용 가이드

기본 설치와 실행 순서는 [README](../README.md)를 참고하세요. 아래 명령은 저장소 루트에서 실행합니다. 전체 명령 목록은 `./scripts/local-k8s.sh help`로 확인합니다. 이 클러스터는 CPU 전용이며 GPU를 사용하지 않습니다.

## 의존성 최소화와 OS 호환성

클러스터 준비 과정은 의존성 최소화와 여러 OS에서의 호환을 최우선으로 유지합니다.

- 모든 스크립트는 POSIX `sh`로 동작하며 bash 전용 문법을 사용하지 않습니다.
- 클러스터 준비에 필요한 도구는 kind, kubectl, Docker뿐입니다. 설치에는 `curl` 또는 `wget`, `sha256sum` 또는 `shasum` 중 하나만 있으면 됩니다.
- Python, jq, yq, helm, kustomize는 필요하지 않습니다. `make` 없이 스크립트를 직접 실행할 수 있습니다.
- Linux, macOS, Windows(WSL2)와 amd64, arm64 아키텍처를 지원합니다. 아키텍처에 맞는 노드 이미지를 사용합니다.
- 외부 `KUBECONFIG`와 `~/.kube/config`를 변경하지 않으며, kubeconfig는 `.local-k8s/`에 권한 `600`으로 격리합니다.

## 환경 준비

로컬 Docker가 실행 중인 호스트를 사용합니다. `doctor`는 도구 존재와 Docker 연결을 확인합니다.

기본 Kubernetes 버전에는 cgroup v2가 필요합니다. 호스트와 같은 아키텍처의 노드 이미지를 사용하고, 노드 수와 workload에 맞춰 CPU, 메모리와 디스크를 확보합니다. [kind 설치 안내](https://kind.sigs.k8s.io/docs/user/quick-start/)

오프라인에서는 도구와 노드 이미지를 미리 준비합니다. 노드 이미지는 Docker에 `load`하고 같은 참조를 `KIND_NODE_IMAGE`로 지정합니다. workload 이미지도 같은 방법으로 준비합니다. [kind 오프라인 안내](https://kind.sigs.k8s.io/docs/user/working-offline/)

## 클러스터 설정

기본 [kind 설정](../config/cluster/kind.yaml)은 CPU 전용 단일 노드, 기본 CNI와 스토리지를 사용합니다. API 서버는 `127.0.0.1`의 임의 포트로 노출합니다. `up`은 노드와 CoreDNS 준비를 기다립니다.

버전과 노드 이미지 digest는 [versions.env](../config/versions.env)에서 관리합니다. 변경 시 [kind 릴리스](https://github.com/kubernetes-sigs/kind/releases)에 명시된 kind와 노드 이미지 조합을 사용하고 kubectl 버전도 맞춥니다. `install`은 다운로드한 도구의 SHA-256을 검증하며, 스크립트는 `.bin/`의 도구를 PATH보다 우선합니다.

| 환경 변수 | 기본값 | 용도 |
| --- | --- | --- |
| `CLUSTER_NAME` | `local-k8s` | 클러스터 이름 |
| `KIND_CONFIG` | `config/cluster/kind.yaml` | 사용할 kind YAML |
| `KIND_EXPERIMENTAL_PROVIDER` | `docker` | Docker 사용. `auto`도 Docker 선택 |
| `WAIT_TIMEOUT` | `180s` | 생성과 각 준비 상태 확인의 대기 시간 |
| `KIND_NODE_IMAGE` | `config/versions.env` 참조 | 노드 이미지 |
| `KIND_VERSION`, `KUBECTL_VERSION` | `config/versions.env` 참조 | 설치할 도구 버전 |
| `LOCAL_K8S_STATE_DIR` | `.local-k8s/` | kubeconfig, 런타임 선택 기록과 로그 저장 위치 |
| `LOCAL_K8S_BIN_DIR` | `.bin/` | 도구 설치 및 우선 탐색 위치 |

기본 경로는 저장소 기준이며, 사용자 지정 상대 경로는 명령을 실행한 디렉터리 기준입니다. 클러스터 이름에는 소문자, 숫자와 하이픈을 사용하고 다른 클러스터와 겹치지 않게 지정합니다.

control-plane 1개와 worker 2개를 사용하려면 [멀티 노드 설정](../config/cluster/kind-multi-node.yaml)을 선택합니다.

```sh
KIND_CONFIG=config/cluster/kind-multi-node.yaml ./scripts/local-k8s.sh up
./scripts/local-k8s.sh status
```

`up`은 같은 이름의 클러스터를 재사용합니다. 기존 클러스터의 노드 구성과 이미지는 변경하지 않습니다. 설정 변경에는 재생성이 필요합니다. 필요한 노드 데이터를 백업한 뒤 `down`하고 원하는 설정으로 `up`합니다.

Docker context와 `DOCKER_HOST`는 생성할 때와 동일하게 유지합니다. 로컬 Docker 데몬에 접속해야 합니다.

## Kubernetes 명령과 이미지 사용

kubeconfig는 `.local-k8s/<클러스터 이름>/kubeconfig`에 권한 `600`으로 저장합니다. 기존 `~/.kube/config`와 외부 `KUBECONFIG`는 변경하지 않습니다. `up`을 다시 실행하면 kubeconfig를 복구할 수 있습니다.

```sh
./scripts/local-k8s.sh kubectl apply -f path/to/workload.yaml

# 설치한 kubectl을 직접 사용할 때
export KUBECONFIG="$(./scripts/local-k8s.sh kubeconfig)"
./.bin/kubectl get pods -A
```

빌드와 kind에서 같은 Docker 데몬을 사용합니다. 로드한 이미지를 사용할 workload에는 `imagePullPolicy: IfNotPresent` 또는 `Never`를 지정하고, `latest` 대신 명시적인 태그를 사용합니다.

```sh
docker build -t inference:test /path/to/application
./scripts/local-k8s.sh load-image inference:test

# 런타임의 save 명령으로 만든 아카이브 사용
./scripts/local-k8s.sh load-archive ./inference.tar

# 배포한 Service에 접속
./scripts/local-k8s.sh kubectl port-forward service/inference 8080:80
```

애플리케이션 경로와 Service 이름은 실제 값으로 바꿉니다. Ingress와 LoadBalancer 구현은 기본 설치에 포함하지 않습니다.

## 문제 해결

생성 실패 시 노드를 남겨 로그를 확인할 수 있습니다. 원인을 해결한 뒤 `down`하고 다시 생성합니다. `down`은 노드 내부의 영구 볼륨 데이터도 삭제합니다.

```sh
./scripts/local-k8s.sh logs
./scripts/local-k8s.sh down
```

| 증상 | 확인 사항 |
| --- | --- |
| Docker 연결 실패 | Docker 서비스와 현재 사용자의 접근 권한 |
| 준비 시간 초과 | 로그와 할당 자원. 필요하면 `WAIT_TIMEOUT=300s`로 조정 |
| `no space left on device` | Docker 데이터 경로와 임시 디렉터리의 여유 공간 확인. 임시 파일은 `TMPDIR`로 위치 지정 |
| VPN과 Pod 또는 Service 대역 충돌 | 사용자 지정 kind YAML의 `podSubnet`, `serviceSubnet` 조정 |
| 이미지 로드 시 `content digest ... not found` | 아래 Docker 이미지 저장소 안내 확인 |

Docker가 containerd 이미지 저장소를 사용하고 `docker image save --platform`을 지원하면, `load-image`는 서버 아키텍처의 아카이브를 임시 생성해 로드합니다. 이미지 크기만큼 임시 디스크 공간이 필요합니다. 해당 옵션이 없는 Docker에서 digest 오류가 발생하면 Docker를 업데이트하거나 단일 플랫폼 이미지 아카이브를 준비합니다. [kind 문제 해결 안내](https://kind.sigs.k8s.io/docs/user/known-issues/)

## 검증

외부 명령을 모사한 스크립트 테스트는 컨테이너 런타임이나 네트워크 없이 실행합니다.

```sh
sh tests/test-local-k8s.sh
sh tests/test-install-tools.sh
sh tests/test-download-model.sh

# 선택 사항: 다른 셸과 정적 분석
TEST_SHELL=bash sh tests/test-local-k8s.sh
shellcheck -x scripts/*.sh tests/*.sh
```

실제 통합 테스트는 임시 클러스터에서 노드 준비, 재사용, 이미지 로드와 DNS를 확인한 뒤 삭제합니다. 이미지 다운로드 연결이 필요하며, 실패 시 진단 로그 경로를 출력합니다.

```sh
./tests/test-cluster.sh
KIND_CONFIG=config/cluster/kind-multi-node.yaml ./tests/test-cluster.sh
```
