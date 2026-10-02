# GPU Prefill/Decode 실험 종합

SmolLM2-135M-Instruct FP16을 RTX 2060 SUPER 8 GiB 한 장에서 실행한 결과입니다. MPS 슬롯 수, worker 역할과 스케줄러별로 보고서를 구분합니다. A2와 A4는 전체 추론 worker 2개와 4개, P1D1과 P1D3는 Prefill worker 1개와 Decode worker 1개 및 3개입니다.

## 주요 결과

| 비교 | 관측 결과 | 해석 범위 |
| --- | --- | --- |
| Serial, A2와 P1D1 | 동시성 8에서 P1D1 처리량은 A2의 0.53~0.57배 | 3회 계획 중 1회만 완료. 두 번째 반복의 Router OOM으로 전체 실행 중단 |
| Serial, A4와 P1D3 | 40개 조건 중 39개에서 A4 처리량이 높고, 동시성 8의 P1D3/A4는 0.76~0.83배 | 3회 완료. P1D3가 높았던 1개 조건의 차이는 약 0.2%로 반복 변동보다 작음 |
| Token budget, 같은 예산 비교 | 예산 32와 256의 총 20개 조건 모두 A4의 평균 TTFT가 더 낮음 | 예산마다 2회 반복. 예산을 고정한 비교에서는 P1D3의 TTFT 우위를 확인하지 못함 |
| Token budget, TPOT 목표를 만족하는 예산 선택 | 704/16, 동시성 16에서 P1D3의 평균 TTFT 35.8% 감소, TPOT-only goodput 38.4% 증가 | TPOT 40 ms 이하를 매 반복 95% 이상 충족하는 A4 예산 32와 P1D3 예산 256 비교 |

마지막 행은 제한된 예산 탐색에서 얻은 조건부 결과입니다. 같은 workload에서 TPOT 상한을 75 ms로 완화하면 A4 예산 256도 충족하며 TTFT가 더 낮습니다. 선택 기준과 전체 수치는 [스케줄러 분석](scheduler-20261002/analysis.md)에 있습니다.

Serial 실험은 Decode worker 수와 HTTP KV 전달 비용의 영향을 포함합니다. 4분할의 긴 입력과 긴 출력에서는 worker 로그상 Prefill 계산 비중이 약 1.8%여서, 분리로 겹칠 수 있는 계산량이 작았습니다. 이 값은 여러 동시성과 워밍업을 포함한 진단 평균이며 특정 조건의 TTFT 분해값이 아닙니다. [4분할 원인 분석](benchmark-four-20261001/analysis.md)을 참고합니다.

## 실험 목록

요청 수는 워밍업을 제외한 측정 표본입니다. 기능 검사와 메모리 스트레스 검사를 성능 반복에 합산하지 않습니다.

| 보고서 | 구성과 범위 | 완료 반복, 측정 요청 | 상태와 근거 |
| --- | --- | --- | --- |
| [2분할 성능](benchmark-20260930/summary.md) | Serial A2/P1D1, 길이 분포 10개, 동시성 1, 2, 4, 8 | 1/3회, 2,560개 | 완료 반복의 오류 0개. [중단 및 OOM 분석](benchmark-20260930/stability.md), 원본 상태는 failed |
| [본문 수명 수정 후 GPU 검사](memory-fix-20260930/summary.md) | Serial A2/P1D1, 축소 workload | 1회, 160개 | 오류와 Pod 재시작 0회. 전체 matrix 재측정은 아님 |
| [Router 메모리](router-memory-20261001/summary.md) | GPU 추론 없이 HTTP mock, 동시성 8, 상태 약 16.33 및 64 MiB | 768개 | cgroup 최대 258.5 MiB, 1 GiB 상한, OOM과 재시작 0회 |
| [4분할 구성 확인](four-slot-check-20261001/validation.md) | Serial A4/P1D3, 축소 workload와 CUDA client 확인 | 1회, 64개 | 요청 분산, 동일 자원 예산과 출력 길이 확인 |
| [4분할 성능](benchmark-four-20261001/summary.md) | Serial A4/P1D3, 길이 분포 10개, 동시성 1, 2, 4, 8 | 3회, 7,680개 | 오류, Router OOM과 Pod 재시작 0회. [실행 검증](benchmark-four-20261001/validation.md) |
| [예산 32](scheduler-20261002-b32/summary.md) | Token budget A4/P1D3, 길이 분포 5개, 동시성 4, 16 | 2회, 960개 | [SLO별 goodput](scheduler-20261002-b32/goodput/separate.md) |
| [예산 256](scheduler-20261002-b256/summary.md) | Token budget A4/P1D3, 길이 분포 5개, 동시성 4, 16 | 2회, 960개 | [SLO별 goodput](scheduler-20261002-b256/goodput/separate.md) |

두 예산의 총 1,920개 요청에서 오류, Router OOM과 worker 재시작은 0회였습니다. [예산 간 비교 및 GPU 출력 검증](scheduler-20261002/analysis.md)은 위 두 실행을 재분석한 결과이며 별도 측정 표본이 아닙니다.

[vLLM 소스 검토](benchmark-four-20261001/vllm-source-analysis.md)는 스케줄러 구현을 검토한 참고 자료입니다. vLLM으로 측정한 성능 결과는 포함하지 않습니다.

MPS 자체의 모델 동시 실행은 [별도 검증](../mps-check-20260930/summary.md)에 있습니다. 6개 모델 조합에서 48개 생성 요청이 성공했으며 HTTP 서버 성능 비교에는 포함하지 않습니다.

## 비교 조건과 주의점

- Serial은 입력 64, 256, 704와 출력 16, 64, 256의 조합 및 혼합 부하를 사용합니다. Scheduler는 입력 64, 704와 출력 16, 128의 조합 및 다른 혼합 부하를 사용하므로 두 보고서 전체의 평균을 직접 비교하지 않습니다.
- 실제 고정 길이 입력은 채팅 템플릿을 포함해 94, 286, 734토큰입니다. 혼합 부하의 실제 길이별 표본 수는 개별 보고서에 기록합니다.
- 처리량과 평균 지연은 반복별 산술 평균, 표준편차는 반복 간 sample SD, p95는 같은 조건의 요청을 합친 nearest-rank입니다. 단일 반복에는 반복 간 변동 추정이 없습니다.
- TTFT에는 큐 대기, tokenizer, HTTP 경로와 TextStreamer 버퍼가 포함됩니다. TPOT는 요청별 `(전체 지연 - TTFT) / (출력 토큰 수 - 1)`이며 개별 토큰의 tail latency가 아닙니다.
- TPOT-only goodput과 TTFT 및 TPOT를 동시에 제한한 goodput을 구분합니다. 모든 반복의 충족률이 기준을 넘는지 확인한 뒤 설정을 선택합니다.
- 물리 GPU 한 장의 MPS 공유, 작은 모델과 CPU를 경유하는 HTTP KV 전송 결과입니다. 별도 물리 GPU, RDMA, NVLink 또는 실제 vLLM의 성능으로 일반화하지 않습니다.

## 실행과 자료 보존

[2분할 실행](../../../guides/prefill-decode.md), [4분할 실행](../../../guides/prefill-decode-4.md), [스케줄러 실행](../../../guides/prefill-decode-scheduler.md)에서 재현 명령과 요구사항을 확인합니다. 과거 보고서의 환경 복구 기록은 측정 종료 당시 상태입니다.

각 실행의 JSON은 설정과 소스 해시, CSV는 집계 수치, Markdown과 그림은 해석을 보존합니다. `reports/pd/<실행명>/`의 요청별 원본과 로그는 로컬에 보관하며 Git에는 포함하지 않습니다. 원본이 없는 checkout에서는 보고서를 열람할 수 있지만 요청 단위 재집계와 goodput 재생성은 할 수 없습니다. [결과 정리 가이드](../../../guides/experiment-results.md)에 보존 파일과 검증 절차가 있습니다.
