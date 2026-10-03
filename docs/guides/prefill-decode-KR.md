# Prefill과 Decode 배치 방식 비교

SmolLM2를 MPS 슬롯 2개에서 실행하며 aggregation과 disaggregation을 비교합니다. 두 모드는 [같은 엔진](../../src/transformer/pd/engine.py), 모델, FP16, greedy decoding, Pod별 batch 1을 사용합니다. Prefix cache와 continuous batching은 사용하지 않습니다.

[실험 종합](../reports/gpu/pd/README.md)에 2분할, 4분할과 스케줄러 결과가 있습니다. [2분할 실측 보고서](../reports/gpu/pd/benchmark-20260930/summary.md)는 중단된 실행 중 완료한 1회의 workload 비교입니다.

기존 2분할과 별도로 Aggregation 4개, Prefill 1개와 Decode 3개를 실행하려면 [4분할 PD 가이드](prefill-decode-4.md)를 따릅니다. 아래 명령의 기본값은 기존 `MPS_REPLICAS=2`입니다.

| 구성 | Aggregation | Disaggregation |
| --- | --- | --- |
| GPU Pod | 전체 추론 2 replicas | Prefill 1개, Decode 1개 |
| Pod별 GPU | `nvidia.com/gpu.shared: 1` | `nvidia.com/gpu.shared: 1` |
| GPU Pod 자원 합계 | CPU 요청 2, 상한 4, 메모리 4 GiB | 동일 |
| 요청 경로 | Router → 전체 추론 Pod 중 하나 | Router → Prefill → Router → Decode |
| 상태 전달 | Pod 내부 KV cache | safetensors를 HTTP로 전달 |

두 모드 모두 같은 CPU router 1개를 사용합니다. Aggregation은 StatefulSet의 Pod별 주소로 요청을 번갈아 전달합니다. Disaggregation은 이전 요청의 Decode와 다음 요청의 Prefill을 겹쳐 실행할 수 있습니다. 각 GPU worker는 한 번에 한 요청을 처리하며, 대기 요청을 포함한 router 수용 한도를 넘으면 HTTP 429를 반환합니다.

### Router 메모리 한도

공통 [설정](../../k8s/pd/values.yaml)의 `MAX_PENDING=8`은 응답 완료까지 수용하는 요청 수이며, `MAX_STATE_TRANSFERS=2`는 동시에 Prefill 상태를 만들고 Decode에 전달하는 요청 수입니다. 전송 슬롯이 없으면 KV를 만들기 전에 기다립니다. 기본 120초 안에 슬롯을 얻지 못하면 HTTP 504를 반환하고, 클라이언트가 끊으면 대기를 취소합니다. 슬롯은 Decode 응답 헤더 수신 시 반환하므로 비스트리밍 요청에서는 생성 완료까지 유지할 수 있습니다.

상태 하나의 한도는 `MAX_STATE_MIB=64`입니다. 기본 설정에서 전송 중인 원본 상태는 합계 128 MiB까지이며, 수신 버퍼를 `bytes`로 변환하는 동안 복사본도 필요합니다. Router는 64 KiB 청크로 업로드하고 성공, 실패와 취소 시 본문 참조를 해제합니다. 이 한도는 프로세스 전체 RSS 상한을 의미하지 않습니다.

[Router 배포](../../k8s/pd/templates/router.yaml)는 두 mode 모두 메모리 요청 512 MiB, 상한 1 GiB를 사용합니다. 상태 크기나 전송 슬롯 수를 늘리면 일시적인 복사본, HTTP 버퍼와 Python 메모리까지 고려해 상한을 다시 검증해야 합니다. 변경한 소스는 추론 이미지를 다시 빌드하고 로드한 뒤 `pd-deploy`로 배포합니다.

## 실행

[MPS 가이드](gpu-mps.md)에 따라 기존 GPU 워크로드를 중지하고 MPS 슬롯 2개를 비웁니다. `transformers-mps` 예제를 배포했다면 먼저 replicas를 0으로 변경합니다. 물리 GPU는 하나이며 두 개의 독립 GPU를 비교하는 실험은 아닙니다.

```sh
make download-model
make up DEVICE=gpu GPU_SHARING=mps
make build-image load-image DEVICE=gpu GPU_SHARING=mps VARIANT=transformers-pd
make pd-deploy PD_MODE=aggregated
```

`pd-deploy`는 `pd-comparison` namespace의 기존 비교용 worker와 router를 종료하고 선택한 구성을 배포합니다. 실행 중인 비교 Job이 있으면 전환을 거부합니다. 결과 PVC는 유지합니다. 커스텀 클러스터에는 모든 명령에 동일한 `CLUSTER_NAME`을 지정합니다.

```sh
k() { GPU_SHARING=mps ./scripts/local-k8s-gpu.sh kubectl -n pd-comparison "$@"; }
k get pods -o wide
k port-forward service/pd-router 8000:8000
```

다른 터미널에서 API를 확인합니다. `stream: true`와 `stream_options: {"include_usage": true}`도 지원합니다.

```sh
curl -sS http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"HuggingFaceTB/SmolLM2-135M-Instruct","messages":[{"role":"user","content":"Explain what a GPU does."}],"max_tokens":32,"temperature":0,"ignore_eos":true}'
```

분리 구성으로 전환합니다. 기존 port-forward는 router 재시작 후 다시 실행합니다.

```sh
make pd-deploy PD_MODE=disaggregated
```

이미지 기본 태그는 manifests에 명시되어 있습니다. `IMAGE_TAG`를 변경하면 각 overlay의 Kustomize `images` 설정도 함께 변경해야 합니다.

## 여러 workload 자동 비교

[workload 설정](../../config/benchmarks/pd.json)은 입력과 출력 길이의 전체 조합, 혼합 부하, 동시성, 요청 수와 반복 횟수를 정의합니다. 기본값은 입력 `64,256,704`, 출력 `16,64,256`의 9개 조합과 혼합 부하이며, 동시성 `1,2,4,8`에서 3회 반복합니다. 채팅 템플릿 토큰이 추가되므로 실제 입력 길이는 응답의 `usage`로 검증합니다.

MPS 클러스터와 추론 이미지를 준비한 뒤 실행합니다. 실행기에는 Python의 PyYAML이 필요하고, 그림 생성에는 matplotlib가 필요합니다.

```sh
make build-benchmark-image load-benchmark-image DEVICE=gpu GPU_SHARING=mps
make pd-benchmark
# 커스텀 클러스터 또는 workload 설정
python3 scripts/benchmark-pd.py --cluster local-k8s-gpu-mps --config config/benchmarks/pd.json
```

[실행기](../../scripts/benchmark-pd.py)는 두 mode의 배포를 순차 전환하고 AIPerf sweep을 실행합니다. 반복마다 A→D와 D→A 순서를 번갈아 사용합니다. 추론 Pod 재시작, 요청 오류, 출력 길이 불일치, 두 mode 간 payload 해시 또는 실제 입력, 출력 분포 불일치가 있으면 중단합니다. 워밍업은 측정 통계에서 제외합니다.

`docs/reports/gpu/pd/pd-<시각>/`에 요약 JSON과 CSV, `reports/pd/pd-<시각>/`에 요청별 AIPerf exports, 배포 설정, GPU 표본과 로그를 저장합니다. 원본은 Git에서 제외됩니다. 완료 후 실행기가 출력한 보고서 디렉터리로 표와 그림을 생성합니다.

```sh
python3 scripts/report-pd.py docs/reports/gpu/pd/pd-<시각>
```

중단된 실행에서 두 mode의 모든 workload를 마친 반복만 보고하려면 `--completed-only`를 추가합니다. 원본 실행의 실패 상태를 유지하며 `completed-summary.json`, `completed-summary.csv`에 선택한 반복만 집계합니다. 보고서에도 원래 반복 계획과 실제 완료 횟수를 표시합니다.

처리량과 평균 지연은 반복별 지표의 산술 평균이며, 표준편차는 반복 간 sample SD입니다. p95는 같은 조건의 모든 반복 요청을 합친 nearest-rank입니다. TTFT와 ITL은 streaming 응답 기준이며 TextStreamer의 단어 버퍼 영향을 포함합니다. 작은 차이나 꼬리 지연을 정밀하게 비교하려면 workload 설정의 요청 수와 반복 횟수를 늘립니다.

보고서 생성, SLO별 goodput 분석과 Git 보존 파일은 [실험 결과 정리 가이드](experiment-results.md)를 참고합니다.

실행기는 기존 클러스터를 사용하며 클러스터 생성이나 외부 GPU 워크로드 중지는 수행하지 않습니다. 완료 후 마지막 mode의 추론 Pod는 유지하고, 생성한 Job과 결과 읽기용 Pod는 정리합니다. 결과 PVC는 유지합니다. 기존 `make benchmark`와 `make benchmark-suite`는 독점 GPU 측정용입니다.

### 단일 분포 수동 측정

[전용 AIPerf Job](../../k8s/aiperf/profiles/pd.yaml)의 `--sequence-distribution`을 원하는 분포로 바꾸고, 비교할 mode를 배포한 후 실행합니다. 예를 들어 `704,16:100`은 긴 입력, 짧은 출력 부하입니다.

```sh
k() { GPU_SHARING=mps ./scripts/local-k8s-gpu.sh kubectl -n pd-comparison "$@"; }
k delete job pd-benchmark --ignore-not-found
GPU_SHARING=mps LOCAL_K8S_SCRIPT=./scripts/local-k8s-gpu.sh ./scripts/k8s.sh apply k8s/aiperf/profiles/pd.yaml --show-only templates/pvc.yaml --show-only templates/job.yaml
k wait --for=condition=complete job/pd-benchmark --timeout=14400s
k logs job/pd-benchmark
GPU_SHARING=mps LOCAL_K8S_SCRIPT=./scripts/local-k8s-gpu.sh ./scripts/k8s.sh apply k8s/aiperf/profiles/pd.yaml --show-only templates/reader.yaml
k wait --for=condition=Ready pod/pd-results --timeout=120s
k cp pd-results:/results reports/pd-manual
```

## 상태 전달과 지표

Prefill은 전체 프롬프트의 KV cache와 마지막 위치의 logits를 전달합니다. Decode는 logits에서 첫 출력 토큰을 선택하고, 이후에는 토큰 하나씩 forward합니다. 두 worker의 모델 파일, tokenizer, dtype과 context 설정 지문이 다르거나 상태의 tensor 형상이 다르면 거부합니다. 전달 형식은 [safetensors bytes API](https://huggingface.co/docs/safetensors/api/torch)를 사용하며, cache position은 [Transformers cache 규칙](https://huggingface.co/docs/transformers/v4.57.1/cache_explanation)을 따릅니다.

JSON 응답의 `metrics`, SSE 종료 chunk의 `metrics`와 worker의 `pd_request` JSON 로그에 다음 값이 포함됩니다. 시간 단위는 ms입니다.

| 지표 | 범위 |
| --- | --- |
| `prefill_queue_ms`, `decode_queue_ms` | 각 worker의 단일 실행 스레드를 기다린 시간 |
| `state_queue_ms` | Router의 상태 전송 슬롯 대기 시간, 분리 구성에서 기록 |
| `prefill_ms` | 입력 tensor 준비와 prefill forward, CUDA 완료 대기 |
| `decode_ms` | 첫 토큰 선택부터 생성 종료까지, 텍스트 변환 포함 |
| `decode_first_token_ms` | decode 루프 시작부터 첫 토큰 선택까지 |
| `export_ms`, `import_ms` | KV와 logits의 CPU 복사 및 직렬화, 역직렬화 및 GPU 복사 |
| `prefill_rpc_ms` | Router에서 Prefill 요청 시작부터 상태 수신 완료까지 |
| `state_receive_ms` | Decode가 HTTP 요청 본문을 읽은 시간 |
| `kv_bytes`, `state_bytes` | 순수 KV tensor 크기, 전달한 전체 상태 크기 |

`prefill_rpc_ms`에는 대기, tokenization, 계산, export와 HTTP 전송이 포함되므로 `prefill_ms` 등과 더하지 않습니다. `state_receive_ms` 역시 전체 전송 경로의 지연을 의미하지 않습니다. 클라이언트 TTFT와 end-to-end latency로 실제 전달 비용을 포함한 차이를 판단합니다. Aggregation의 전달 지표는 0이며 RPC와 수신 지표는 없습니다.

이 구현은 CPU 메모리를 경유하는 HTTP KV 전달을 측정합니다. NVLink, RDMA, CUDA IPC를 사용하는 시스템의 성능과 직접 비교하지 않습니다. 현재 지원 대상은 Llama 구조의 SmolLM2입니다. Mamba와 Jamba의 recurrent state, llama.cpp GGUF 전달은 포함하지 않습니다.

## 구성과 검증

- 공통 토큰과 대기열 한도: [pd/values.yaml](../../k8s/pd/values.yaml)
- GPU 자원, 모델 mount와 역할: [workers](../../k8s/pd/templates/workers.yaml)
- 엔진, 내부 API와 router: [src/transformer/pd](../../src/transformer/pd)

CPU 환경에서도 작은 Llama 모델로 상태 전달과 출력 동등성을 검증할 수 있습니다.

```sh
python -m pip install torch==2.10.0 --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r src/transformer/requirements.txt -r src/transformer/pd/requirements.txt pyyaml
python -m unittest discover -s tests -p 'test_pd*.py' -v
./scripts/render-k8s.sh k8s/pd/profiles/mps-2-aggregated.yaml
./scripts/render-k8s.sh k8s/pd/profiles/mps-2-disaggregated.yaml
```

결과를 호스트로 복사한 뒤 종료합니다. namespace 삭제는 결과 PVC도 삭제합니다.

```sh
k delete namespace pd-comparison
make down DEVICE=gpu GPU_SHARING=mps
```
