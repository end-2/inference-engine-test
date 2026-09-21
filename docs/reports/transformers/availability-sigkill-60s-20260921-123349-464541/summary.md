# SmolLM2 멀티 노드 availability, SIGKILL, toleration 60초

2026-09-21 `transformers-tests` kind의 engine worker 하나를 SIGKILL하고 대체 Pod, 노드 재시작과 원래 Docker 재시작 정책 복원을 확인했습니다. 절차는 완료됐고 관측 구간에 요청 오류 8건이 발생했습니다.

모델, 이미지, 토폴로지, CPU와 AIPerf 조건은 [pause 실험](../availability-pause-60s-20260921-122415-594492/summary.md#측정-조건)과 같습니다. 두 engine worker의 SmolLM2 FP32 Pod는 각각 CPU 2개, 메모리 2Gi, 2스레드이며, AIPerf concurrency는 4입니다. SIGKILL 직전 Docker 자동 재시작을 중지하고, 복구 후 원래 정책을 복원했습니다.

| 항목 | 시간 |
| --- | ---: |
| 장애 요청 → Node NotReady 관측 | 51.1초 |
| 장애 요청 → 대체 Pod Ready 관측 | 115.9초 |
| 노드 재시작 요청 → Node Ready 관측 | 1.6초 |
| Pod 초기화부터 수집과 재분산 완료까지 | 560.8초 |

`transformers-tests-worker2`를 종료하고 `worker3`에 대체 Pod가 준비됐습니다. 종료 후 worker2를 재시작하고 추론 Pod를 두 worker에 다시 분산했습니다. 60초는 Pod의 NoExecute toleration이며 노드 장애 감지 시간은 별도입니다.

| 집계 범위 | 성공 | 오류 | 성공률 | 성공 요청 평균 지연 |
| --- | ---: | ---: | ---: | ---: |
| 관측 구간에 시작한 요청 | 428 | 8 | 98.17% | 3.704초 |
| 전체 AIPerf, 워밍업과 종료 대기 포함 | 520 | 8 | 98.48% | 3.723초 |

관측 구간은 `run.json`의 `[collection_start, experiment_complete)`에 요청이 시작된 경우이며, 구간 이후 완료도 포함합니다. 오류는 TimeoutError 2건과 ClientConnectorError 6건입니다. 절차 완료와 사용자 요청의 오류율은 별도로 해석합니다. kind worker는 같은 Docker 호스트 자원을 공유합니다.

## 관측 시계열

관측 구간의 endpoint, 요청 지연과 TTFT, CPU를 같은 시간축에 표시했습니다. x축 0은 장애 요청 시각이며, 성공 요청은 완료 시각, 오류는 AIPerf 오류 로그 시각에 표시합니다. 빨간 ×의 높이 10은 지연값이 아닙니다. CPU는 kubelet 표본 시각으로 중복을 제거했습니다.

![SmolLM2 요청 지연, TTFT, 오류 시점과 ready endpoint, CPU](figures/observed-timeline.png)

[재실행 가이드](../../../guides/availability-test.md), [실행 시각](run.json).
