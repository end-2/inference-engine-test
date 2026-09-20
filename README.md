# Inference engine test (CPU)

kind 기반 로컬 Kubernetes 환경에서 CPU inference engine을 테스트합니다. 기본 구성은 단일 노드입니다.

## 준비 사항

- Docker가 실행 중인 호스트, POSIX 셸
- 도구 설치 시 `curl` 또는 `wget`, 체크섬 검증용 `sha256sum` 또는 `shasum`과 인터넷 연결
- 모델 다운로드 시 `curl`과 인터넷 연결
- 추론 실행 전 [CPU·메모리·디스크 요구사항](docs/requirements.md#cpu-메모리와-디스크)에 맞는 Docker 자원 확보

## 빠른 시작

저장소 루트에서 실행합니다. 아래 절차는 모델 없이 클러스터와 DNS를 확인합니다. 실제 추론은 다음 CPU 추론 API 절차로 실행합니다.

```sh
./scripts/local-k8s.sh install
./scripts/local-k8s.sh up
./scripts/local-k8s.sh test
```

## CPU 추론 API

`src/base`는 `llama-cpp-python`으로 GGUF 모델을 서빙하는 CPU 전용 채팅 API입니다.

위의 도구 설치를 마친 뒤 실행합니다. 모델은 별도로 내려받아 마운트하며, API 서버는 모델을 자동으로 다운로드하지 않습니다.

```sh
./scripts/download-model.sh
./scripts/local-k8s.sh up
IMAGE_TAG=0.1.0 ./scripts/build-inference-images.sh base
IMAGE_TAG=0.1.0 ./scripts/load-inference-images.sh base
./scripts/local-k8s.sh kubectl apply -f k8s/llama-base/
```

배포 후 [추론 API 가이드](docs/llama-api.md)에 따라 서버 준비를 기다리고, 포트를 연결한 뒤 요청을 보냅니다.

사용 후 `./scripts/local-k8s.sh down`으로 클러스터를 삭제합니다.

상세 내용은 [최소 요구사항](docs/requirements.md), [클러스터 사용](docs/local-k8s.md), [모델 관리](docs/models.md), [추론 API](docs/llama-api.md), [AIPerf 측정](docs/aiperf.md), [서비스 안정성 테스트](docs/availability-test.md), [CPU HPA 테스트](docs/hpa-test.md)를 참고하세요.
