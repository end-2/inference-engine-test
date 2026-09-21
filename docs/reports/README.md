# 테스트 결과

보고서는 측정한 inference backend별로 구분합니다.

- [llama.cpp 결과](llamacpp/README.md): Qwen2.5 GGUF, base, batch, cache, 안정성 및 HPA 실험
- [Transformers 결과](transformers/README.md): SmolLM2-135M-Instruct FP32, base, batch, cache 성능 비교, 노드 장애 복구 및 CPU HPA 실험

각 보고서의 원본에는 측정 당시의 이미지 이름과 실행 설정을 보존합니다. 실행 방법은 [벤치마크 가이드](../guides/benchmark.md), AIPerf에 대한 설명은 [AIPerf 가이드](../guides/aiperf.md)를 참고하세요.
