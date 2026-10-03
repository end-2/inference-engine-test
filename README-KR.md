> English version: [English](README.md)

# Inference engine test

kind에서 Transformers와 llama.cpp의 추론, 배칭과 prefix 캐시를 측정합니다. CPU가 기본값이며 NVIDIA GPU, Mamba, Jamba와 분산 Prefill/Decode 실험은 전용 가이드에서 설명합니다.

## 사전 요구사항

- 실행 중인 로컬 Docker daemon, POSIX 셸, Python 3.10 이상과 `make`
- 다운로드와 체크섬 검증 도구, 초기 준비를 위한 인터넷 연결, 선택한 워크로드의 실행 자원: [실행 요구사항](docs/guides/requirements-KR.md) 참고

## 빠른 시작

저장소 루트에서 실행합니다.

```sh
make install
make benchmark-suite
```

kind, kubectl과 Helm을 설치한 뒤 모델, 클러스터와 이미지를 준비하고 기본 CPU 비교를 실행합니다. 결과는 `docs/reports/transformers/benchmark-suite-*/`에 저장합니다.

하나의 구현만 측정하려면 다음과 같이 실행합니다.

```sh
make benchmark VARIANT=transformers-enhanced-batch
```

구현 선택, 스크립트 직접 실행, 반복 수, 캐시 정책과 GPU 실행은 [벤치마크 가이드](docs/guides/benchmark-KR.md)를 참고합니다. 측정 없이 서버만 실행하려면 [추론 엔진 가이드](docs/guides/inference-engine-KR.md)를 참고합니다.

결과 수집 후 `make down`을 실행하면 CPU 클러스터와 노드 내부 PVC 데이터를 삭제합니다. 호스트 모델과 내보낸 보고서는 유지합니다.

## 가이드와 결과

- [소스 구조와 기능별 실험](docs/guides/feature-experiments-KR.md), [Helm 프로필](docs/guides/manifests-KR.md)
- [클러스터 구성](docs/guides/local-k8s-KR.md), [모델 관리](docs/guides/models-KR.md), [AIPerf](docs/guides/aiperf-KR.md)
- [Mamba 상태 캐시](docs/guides/mamba-cache-KR.md), [Jamba hybrid 배치와 HiCache](docs/guides/hybrid-cache-KR.md)
- [MPS GPU 공유](docs/guides/gpu-mps-KR.md), [분산 Prefill/Decode](docs/guides/prefill-decode-KR.md)
- [품질 검사](docs/guides/quality-check-KR.md), [가용성 테스트](docs/guides/availability-test-KR.md), [HPA 테스트](docs/guides/hpa-test-KR.md)
- [테스트 결과](docs/reports/README-KR.md), [Transformers CPU 보고서](docs/reports-transformers-KR.md)
