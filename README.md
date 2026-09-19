# Inference engine test (CPU)

kind 기반 로컬 Kubernetes 환경입니다. CPU 기반 inference engine 테스트를 위한 클러스터 준비가 목적이며, 기본 구성은 단일 노드입니다.

## 의존성 최소화와 OS 호환성

이 저장소는 의존성 최소화와 여러 OS에서의 호환을 최우선으로 유지합니다.

- POSIX `sh`로만 스크립트를 작성하며 bash, zsh, fish 전용 문법을 사용하지 않습니다.
- 필수 도구는 kind, kubectl, Docker뿐이며 `install`은 `curl` 또는 `wget`, `sha256sum` 또는 `shasum` 중 하나만 있으면 동작합니다.
- Python, jq, yq, helm, kustomize는 클러스터 준비에 필요하지 않습니다. `make`도 선택 사항이며 각 스크립트를 직접 실행할 수 있습니다.
- Linux, macOS, Windows(WSL2)를 지원하고 amd64와 arm64 아키텍처를 지원합니다.
- 버전은 [도구 설정](config/versions.env)에 고정하며 다운로드한 도구는 SHA-256으로 검증합니다.

## 준비 사항

- Docker가 실행 중인 호스트, POSIX 셸
- 도구 설치 시 curl 또는 wget, sha256sum 또는 shasum과 인터넷 연결

OS, 컨테이너 환경, 버전과 자원 조건은 [최소 요구사항](docs/requirements.md)을 참고하세요.

## 빠른 시작

Docker를 실행한 뒤 저장소 루트에서 실행합니다.

```sh
./scripts/local-k8s.sh install
./scripts/local-k8s.sh doctor
./scripts/local-k8s.sh up
./scripts/local-k8s.sh status
./scripts/local-k8s.sh test
```

`install`은 kind와 kubectl을 `.bin/`에 설치합니다. 호환되는 도구가 PATH에 있으면 생략할 수 있습니다. `up`은 노드와 CoreDNS 준비까지 기다리며, `test`는 GPU 없는 smoke Job과 클러스터 DNS를 검증합니다. kubeconfig는 `.local-k8s/`에 저장합니다.

클러스터가 준비되면 `./scripts/local-k8s.sh kubectl`로 Kubernetes 명령을 실행합니다.

```sh
./scripts/local-k8s.sh kubectl get pods -A
```

사용 후 클러스터를 삭제합니다. 노드 내부의 영구 볼륨 데이터도 삭제됩니다.

```sh
./scripts/local-k8s.sh down
```

멀티 노드 설정과 문제 해결은 [사용 가이드](docs/local-k8s.md)를 참고하세요.
