# SmolLM2 멀티 노드 availability, pause, toleration 60초

2026-09-21 `transformers-tests` kind에서 worker 하나를 pause하고 대체 Pod와 노드 복구를 확인했습니다. 절차는 완료됐고, 관측 구간에는 timeout 8건이 발생했습니다.

## 측정 조건

- control-plane 1개, monitor worker 1개, engine worker 2개, Kubernetes v1.36.4.
- SmolLM2-135M-Instruct, revision `12fd25f77366fa6b3b4b768ec3050bf629380bac`, Transformers 4.57.6, torch 2.10.0, FP32.
- `transformers-base-metric` 2 replicas, Pod당 CPU 2개, 메모리 2Gi, PyTorch 2스레드. 모든 측정 컨테이너 requests=limits.
- AIPerf 0.12.0, concurrency 4, worker 1, timeout 30초, streaming, 매 요청 새 연결.
- 입력/출력 분포 `64,32:50;256,64:50`, 입력 16개, seed 42, sequential, `ignore_eos:true`.
- 90초 워밍업, 150초 정상 구간, 장애와 대체 Pod, 대체 후 90초, 노드 복구 후 90초.

## 복구 결과

| 항목 | 시간 |
| --- | ---: |
| 장애 요청 → Node NotReady 관측 | 49.9초 |
| 장애 요청 → 대체 Pod Ready 관측 | 115.4초 |
| 노드 복구 요청 → Node Ready 관측 | 10.4초 |
| Pod 초기화부터 수집과 재분산 완료까지 | 563.5초 |

`transformers-tests-worker2`를 pause하고 `worker3`에 대체 Pod가 준비됐습니다. 종료 후 worker2를 unpause하고 추론 Pod를 두 worker에 다시 분산했습니다. 60초는 Pod의 NoExecute toleration이며 노드 장애 감지 시간은 별도입니다.

## 요청 결과

| 집계 범위 | 성공 | 오류 | 성공률 | 성공 요청 평균 지연 |
| --- | ---: | ---: | ---: | ---: |
| 관측 구간에 시작한 요청 | 414 | 8 | 98.10% | 3.794초 |
| 전체 AIPerf, 워밍업과 종료 대기 포함 | 514 | 8 | 98.47% | 3.738초 |

관측 구간은 `run.json`의 `[collection_start, experiment_complete)`에 요청이 시작된 경우이며, 구간 이후 완료도 포함합니다. 오류 8건은 모두 TimeoutError입니다. 장애 전 3.4초부터 장애 후 45.6초 사이에 시작된 요청으로, 장애 순간 진행 중이던 요청과 endpoint 제거 전 요청이 포함됩니다. 절차 완료는 무오류 서비스를 뜻하지 않습니다. kind worker들은 한 Docker 호스트 자원을 공유합니다.

## 관측 시계열

관측 구간의 endpoint, 요청 지연과 TTFT, CPU를 같은 시간축에 표시했습니다. x축 0은 장애 요청 시각이며, 성공 요청은 완료 시각, 오류는 AIPerf 오류 로그 시각에 표시합니다. 빨간 ×의 높이 10은 지연값이 아닙니다. CPU는 kubelet 표본 시각으로 중복을 제거했습니다.

![SmolLM2 요청 지연, TTFT, 오류 시점과 ready endpoint, CPU](figures/observed-timeline.png)

[재실행 가이드](../../../guides/availability-test.md), [실행 시각](run.json), [원본과 요약](../../../../reports/transformers/availability-pause-60s-20260921-122415-594492/summary.json), [배포 스냅샷](../../../../reports/transformers/availability-pause-60s-20260921-122415-594492/prepared-kubernetes.txt), [AIPerf 요청별 결과](../../../../reports/transformers/availability-pause-60s-20260921-122415-594492/aiperf/profile_export.jsonl).
