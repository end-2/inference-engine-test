# 로컬 Kubernetes 사용 가이드

`scripts/local-k8s.sh`로 Docker 기반 kind 클러스터를 생성하고 워크로드와 이미지를 관리합니다. 클러스터는 CPU 전용입니다. 아래 명령은 저장소 루트에서 실행하며, 전체 명령 목록은 `./scripts/local-k8s.sh help`로 확인합니다.

## 환경 준비

실행 중인 로컬 Docker 데몬과 POSIX 셸이 필요합니다. 도구를 설치한 뒤 Docker 연결을 확인하고 클러스터를 생성합니다. 지원 플랫폼과 워크로드별 자원 조건은 [최소 요구사항](requirements.md)에 정리되어 있습니다.

```sh
./scripts/local-k8s.sh install
./scripts/local-k8s.sh doctor
./scripts/local-k8s.sh up
./scripts/local-k8s.sh test
```

오프라인에서는 도구와 노드 이미지를 미리 준비합니다. 노드 이미지는 Docker에 `load`하고 같은 참조를 `KIND_NODE_IMAGE`로 지정합니다. workload 이미지도 같은 방법으로 준비합니다. [kind 오프라인 안내](https://kind.sigs.k8s.io/docs/user/working-offline/)

## 클러스터 설정

기본 [kind 설정](../../config/cluster/kind.yaml)은 CPU 전용 단일 노드, 기본 CNI와 스토리지를 사용합니다. API 서버는 `127.0.0.1`의 임의 포트로 노출합니다. `up`은 노드와 CoreDNS 준비를 기다립니다.

버전과 노드 이미지 digest는 [versions.env](../../config/versions.env)에서 관리합니다. 변경 시 [kind 릴리스](https://github.com/kubernetes-sigs/kind/releases)에 명시된 kind와 노드 이미지 조합을 사용하고 kubectl 버전도 맞춥니다. `install`은 다운로드한 도구의 SHA-256을 검증하며, 스크립트는 `.bin/`의 도구를 PATH보다 우선합니다.

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

control-plane 1개와 worker 3개를 사용하려면 [멀티 노드 설정](../../config/cluster/kind-multi-node.yaml)을 선택합니다. worker는 `workload=monitor` 1개와 `workload=engine` 2개로 구성합니다. 측정 워크로드는 이 라벨을 node selector로 사용해 추론 서버와 모니터링 도구를 배치합니다.

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
| macOS에서 `keychain cannot be accessed` | 이미지 다운로드에 사용하는 Docker credential helper가 로그인 키체인에 접근할 수 있는지 확인 |
| 준비 시간 초과 | 로그와 할당 자원. 필요하면 `WAIT_TIMEOUT=300s`로 조정 |
| `no space left on device` | Docker 데이터 경로와 임시 디렉터리의 여유 공간 확인. 임시 파일은 `TMPDIR`로 위치 지정 |
| VPN과 Pod 또는 Service 대역 충돌 | 사용자 지정 kind YAML의 `podSubnet`, `serviceSubnet` 조정 |
| 이미지 로드 시 `content digest ... not found` | Docker 버전과 단일 플랫폼 이미지 아카이브 확인 |

이미지 digest 오류가 발생하면 Docker를 업데이트하거나 단일 플랫폼 이미지 아카이브를 사용합니다. 이미지 로드에는 아카이브 크기만큼 임시 디스크 공간이 필요합니다.

## 검증

외부 명령을 모사한 스크립트 테스트는 컨테이너 런타임이나 네트워크 없이 실행합니다.

```sh
sh tests/test-local-k8s.sh
sh tests/test-install-tools.sh
```

실제 통합 테스트는 임시 클러스터에서 노드 준비, 재사용, 이미지 로드와 DNS를 확인한 뒤 삭제합니다. 이미지 다운로드 연결이 필요하며, 실패 시 진단 로그 경로를 출력합니다.

```sh
./tests/test-cluster.sh
KIND_CONFIG=config/cluster/kind-multi-node.yaml ./tests/test-cluster.sh
```
