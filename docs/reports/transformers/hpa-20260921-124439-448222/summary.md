# SmolLM2 멀티 노드 CPU HPA, 1→4→1

2026-09-21 `transformers-tests` kind에서 HPA의 확장, 고부하 유지, 축소와 축소 후 성공 요청을 확인했습니다. `status=complete`이며 고부하 233건과 저부하 5건이 모두 성공했습니다.

## 조건과 판정

- control-plane 1개, monitor worker 1개, engine worker 2개, Kubernetes v1.36.4.
- SmolLM2-135M-Instruct FP32, Transformers 4.57.6, torch 2.10.0, `transformers-base-metric` 이미지.
- 추론 Pod당 CPU 2개, 메모리 2Gi, PyTorch 2스레드, requests=limits. 호스트와 이미지 ID는 [원본 요약](../../../../reports/transformers/hpa-20260921-124439-448222/summary.json)의 environment에 기록했습니다.
- CPU request 대비 평균 50%, min 1, max 4. 확장 안정화 0초, 축소 안정화 120초, 각 방향 30초당 Pod 1개.
- AIPerf 고부하 concurrency 8, 저부하 concurrency 1 및 constant 0.02 req/s. worker 1, timeout 30초, streaming, 매 요청 새 연결.
- 입력/출력 분포 `64,32:50;256,64:50`, 입력 16개, seed 42, sequential, `ignore_eos:true`.
- baseline 30초와 각 목표 도달 후 60초 유지. HPA current/desired, Deployment, Ready Pod, ready endpoint를 함께 판정합니다.

## 결과

| 항목 | 결과 |
| --- | ---: |
| 고부하 시작 요청 → 4 replicas, Ready endpoint 4개 | 129.6초 |
| 부하 감소 요청 → 1 replica, Ready endpoint 1개, 종료 중 Pod 없음 | 212.1초 |
| baseline 대기부터 자료 수집 완료까지 | 536.2초, 8분 56초 |
| 고부하 성공 / 오류 | 233 / 0 |
| 저부하 성공 / 오류 | 5 / 0 |
| 축소 후 유지 구간 안에서 시작하고 완료된 성공 요청 | 1 |

확장 시간은 `high_load_requested`부터 `scale_out_observed`, 축소 시간은 `load_reduction_requested`부터 `scale_in_observed`까지입니다. 클라이언트 초기화와 고부하 종료, 저부하 시작에 필요한 시간도 포함합니다. 요청 수는 각 AIPerf 단계의 전체 요청별 기록을 집계했습니다.

4 replicas에서 각 engine worker에 Pod 2개가 배치됐습니다. 저부하 후 4→3→2→1로 줄었고, 최종 1개 상태에서 실제 요청 성공을 확인했습니다. 종료 시 AIPerf와 renderer는 0개, 추론 서버는 1개이며 원래 고부하 인자를 복원했습니다. 같은 Docker 호스트를 공유하는 kind의 Pod 확장 검증이며 노드 증설 실험은 아닙니다.

## Grafana 패널

실제 Grafana 패널을 **2026-09-21 12:44:39.449~12:53:35.605 UTC**로 고정해 추출했습니다. 고부하 시작 요청은 **12:45:42.421 UTC**, 저부하 전환 요청은 **12:48:54.496 UTC**입니다. 추출은 실험 종료 후 13:52:14 UTC에 시작했고, 완료 후 renderer를 정지했습니다.

### CPU와 replica

초기 CPU 공백과 HPA desired 0은 상태 지표가 채워지기 전 구간입니다. 이때도 실제 가용 Pod와 ready endpoint는 각각 1개였습니다.

![Grafana: CPU request 대비 평균 사용률과 목표 50%](figures/grafana-cpu.png)

![Grafana: HPA desired, current와 가용 Pod의 1→4→1 변화](figures/grafana-replicas.png)

### Endpoint와 처리 중 요청

![Grafana: Service ready endpoint의 증가와 축소](figures/grafana-endpoints.png)

![Grafana: Pod별 처리 중 요청](figures/grafana-in-flight.png)

### 요청 처리량과 TTFT

요청 처리량은 서버 outcome별 counter의 1분 rate이며, TTFT p95는 같은 1분 구간의 서버 histogram 추정치입니다. AIPerf의 요청별 결과와 집계 방식이 다릅니다.

![Grafana: 서버 outcome별 완료 요청 처리량](figures/grafana-requests.png)

![Grafana: 서버 TTFT p95](figures/grafana-ttft.png)

패널 ID, 시간 범위와 추출 시각은 [캡처 기록](../../../../reports/transformers/hpa-20260921-124439-448222/grafana-capture.json)에 있습니다.

[재실행 가이드](../../../guides/hpa-test.md), [실행 시각과 부하 인자](run.json), [5초 간격 관측](../../../../reports/transformers/hpa-20260921-124439-448222/observations.csv), [고부하와 저부하 원본](../../../../reports/transformers/hpa-20260921-124439-448222/aiperf), [Prometheus 시계열](../../../../reports/transformers/hpa-20260921-124439-448222/prometheus).
