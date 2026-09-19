# 벤치마크 결과

`make benchmark`는 실행별 디렉터리에 요약, 요청별 원본 AIPerf 결과, CPU·메모리 시계열과 재현에 필요한 이미지·Pod 정보를 저장합니다. 각 동시성 측정 전 추론 Pod를 재시작합니다.

실행 방법과 결과 구성은 [AIPerf 가이드](../aiperf.md)를 참고하세요. 각 실행의 `summary.md`에서 측정 결과를 확인하고 `run.json`의 `status`가 `complete`인지 확인합니다.
