# Mamba GPU 테스트 결과

RTX 2060 SUPER 8GB에서 `state-spaces/mamba-130m-hf`의 기본 엔진과 요청 간 prefix 상태 캐시를 비교했습니다. PyTorch 2.10.0+cu128, Transformers 4.57.6, FP16을 사용했습니다. 두 엔진 모두 Mamba 전용 커널이 없는 일반 PyTorch CUDA 경로입니다.

## AIPerf 검증

동시성 1, warmup 2개와 측정 요청 100개를 조건별로 1회 실행했습니다. 입력/출력 분포는 `64,32:50;256,64:50`, dataset entries 16, seed 42이며 순차적으로 입력을 재사용했습니다. 캐시는 sweep 전에 비웠으므로 warmup과 측정 초반의 miss도 포함합니다. 기본 엔진을 먼저 측정했습니다.

| 조건 | 요청 | 평균 TTFT(ms) | 평균 응답 시간(ms) | 출력 tok/s | 최대 GPU 메모리(MiB) | 원본 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| base | 100 | 252.44 | 1037.65 | 40.33 | 550 | [summary](aiperf-base-20260930/bench-20260930-025300-141375-local-transformers-mamba-base-gpu-0.1.0/summary.md) |
| cache | 100 | 80.40 | 907.72 | 46.09 | 550 | [summary](aiperf-cache-20260930/bench-20260930-025634-922097-local-transformers-mamba-cache-gpu-0.1.0/summary.md) |

이 실행에서 평균 TTFT는 68.1% 감소했고 출력 처리량은 14.3% 증가했습니다. 두 조건 모두 요청 실패와 출력 길이 부족이 없었습니다. 조건별 1회 측정이므로 반복 실험의 오차 범위는 산출하지 않았습니다.

공유 API는 cached token 수를 usage에 노출하지 않습니다. AIPerf의 prompt-cache hit 지표는 사용하지 않았으며 캐시 동작은 엔진의 복원 검사와 종료 로그로 확인했습니다.

종료 로그에는 RAM hit 84회, disk hit 0회, miss 18회, 복원 토큰 10284개와 캐시 오류 0개가 기록되었습니다. 이 집계에는 warmup 2개가 포함됩니다.

## 정확성 및 상태 복원

[직렬 엔진 검증](cache-check-20260930/summary.md)은 입력 64/256토큰과 출력 16토큰에서 기본, cold, warm과 재시작 후 disk 복원의 결과가 일치함을 확인합니다. 첫 텍스트 콜백의 시간은 AIPerf의 TTFT와 구분해 기록했습니다.

Python 테스트는 회귀 119개와 실제 HTTP 4개가 통과했습니다. GPU FP32/FP16, prefix 분기와 짧은 입력, 손상 복구, 취소, sampling, SSE, 동시 요청 4개의 결과 격리를 검사했습니다. 기존 SmolLM2 사전학습 모델 통합 테스트 2개는 이번 실행에서 제외했습니다.

## 재현

[Mamba 실행과 테스트 가이드](../../../guides/mamba-cache.md)를 따릅니다. 모델 revision은 [상태 복원 검증 메타데이터](cache-check-20260930/run.json)에, 이미지 digest는 각 AIPerf 실행의 `run.json`에 기록되어 있습니다. 측정 설정은 해당 `run.json`과 AIPerf 보고서에서 확인합니다. 검증한 GPU 이미지는 worker에 로드되어 있으므로 가이드의 빌드 생략 명령으로 다시 실행할 수 있습니다.

이미지는 기존 CUDA runtime을 OCI build context로 지정해 저장소 Dockerfile로 빌드했습니다. 일반 Docker 저장소의 여유 공간이 부족해 빌드 상태와 OCI 내보내기를 작업 디스크에 두었습니다. 측정 종료 후 Mamba Deployment는 0 replicas로 두고 기존 llama.cpp Deployment의 1 replica를 복원했습니다.
