# 테스트 결과

보고서는 측정한 inference backend별로 구분합니다.

- [llama.cpp 결과](llamacpp/README.md): Qwen2.5 GGUF, base, batch, cache, 안정성 및 HPA 실험
- [Transformers 결과](transformers/README.md): SmolLM2-135M-Instruct FP32, base, batch, cache 성능 비교, 노드 장애 복구 및 CPU HPA 실험
- [MPS 모델 동시 실행 검증](gpu/mps-check-20260930/summary.md): 같은 GPU에서 모델 조합 6개의 CUDA 생성 확인
- [GPU Prefill/Decode 실험 종합](gpu/pd/README.md): 2분할과 4분할 성능, Router 메모리, token budget 및 SLO별 결과

각 보고서의 원본에는 측정 당시의 이미지 이름과 실행 설정을 보존합니다. 실행 방법은 [벤치마크 가이드](../guides/benchmark.md), AIPerf에 대한 설명은 [AIPerf 가이드](../guides/aiperf.md)를 참고하세요.

PD 실험의 보고서 구성, 집계 확인과 Git 보존 범위는 [실험 결과 정리 가이드](../guides/experiment-results.md)를 따릅니다.
