# Inference engine test (CPU)

kind 기반 로컬 Kubernetes 환경에서 CPU inference engine을 테스트합니다. 기본 구성은 단일 노드입니다.

## 준비 사항

- Docker가 실행 중인 호스트, POSIX 셸
- 도구 설치 시 curl 또는 wget, sha256sum 또는 shasum과 인터넷 연결

## 빠른 시작

저장소 루트에서 실행합니다.

```sh
./scripts/local-k8s.sh install
./scripts/local-k8s.sh up
./scripts/local-k8s.sh test
```

## CPU 추론 API

`src/base`는 `llama-cpp-python`으로 GGUF 모델을 서빙하는 CPU 전용 채팅 API입니다.

```sh
./scripts/download-model.sh
./scripts/local-k8s.sh up
IMAGE_TAG=0.1.0 ./scripts/build-inference-images.sh base
IMAGE_TAG=0.1.0 ./scripts/load-inference-images.sh base
./scripts/local-k8s.sh kubectl apply -f k8s/llama-base/
```

사용 후 `./scripts/local-k8s.sh down`으로 클러스터를 삭제합니다.

상세 내용은 [최소 요구사항](docs/requirements.md), [클러스터 사용](docs/local-k8s.md), [모델 관리](docs/models.md), [추론 API](docs/llama-api.md), [AIPerf 측정](docs/aiperf.md)을 참고하세요.
