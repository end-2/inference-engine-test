# 벤치마크 결과

`make benchmark`는 실행별 디렉터리에 요약, 요청별 원본 AIPerf 결과, CPU·메모리 시계열과 재현에 필요한 이미지·Pod 정보를 저장합니다. 각 동시성 측정 전 추론 Pod를 재시작합니다.

실행 방법과 결과 구성은 [AIPerf 가이드](../aiperf.md)를 참고하세요. 각 실행의 `summary.md`에서 측정 결과를 확인하고 `run.json`의 `status`가 `complete`인지 확인합니다.

서비스 안정성 보고서는 각 실험의 요약·환경·관찰·해석을 독립적으로 담습니다. [실행 가이드](../availability-test.md#네-가지-실험-재실행)에서 같은 조건을 재실행할 수 있습니다.

| 장애 주입 | NoExecute toleration | 보고서 |
| --- | ---: | --- |
| Docker pause | 300초 | [실험 보고서](availability-20260920-045929/summary.md) |
| Docker SIGKILL | 300초 | [실험 보고서](availability-sigkill-20260920-053546/summary.md) |
| Docker pause | 60초 | [실험 보고서](availability-pause-60s-20260920-061021/summary.md) |
| Docker SIGKILL | 60초 | [실험 보고서](availability-sigkill-60s-20260920-061946/summary.md) |
