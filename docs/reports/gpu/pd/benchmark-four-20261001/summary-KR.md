# Aggregation과 Prefill/Decode disaggregation 성능 비교

SmolLM2-135M-Instruct, FP16, GPU: `NVIDIA GeForce RTX 2060 SUPER, GPU-7b77b97b-2222-89f1-2d5e-5c488faedd7b, 580.126.09, 8192 MiB`.

집계에 포함한 측정 요청은 7,680개이며, 이 요청들의 오류는 0개입니다. 입력과 출력 조합 10개, 동시성 [1, 2, 4, 8], 3회 반복이며 조건과 반복별 32개 요청을 측정했습니다.

Disaggregation의 평균 처리량이 aggregation보다 높은 조건은 40개 중 1개입니다. 이는 단일 GPU의 MPS share 4개와 CPU 메모리를 경유하는 HTTP 상태 전달 구현에 대한 결과입니다.

동시성 8에서 disaggregation / aggregation 처리량 비율은 0.76x부터 0.83x입니다.

![처리량 비율](figures/throughput-ratio.png)

## 동시성 8 비교

A는 aggregation, D는 disaggregation입니다. 입력 길이는 합성 텍스트 기준이며 실제 사용량은 표에 별도로 표시합니다.

| 입력/출력 | 실제 입력 평균 | A tok/s | D tok/s | D 변화 | A TTFT ms | D TTFT ms | A p95 지연 ms | D p95 지연 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 64/16 | 94.0 | 123.92 | 94.72 | -23.6% | 531.3 | 794.8 | 1092.3 | 1615.0 |
| 64/64 | 94.0 | 129.66 | 98.27 | -24.2% | 1792.0 | 2823.8 | 4130.6 | 6074.5 |
| 64/256 | 94.0 | 129.44 | 98.41 | -24.0% | 6928.3 | 11119.3 | 16475.4 | 23598.8 |
| 256/16 | 286.0 | 122.98 | 94.08 | -23.5% | 539.6 | 801.9 | 1118.5 | 1569.1 |
| 256/64 | 286.0 | 127.50 | 96.57 | -24.3% | 1816.2 | 2877.1 | 4389.3 | 5983.0 |
| 256/256 | 286.0 | 128.69 | 97.27 | -24.4% | 6950.1 | 11205.1 | 16889.4 | 23873.9 |
| 704/16 | 734.0 | 100.30 | 83.12 | -17.1% | 767.5 | 960.2 | 1360.9 | 1866.1 |
| 704/64 | 734.0 | 120.95 | 94.06 | -22.2% | 2041.1 | 3013.7 | 4389.8 | 6125.6 |
| 704/256 | 734.0 | 127.05 | 96.32 | -24.2% | 7184.4 | 11394.0 | 16540.0 | 23809.7 |
| 혼합 | 374.0 | 107.19 | 89.48 | -16.5% | 4703.9 | 7200.2 | 15940.8 | 22680.7 |

![처리량과 TTFT](figures/throughput-ttft.png)

## 측정 조건

- Aggregation: 전체 추론 worker 4개. Disaggregation: Prefill worker 1개와 Decode worker 3개.
- 각 worker는 MPS share 1개, CPU 요청 1과 상한 2, 메모리 2 GiB를 사용합니다. 두 mode 모두 같은 CPU router를 사용합니다.
- 물리 GPU 하나를 MPS share 4개로 나누며 client별 active thread 한도는 25%입니다.
- Greedy decoding, EOS 억제, 요청별 batch 1, prefix cache와 continuous batching 비활성화입니다.
- 합성 입력 [64, 256, 704], 출력 [16, 64, 256]의 모든 조합을 측정했습니다. 혼합 분포는 `64,256:50;704,16:50`입니다.
- AIPerf 0.12.0, seed 42, 데이터셋 32개, sequential sampling을 사용했습니다.
- 혼합 부하에서 실제 측정된 입력/출력별 반복당 요청 수는 94/256토큰 18개, 734/16토큰 14개입니다. 설정의 확률과 유한 데이터셋의 실제 비중은 다를 수 있습니다.
- 각 조건의 워밍업 4개는 통계에서 제외했습니다. 배포, 모델 로딩과 AIPerf 시작 시간도 처리량에서 제외합니다.
- 반복별 mode 순서는 A→D, D→A, A→D입니다. 두 mode의 요청 payload 해시와 실제 입력, 출력 길이별 요청 수가 동일한지 검사했습니다.
- 출력 길이가 요청값과 다르거나 요청 오류가 있으면 해당 실행을 성공 결과로 저장하지 않습니다.

## 지표와 해석 범위

처리량, 평균 지연, 평균 TTFT와 ITL은 반복별 AIPerf 지표를 산술 평균했습니다. 표준편차는 반복 간 sample SD입니다. p95 지연과 p95 TTFT는 같은 조건의 모든 반복 요청을 합쳐 nearest-rank로 계산했습니다. 조건별 mode당 표본은 96개이며 긴 꼬리 지연의 정밀 추정에는 더 많은 표본이 필요합니다.

TTFT는 첫 텍스트 chunk 도착까지의 시간이며 대기열, tokenization과 HTTP 전달을 포함합니다. TextStreamer의 단어 버퍼 때문에 첫 GPU 토큰 생성 시간과 다를 수 있습니다. ITL은 AIPerf의 streaming 지표입니다.

분리 경로는 GPU KV cache를 CPU로 복사한 뒤 Prefill→Router→Decode의 HTTP 경로로 보냅니다. Decode는 프롬프트를 다시 계산하지 않습니다. 첫 토큰 선택도 Decode worker에서 수행하므로 TTFT에는 Decode 대기열이 포함됩니다. Aggregation의 4개 worker는 각각 decode를 수행하고 분리 구성에는 decode worker가 3개입니다. 긴 출력의 처리량, 전송 비용과 높은 동시성의 대기 시간을 이 조건에 맞춰 해석해야 합니다.

RDMA, NVLink 또는 CUDA IPC를 사용한 전송, continuous batching, 대형 모델과 다중 물리 GPU의 성능으로 일반화하지 않습니다.

## 원본과 재현

[집계 CSV](summary.csv), [조건별 A/D 비교](comparison.csv), [집계 설정과 검증 JSON](summary.json), [worker 단계별 진단](phase-diagnostics.json)에 수치가 있습니다. 단계별 진단은 워밍업을 포함한 worker 로그의 평균이며 AIPerf 측정 통계와 분리합니다.

요청별 AIPerf exports, payload, GPU 표본과 Pod 로그는 저장소의 `reports/pd/benchmark-four-20261001`에 보관합니다. 원본 경로는 Git에서 제외됩니다.

```sh
python3 scripts/benchmark-pd.py --mps-replicas 4 --cluster local-k8s-gpu --config docs/reports/gpu/pd/benchmark-four-20261001/workload.json
python3 scripts/report-pd.py docs/reports/gpu/pd/benchmark-four-20261001
```

준비와 설정은 [PD 비교 가이드](../../../../guides/prefill-decode-4.md)를 참고합니다.

실행 환경과 기존 환경 복구 검사는 [환경 검증 결과](environment-validation.json)에 기록합니다.

처리량과 지연 차이의 원인은 [성능 원인 분석](analysis.md)을 참고합니다.

배포 검증 범위와 기존 환경 보존 확인은 [구성 검증](validation.md)을 참고합니다.

요청별 TTFT와 TPOT 임계값에 따른 결과는 [Goodput 비교](goodput/summary.md)를 참고합니다.
