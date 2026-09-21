# 실행을 위한 최소 요구사항

CPU 전용 kind 클러스터와 추론, 측정 워크로드를 실행하기 위한 준비 조건입니다. 기본 버전은 [도구 설정](../../config/versions.env)을 기준으로 합니다. 다른 버전의 지원 여부는 실제 실행으로 확인해야 합니다.

## 호스트 OS와 컨테이너 환경

| 항목 | 요구사항 |
| --- | --- |
| OS | 로컬 Linux, macOS, Windows(WSL2). Docker가 지원하는 배포판과 커널 |
| cgroup | 기본 Kubernetes 구성에 필요한 cgroup v2 활성화 |
| CPU 아키텍처 | x86_64 또는 arm64. 노드 이미지는 호스트와 같은 아키텍처 |
| Docker | 로컬 Docker Engine과 현재 사용자의 Docker 접근 권한 |
| 노드 실행 | kind의 privileged 노드 컨테이너 실행과 호스트 디렉터리 bind mount가 가능한 환경 |
| 셸 | POSIX `sh`와 `awk`, `grep`, `mktemp` 등 일반적인 명령 |

빌드와 클러스터 실행에는 같은 로컬 Docker 데몬을 사용합니다.

## kind와 Kubernetes

[versions.env](../../config/versions.env)의 kind, kubectl과 노드 이미지 조합을 사용합니다. 노드 이미지는 호스트와 같은 CPU 아키텍처여야 합니다. 버전을 변경할 때는 [kind 릴리스의 지원 이미지](https://github.com/kubernetes-sigs/kind/releases)와 [kubectl 버전 차이 정책](https://kubernetes.io/releases/version-skew-policy/#kubectl)을 확인합니다.

클러스터는 `local-k8s.sh up`으로 생성하며 GPU, CDI, device plugin 설정은 포함하지 않습니다. `up`은 호스트 모델 디렉터리를 노드의 `/models`에 읽기 전용으로 마운트합니다. 모델 다운로드와 경로 설정은 [모델 볼륨 가이드](models.md), 클러스터 설정 변경은 [클러스터 가이드](local-k8s.md)를 참고합니다.

## 작업별 추가 도구

| 작업 | 추가 요구사항 |
| --- | --- |
| kind와 kubectl 설치 | 다운로드용 `curl` 또는 `wget`, 체크섬 검증용 `sha256sum` 또는 `shasum` |
| 모델과 토크나이저 다운로드 | `curl`, 체크섬 검증용 `sha256sum` 또는 `shasum` |
| 이미지 빌드 | `docker build` |
| [벤치마크 자동 측정](benchmark.md#pod-재시작을-포함한-자동-측정) | Python 3.10 이상 |
| Makefile 명령 | `make`. 각 스크립트를 직접 실행할 때는 불필요 |

## CPU, 메모리와 디스크

선택한 추론 Deployment와 [AIPerf Job](../../k8s/aiperf/job.yaml)의 자원 요청량을 합산하고 Kubernetes 시스템 Pod의 여유분을 확보합니다. 추론 설정은 [Transformers](../../k8s/transformers-base/deployment.yaml) 또는 [llama.cpp](../../k8s/base-llamacpp/deployment.yaml) 매니페스트에서 확인합니다. Docker를 VM에서 실행하면 VM에 할당한 자원도 확인합니다. 측정 자원은 실행 환경에 맞춰 조정하되 `requests=limits`를 유지합니다.

디스크에는 [모델 파일](models.md#다운로드), Docker 이미지와 빌드 캐시, kind 노드의 이미지 사본, 임시 아카이브와 결과를 저장할 공간이 필요합니다. `TMPDIR`와 Docker 데이터 경로의 여유 공간도 확인합니다.

## 네트워크

최초 설치, 이미지 빌드와 모델과 토크나이저 다운로드에는 사용하는 파일의 배포처에 HTTPS로 접근할 수 있어야 합니다.

| 대상 | 주요 배포처 |
| --- | --- |
| kind와 kubectl | GitHub 릴리스, `dl.k8s.io` |
| 노드와 보조 이미지 | Docker Hub 등의 컨테이너 레지스트리 |
| 이미지 빌드 의존성 | Debian 패키지 저장소, PyPI |
| 모델과 토크나이저 | Hugging Face |

프록시나 방화벽 환경에서는 리다이렉트되는 다운로드 호스트와 CDN도 허용해야 합니다. 오프라인 실행에는 [도구와 이미지](local-k8s.md#환경-준비), 추론용 [모델](models.md), AIPerf 측정용 [토크나이저](aiperf.md#토크나이저-준비)를 미리 준비합니다.

기본 네트워크는 IPv4이며 Kubernetes API는 로컬 `127.0.0.1`에 바인딩됩니다. Docker 네트워크와 클러스터 DNS가 동작하고 Pod 및 Service 대역이 호스트나 VPN 대역과 충돌하지 않아야 합니다. 원격 접속이나 IPv6 구성이 필요하면 [클러스터 설정](local-k8s.md#클러스터-설정)을 변경해야 합니다.

## 실행 전 확인

호스트 준비와 도구 설치를 마친 뒤 저장소 루트에서 확인합니다.

```sh
uname -s
uname -m
./scripts/local-k8s.sh doctor
```

`doctor`는 도구 존재와 Docker 접근을 확인하지만 모든 버전 조합과 파일 권한을 보장하지는 않습니다.

기본 실험은 [빠른 시작](../../README.md#빠른-시작), 서버만 배포하는 방법은 [Transformers 가이드](inference-engine.md#docker와-kubernetes)를 따릅니다. 모델 없이 클러스터와 DNS만 확인하려면 `scripts/local-k8s.sh up` 후 `scripts/local-k8s.sh test`를 실행합니다.
