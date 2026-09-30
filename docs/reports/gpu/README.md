# GPU 추론 벤치마크 결과

> **주의:** 기존 CPU 벤치마크와 이번 GPU 벤치마크는 호스트 환경과 클러스터 배치가 달라 성능 수치를 직접 비교하면 안 됩니다.

이번 GPU 측정은 각 구현을 1회 실행했습니다. 동시성은 `1,2,4,8`이며 조건마다 warmup 요청 2개와 측정 요청 100개를 사용했습니다. 추론 Pod는 RTX 2060 SUPER가 할당된 worker에서, AIPerf는 control-plane에서 실행했습니다.

| 엔진 | 모델 | GPU 설정 | 측정 조건 | 결과 |
| --- | --- | --- | --- | --- |
| Transformers | `HuggingFaceTB/SmolLM2-135M-Instruct` | `dtype=float16` | base, batch, cache | [1회차 요약](transformers/benchmark-suite-20260928-141725-165948/summary.md) |
| llama.cpp | `Qwen/Qwen2.5-0.5B-Instruct` | `n_gpu_layers=-1` | base, batch, cache 초기화, cache 보존 | [1회차 요약](llamacpp/benchmark-suite-20260928-144903-213311/summary.md) |

각 요약에는 동시성별 처리량, 지연, GPU 사용률과 사용 메모리의 평균 및 최대값이 있습니다. `run.json`에는 실행 설정과 이미지 ID가 있으며, `gpu.csv` 시계열은 로컬 결과 디렉터리에 보관합니다.

Transformers batch의 `max-parallel` 설정 실험은 [설정 실험 보고서](transformers/batch-config-tuning-20260928.md)에, GPU 전용 배치 구현의 결과는 [최적화 보고서](transformers/batch-gpu-optimization-20260928.md)에 있습니다.

GPU batch의 높은 동시성에서 실제 모델 출력을 대조한 결과는 [출력 검증 보고서](transformers/batch-gpu-output-validation-20260929.md)에 있습니다.

Mamba-130M의 prefix 상태 캐시 구현, 정확성 검사와 동시성 1의 AIPerf 비교는 [Mamba GPU 테스트 결과](mamba/README.md)를 참고하세요.
