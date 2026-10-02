# 추론 구현별 3회 반복 benchmark

네 조건을 각각 3회씩 측정한 12개 sweep이 모두 완료됐습니다. 본 측정 4,800회와 warmup 96회가 성공했으며 출력 길이 부족이나 초과는 없습니다.

- Status: complete
- Repetitions per condition: 3
- Inference node: `local-k8s-worker`; AIPerf node: `local-k8s-worker2`
- Each sweep uses concurrency 1, 2, 4, 8; each step has 2 warmup and 100 profiling requests.
- Each step starts with a fresh inference Pod. Image IDs and node placement are fixed across repetitions.
- Cache clear: empty PVC before every step. Cache preserve: empty PVC before the sweep, then retain it between steps.
- Cache clearing precedes warmup; cache can fill and be reused within each step.
- Execution order rotates by one condition each repetition. All sweeps run sequentially.
- Values are mean ± sample standard deviation across sweeps. TTFT p95 is the mean of per-sweep p95 values, not a pooled p95.

| Condition | Concurrency | Runs | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| base | 1 | 3 | 43.24 ± 0.57 | 628.68 ± 6.70 | 1119.64 ± 18.75 | 8.29 ± 0.15 |
| base | 2 | 3 | 43.83 ± 0.14 | 1572.32 ± 4.24 | 2062.74 ± 10.95 | 8.19 ± 0.10 |
| base | 4 | 3 | 44.03 ± 0.27 | 3442.62 ± 18.30 | 4319.00 ± 41.40 | 8.18 ± 0.11 |
| base | 8 | 3 | 44.45 ± 0.21 | 7009.25 ± 34.46 | 7984.90 ± 58.09 | 8.05 ± 0.10 |
| enhanced-batch | 1 | 3 | 49.35 ± 0.31 | 572.66 ± 4.78 | 1078.96 ± 9.91 | 6.70 ± 0.02 |
| enhanced-batch | 2 | 3 | 50.15 ± 0.32 | 854.30 ± 3.87 | 1449.09 ± 6.76 | 19.28 ± 0.35 |
| enhanced-batch | 4 | 3 | 50.57 ± 0.32 | 1334.28 ± 31.55 | 2609.01 ± 105.61 | 48.07 ± 1.35 |
| enhanced-batch | 8 | 3 | 51.69 ± 0.16 | 2525.54 ± 155.68 | 4050.89 ± 319.28 | 94.60 ± 4.37 |
| enhanced-cache-clear | 1 | 3 | 98.93 ± 0.31 | 106.16 ± 0.30 | 434.90 ± 5.90 | 7.71 ± 0.03 |
| enhanced-cache-clear | 2 | 3 | 98.53 ± 1.43 | 531.55 ± 6.42 | 1762.11 ± 17.06 | 7.70 ± 0.11 |
| enhanced-cache-clear | 4 | 3 | 97.20 ± 1.84 | 1388.29 ± 25.48 | 3330.59 ± 71.88 | 7.83 ± 0.18 |
| enhanced-cache-clear | 8 | 3 | 97.64 ± 0.52 | 3032.04 ± 17.64 | 6915.72 ± 10.30 | 7.73 ± 0.07 |
| enhanced-cache-preserve | 1 | 3 | 97.48 ± 0.78 | 107.07 ± 1.72 | 441.68 ± 2.58 | 7.83 ± 0.07 |
| enhanced-cache-preserve | 2 | 3 | 128.15 ± 2.75 | 336.58 ± 7.86 | 563.05 ± 21.63 | 7.68 ± 0.16 |
| enhanced-cache-preserve | 4 | 3 | 129.34 ± 1.89 | 969.95 ± 15.06 | 1300.33 ± 41.07 | 7.57 ± 0.07 |
| enhanced-cache-preserve | 8 | 3 | 130.01 ± 3.53 | 2190.50 ± 56.90 | 2602.04 ± 66.29 | 7.58 ± 0.17 |

## 비교 그래프

![3회 반복 처리량 및 TTFT 비교](figures/benchmark-comparison.png)

## Sweep reports

| Order | Repetition | Condition | Status | Report |
| ---: | ---: | --- | --- | --- |
| 1 | 1 | base | complete | [summary](r1/base/bench-20260920-091633-772941-local-llama-base-0.1.0/summary.md) |
| 2 | 1 | enhanced-batch | complete | [summary](r1/enhanced-batch/bench-20260920-092434-166531-local-llama-enhanced-batch-0.1.0/summary.md) |
| 3 | 1 | enhanced-cache-clear | complete | [summary](r1/enhanced-cache-clear/bench-20260920-093145-314357-local-llama-enhanced-cache-0.1.0/summary.md) |
| 4 | 1 | enhanced-cache-preserve | complete | [summary](r1/enhanced-cache-preserve/bench-20260920-093646-261612-local-llama-enhanced-cache-0.1.0/summary.md) |
| 5 | 2 | enhanced-batch | complete | [summary](r2/enhanced-batch/bench-20260920-094049-214568-local-llama-enhanced-batch-0.1.0/summary.md) |
| 6 | 2 | enhanced-cache-clear | complete | [summary](r2/enhanced-cache-clear/bench-20260920-094800-747005-local-llama-enhanced-cache-0.1.0/summary.md) |
| 7 | 2 | enhanced-cache-preserve | complete | [summary](r2/enhanced-cache-preserve/bench-20260920-095303-749128-local-llama-enhanced-cache-0.1.0/summary.md) |
| 8 | 2 | base | complete | [summary](r2/base/bench-20260920-095708-648602-local-llama-base-0.1.0/summary.md) |
| 9 | 3 | enhanced-cache-clear | complete | [summary](r3/enhanced-cache-clear/bench-20260920-100514-693326-local-llama-enhanced-cache-0.1.0/summary.md) |
| 10 | 3 | enhanced-cache-preserve | complete | [summary](r3/enhanced-cache-preserve/bench-20260920-101020-699662-local-llama-enhanced-cache-0.1.0/summary.md) |
| 11 | 3 | base | complete | [summary](r3/base/bench-20260920-101418-182171-local-llama-base-0.1.0/summary.md) |
| 12 | 3 | enhanced-batch | complete | [summary](r3/enhanced-batch/bench-20260920-102220-720274-local-llama-enhanced-batch-0.1.0/summary.md) |

`runs.csv` and `summary.jsonl` contain the individual sweep metrics; `summary.csv` includes mean, standard deviation, minimum, and maximum for every metric.
Image IDs, commands, and execution order are recorded in `run.json`. Per-request exports and resource time series are saved locally under each sweep report and are excluded from Git.

## 결과 해석

- Concurrency 2, 4, 8에서 cache 보존의 평균 처리량은 초기화보다 30.1~33.2% 높았습니다. Concurrency 8에서는 97.64 → 130.01 tok/s이며 TTFT 평균은 27.8% 낮았습니다.
- Concurrency 8에서 enhanced-batch의 처리량은 base보다 16.3% 높았습니다. TTFT 평균은 7009.25 → 2525.54 ms로 낮아졌지만, ITL 평균은 8.05 → 94.60 ms로 높아졌습니다.
- 데이터셋 16개를 같은 seed 42로 반복하는 부하의 결과입니다. 두 cache 조건 모두 sweep 시작은 빈 cache이며, 차이는 concurrency 단계 사이의 보존 여부입니다. Warmup과 본 측정 안에서는 cache가 다시 채워져 재사용됩니다.

## 검증과 환경

- [최종 검증 기록](verification.json): 48개 단계, 서로 다른 추론 Pod UID 48개, 본 측정 4,800회, warmup 96회, 출력 길이 부족이나 초과 0회.
- 48개 단계의 입력 데이터 파일 SHA-256이 동일합니다. 결과 경로, concurrency 값 외의 AIPerf 컨테이너 설정도 동일합니다. Cache 초기화 15회 모두 삭제 후 잔여 항목 0을 확인했습니다.
- 추론은 12 CPU, 16 GiB, AIPerf는 1 CPU, 1 GiB이며 requests와 limits가 같습니다. 저장된 추론, AIPerf Pod는 모두 지정 노드와 Guaranteed QoS를 검증했습니다.
- [환경 기록](environment.json): Docker VM의 15 CPU, 약 24 GiB를 kind 4개 노드가 공유합니다. 측정 전후 기존 background Deployment의 이미지, replica 수와 Docker 자원 설정은 같았습니다. 실행 중 모든 변형의 이미지 ID와 배치 노드를 고정했습니다.
- 측정 기간(UTC): 2026-09-20 09:16:20~10:29:33. 종료 시 `llama-base` Deployment는 enhanced-batch 이미지로 1/1 Ready였습니다.

## 재실행

[벤치마크 가이드](../../../guides/benchmark.md#전체-구현-반복-측정)에 따라 클러스터, 이미지를 준비하고 실제 노드를 선택합니다. 이 보고서의 이미지 ID와 실행 순서는 [run.json](run.json)에 있습니다. 다른 환경에서 얻은 결과는 위 실험 조건과 구분해 해석합니다.
