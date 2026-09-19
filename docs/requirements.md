# 실행을 위한 최소 요구사항

CPU 전용 kind 클러스터를 실행하기 위한 준비 조건입니다. 기본 버전은 [도구 설정](../config/versions.env)을 기준으로 합니다. 다른 버전의 지원 여부는 실제 실행으로 확인해야 합니다.

## 의존성 최소화와 OS 호환성

- 스크립트는 POSIX `sh`와 `awk`, `grep`, `mktemp` 등 일반적인 명령만 사용합니다. bash 전용 문법, Python, jq, yq, helm, kustomize는 필요하지 않습니다.
- 클러스터 준비에 필요한 도구는 kind, kubectl, Docker뿐입니다. 설치에는 `curl` 또는 `wget`, `sha256sum` 또는 `shasum` 중 하나만 있으면 됩니다.
- `make`는 선택 사항이며 각 스크립트를 직접 실행할 수 있습니다.

## 호스트 OS와 컨테이너 환경

| 항목 | 요구사항 |
| --- | --- |
| OS | 로컬 Linux, macOS, Windows(WSL2). Docker가 지원하는 배포판과 커널 |
| cgroup | 기본 Kubernetes 구성에 필요한 cgroup v2 활성화 |
| CPU 아키텍처 | x86_64 또는 arm64. 노드 이미지는 호스트와 같은 아키텍처 |
| Docker | 로컬 Docker Engine과 현재 사용자의 Docker 접근 권한 |
| 노드 실행 | kind의 privileged 노드 컨테이너 실행과 호스트 디렉터리 bind mount가 가능한 환경 |
| 셸 | POSIX `sh`와 `awk`, `grep`, `mktemp` 등 일반적인 명령 |

특정 OS 릴리스나 커널 패치 버전을 코드에서 강제하지 않습니다. cgroup 확인 방법은 [Kubernetes 안내](https://kubernetes.io/docs/concepts/architecture/cgroups/)를 참고합니다.

빌드와 클러스터 실행에는 같은 로컬 Docker 데몬을 사용합니다.

## kind와 Kubernetes

[versions.env](../config/versions.env)의 kind, kubectl과 노드 이미지 조합을 사용합니다. 노드 이미지는 호스트와 같은 CPU 아키텍처여야 합니다. 버전을 변경할 때는 [kind 릴리스의 지원 이미지](https://github.com/kubernetes-sigs/kind/releases)와 [kubectl 버전 차이 정책](https://kubernetes.io/releases/version-skew-policy/#kubectl)을 확인합니다.

클러스터는 `local-k8s.sh up`으로 생성합니다. GPU, CDI, device plugin, 모델 마운트 설정은 포함하지 않습니다. 설정 변경은 [클러스터 가이드](local-k8s.md)를 참고합니다.

## 작업별 추가 도구

| 작업 | 추가 요구사항 |
| --- | --- |
| kind와 kubectl 설치 | `curl` 또는 `wget`, `sha256sum` 또는 `shasum` |
| 이미지 빌드 | `docker build` |
| Makefile 명령 | `make`. 각 스크립트를 직접 실행할 때는 불필요 |

## CPU, 메모리와 디스크

CPU 기반 테스트이므로 GPU 자원 요청은 없습니다. 노드 수와 workload에 맞춰 CPU, 메모리와 디스크를 확보합니다. 디스크에는 Docker 이미지와 빌드 캐시, kind 노드의 이미지 사본, 임시 아카이브와 결과를 저장할 공간이 필요합니다. `TMPDIR`와 Docker 데이터 경로의 여유 공간도 확인합니다.

## 네트워크와 오프라인 실행

최초 설치와 빌드에는 사용하는 파일의 배포처에 HTTPS로 접근할 수 있어야 합니다.

| 대상 | 주요 배포처 |
| --- | --- |
| kind와 kubectl | GitHub 릴리스, `dl.k8s.io` |
| 노드와 보조 이미지 | Docker Hub 등의 컨테이너 레지스트리 |

프록시나 방화벽 환경에서는 리다이렉트되는 다운로드 호스트와 CDN도 허용해야 합니다. 도구와 이미지를 미리 준비하면 [오프라인 절차](local-k8s.md#환경-준비)로 실행할 수 있습니다.

기본 네트워크는 IPv4이며 Kubernetes API는 로컬 `127.0.0.1`에 바인딩됩니다. Docker 네트워크와 클러스터 DNS가 동작하고 Pod 및 Service 대역이 호스트나 VPN 대역과 충돌하지 않아야 합니다. 원격 접속이나 IPv6 구성이 필요하면 [클러스터 설정](local-k8s.md#클러스터-설정)을 변경해야 합니다.

## 실행 전 확인

호스트 준비와 도구 설치를 마친 뒤 저장소 루트에서 확인합니다.

```sh
uname -s
uname -m
./scripts/local-k8s.sh doctor
```

`doctor`는 도구 존재와 Docker 접근을 확인하지만 모든 버전 조합과 파일 권한을 보장하지는 않습니다.

클러스터 생성과 smoke 연산 확인은 [빠른 시작](../README.md#빠른-시작)을 따릅니다.
