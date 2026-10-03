# Token budget 스케줄러 검증

기존 PD worker에 `--scheduler token-budget`을 추가하면 여러 요청의 decode와 chunked prefill을 한 번의 모델 forward로 처리합니다. 기본값은 기존 `serial`입니다. MPS 2분할과 4분할의 기존 manifest, 이미지 태그와 namespace는 유지합니다.

[실제 GPU 검증 결과](../reports/gpu/pd/scheduler-20261002/analysis.md)에 1,920개 요청의 비교와 TPOT SLO를 적용한 TTFT 차이를 기록했습니다.

## 스케줄링 규칙

[vLLM V1 v0.30.0의 schedule](https://github.com/vllm-project/vllm/blob/ced6857afa0ea7b2e3f0846a62e1394e90f15607/vllm/v1/core/sched/scheduler.py#L561-L865)을 참고했습니다. 구현은 [scheduler.py](../../src/huggingface/llama/inference_distributed/scheduler.py)와 [packed.py](../../src/huggingface/llama/inference_distributed/packed.py)에 있습니다.

1. 매 step에서 RUNNING 요청을 들어온 순서대로 선택합니다. 진행 중인 decode는 보통 1토큰을, 부분 prefill은 남은 prompt의 일부를 사용합니다.
2. 남은 token budget, 실행 요청 수와 KV 예약량이 허용하면 WAITING의 요청을 FIFO로 받습니다.
3. 선택한 모든 요청의 토큰을 하나의 forward로 계산합니다. 요청별 position과 causal attention mask로 KV를 분리합니다.
4. 완료되거나 취소된 요청의 실행 자리와 KV 예약량을 반환하고 다음 step에서 새 요청을 받습니다.

진행 중인 부분 prefill도 RUNNING이므로 모든 decode가 모든 prefill보다 우선하는 규칙은 아닙니다. P1D3에서는 P가 prompt 전체의 KV를 전송하고 D는 마지막 prompt 토큰 1개를 다시 계산하여 첫 출력을 생성합니다. TTFT에는 KV 전송과 D의 입장 대기가 포함됩니다.

## 실행

[MPS 4분할 가이드](prefill-decode-4.md)의 클러스터와 모델을 준비합니다. 새 구성도 GPU share 4개를 모두 사용하므로 같은 물리 GPU에서 기존 PD worker와 동시에 실행할 수 없습니다.

```sh
DEVICE=gpu IMAGE_TAG=token-budget-v1 ./scripts/build-inference-images.sh transformers-pd
DEVICE=gpu IMAGE_TAG=token-budget-v1 GPU_SHARING=mps MPS_REPLICAS=4 \
  ./scripts/load-inference-images.sh transformers-pd

PD_SCHEDULER=token-budget PD_TOKEN_BUDGET=256 MPS_REPLICAS=4 \
  ./scripts/deploy-pd.sh aggregated
# 같은 namespace에서 A4를 P1D3로 전환합니다.
PD_SCHEDULER=token-budget PD_TOKEN_BUDGET=256 MPS_REPLICAS=4 \
  ./scripts/deploy-pd.sh disaggregated

python3 scripts/benchmark-pd.py --mps-replicas 4 --scheduler token-budget \
  --token-budget 32 --config benchmarks/pd-scheduled.json
python3 scripts/benchmark-pd.py --mps-replicas 4 --scheduler token-budget \
  --token-budget 256 --config benchmarks/pd-scheduled.json
python3 scripts/report-pd.py <report-directory>
python3 scripts/report-pd-goodput.py <report-directory> --tpot-ms 25,30,35,40,50,75
```

Manifest는 `k8s/inference-distributed/profiles/mps-4-scheduled-*.yaml`, namespace는 `pd-comparison-4-scheduled`입니다. 별도 클러스터를 지정하려면 배포에 `CLUSTER_NAME`, benchmark에 `--cluster`를 사용합니다. Benchmark는 배포를 전환하고 동일 payload 및 입출력 길이를 검증합니다. 테스트 종료 후 worker를 자동 삭제하지 않습니다.

| Worker 옵션 | 기본값 | 동작 |
| --- | ---: | --- |
| `--max-num-batched-tokens` | 256 | 한 forward에 넣는 전체 query 토큰 상한 |
| `--max-num-seqs` | 8 | worker당 RUNNING 요청 상한 |
| `--max-kv-tokens` | 8192 | RUNNING 요청의 최대 KV 길이 합계 예약 상한 |
| `--long-prefill-token-threshold` | 0 | 요청당 chunk 상한, 0이면 전체 budget만 적용 |
| `--scheduler-trace` | 꺼짐 | step별 prefill/decode 토큰, 요청 수와 시간을 로그에 기록 |

추가 manifest는 trace를 켜고 HTTP admission을 32로 설정합니다. Router의 전송 동시성 2, 상태 크기 상한 64 MiB와 메모리 상한 1 GiB는 유지합니다. A4, P1D3의 모든 worker에 같은 token budget을 적용합니다. P와 D의 개별 튜닝 결과는 아닙니다.

## 해석 범위와 검증

이 구현은 스케줄링 순서와 토큰 예산의 영향을 살펴보는 Transformers runtime입니다. vLLM의 PagedAttention, CUDA graph, 비동기 스케줄링, prefix caching과 KV preemption은 구현하지 않습니다. 밀집 attention mask와 step별 KV 결합 및 분리 비용이 있으므로 측정된 처리량을 vLLM의 성능으로 해석하지 않습니다. KV는 요청의 prompt와 최대 출력 길이를 미리 예약하며, 예약 한도가 차면 새 요청이 대기합니다.

TTFT는 첫 텍스트 chunk까지의 시간입니다. TextStreamer의 단어 버퍼 때문에 첫 GPU 토큰 생성 시각과 다릅니다. 요청별 TPOT는 `(전체 지연 - TTFT) / (출력 토큰 수 - 1)`이며 토큰별 ITL 분포를 대체하지 않습니다.

```sh
python3 -m unittest discover -s tests -p 'test_pd*py'
```

테스트는 서로 다른 길이의 요청 간 attention 격리, 개별 실행과의 logits 및 KV 일치, 연속 배치의 생성 결과, 마지막 prompt 토큰만 재계산하는 KV 전달, 취소, admission과 잘못된 상태 복구를 확인합니다. Step 로그의 `pd_scheduler` JSON으로 token budget 준수와 mixed prefill/decode forward를 확인할 수 있습니다.
