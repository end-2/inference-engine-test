# MPS 4분할 Prefill/Decode 비교

SmolLM2-135M FP16에서 Aggregation worker 4개와 Prefill 1개, Decode 3개를 비교합니다. [2분할 구성](prefill-decode.md)을 기반으로 한 별도 overlay이며, 기존 설정 파일과 기본 실행 명령을 유지합니다.

[실제 GPU 구성 검증](../reports/gpu/pd/four-slot-check-20261001/validation.md)에서 네 CUDA client와 두 mode의 요청 분산을 확인했습니다.

[전체 workload 비교 결과](../reports/gpu/pd/benchmark-four-20261001/summary.md)에 3회 반복의 처리량, TTFT, 지연과 router 메모리 검증을 기록했습니다.

vLLM V1과 유사한 RUNNING 우선 정책과 chunked prefill은 [별도 token budget 스케줄러](prefill-decode-scheduler.md)로 검증할 수 있습니다.

| 항목 | 기존 2분할 | 추가 4분할 |
| --- | --- | --- |
| 선택 | `MPS_REPLICAS=2` 또는 생략 | `MPS_REPLICAS=4` |
| 기본 클러스터 | `local-k8s-gpu-mps` | `local-k8s-gpu-mps4` |
| Namespace | `pd-comparison` | `pd-comparison-4` |
| MPS 설정 | `config/cluster/mps.yaml` | `config/cluster/mps-4.yaml` |
| Aggregation | worker 2개 | worker 4개 |
| Disaggregation | Prefill 1개, Decode 1개 | Prefill 1개, Decode 3개 |
| 8 GiB GPU의 client별 메모리 한도 | 4 GiB | 2 GiB |
| client별 active thread 한도 | 50% | 25% |

각 worker는 공유 GPU 슬롯 1개, CPU 요청 1과 상한 2, 호스트 메모리 2 GiB를 사용합니다. 4분할의 두 mode 모두 worker 합계 CPU 요청 4, 상한 8과 메모리 8 GiB입니다. MPS 한도는 CUDA client별 한도이며 처리량 비율을 보장하지 않습니다.

Router는 Aggregation 4개 또는 Decode 3개의 StatefulSet Pod 주소로 round-robin 분산합니다. `--decode-urls`는 여러 Decode 주소를 지정하며 기존 `--decode-url`보다 우선합니다. Readiness는 선택한 mode의 모든 backend를 확인합니다. 장애가 난 backend로 보냈던 요청을 자동 재시도하지 않습니다.

## 클러스터와 이미지 준비

먼저 [MPS 준비 사항](gpu-mps.md#준비와-생성)을 충족하고 GPU 0의 기존 작업을 중지합니다. 두 클러스터는 같은 물리 GPU를 사용하므로 MPS 데몬을 동시에 운영하지 않습니다. 클러스터와 namespace 분리는 GPU 자원의 물리적 분리를 의미하지 않습니다.

실행 중인 2분할 PD 클러스터를 보존하며 정지하려면 벤치마크 Job이 끝난 뒤 다음을 실행합니다. 기존 PVC와 클러스터는 유지됩니다.

```sh
GPU_SHARING=mps MPS_REPLICAS=2 ./scripts/local-k8s-gpu.sh kubectl \
  -n pd-comparison scale deployment,statefulset --all --replicas=0
GPU_SHARING=mps MPS_REPLICAS=2 ./scripts/local-k8s-gpu.sh kubectl \
  -n pd-comparison wait --for=delete pod -l app.kubernetes.io/part-of=pd-comparison --timeout=180s
GPU_SHARING=mps MPS_REPLICAS=2 ./scripts/local-k8s-gpu.sh kubectl \
  label node -l nvidia.com/gpu.present=true nvidia.com/mps.capable-
```

NVIDIA namespace의 MPS control daemon Pod가 종료되고 `nvidia-smi`에서 CUDA 작업이 없는지 확인한 후 4분할을 시작합니다. 다른 GPU 서비스를 사용 중이라면 해당 서비스도 먼저 중지합니다.

```sh
make up DEVICE=gpu GPU_SHARING=mps MPS_REPLICAS=4
make build-image load-image DEVICE=gpu GPU_SHARING=mps MPS_REPLICAS=4 VARIANT=transformers-pd
make build-benchmark-image load-benchmark-image DEVICE=gpu GPU_SHARING=mps MPS_REPLICAS=4
make pd-deploy MPS_REPLICAS=4 PD_MODE=disaggregated
```

커스텀 클러스터 이름은 모든 명령에 동일한 `CLUSTER_NAME`으로 지정합니다. 기존 2분할 클러스터 이름에 `MPS_REPLICAS=4`를 지정하면 변경을 거부합니다. `up`과 `test`는 CUDA client 4개가 같은 MPS 서버에 연결되는지 검사합니다.

```sh
k4() { GPU_SHARING=mps MPS_REPLICAS=4 ./scripts/local-k8s-gpu.sh kubectl -n pd-comparison-4 "$@"; }
k4 get pods -o wide
k4 port-forward service/pd-router 8000:8000
```

Aggregation으로 전환하려면 다음을 실행합니다. 실행 중인 벤치마크 Job이 있으면 전환을 거부하며, 종료된 worker Pod가 GPU 슬롯을 반환한 뒤 새 mode를 배포합니다.

```sh
make pd-deploy MPS_REPLICAS=4 PD_MODE=aggregated
```

## Workload 비교

두 mode에 동일한 [기본 workload](../../config/benchmarks/pd.json)를 적용합니다. 입력과 출력 길이, 혼합 분포, 동시성, 요청 수와 반복 횟수는 2분할과 같습니다.

```sh
make pd-benchmark MPS_REPLICAS=4
# 같은 작업의 직접 실행
python3 scripts/benchmark-pd.py --mps-replicas 4 --config config/benchmarks/pd.json
```

결과는 `docs/reports/gpu/pd/pd4-<시각>/`와 `reports/pd/pd4-<시각>/`에 저장합니다. JSON에는 MPS 슬롯 수, worker별 역할 수, namespace와 실행 설정이 기록됩니다. 보고서 생성 시 4개 share, 25% 한도와 Decode 3개를 표시합니다.

```sh
python3 scripts/report-pd.py docs/reports/gpu/pd/pd4-<시각>
```

Router의 동시 전송 슬롯 2개, 요청 수용 한도 8개와 메모리 상한 1 GiB는 공통으로 적용합니다. 스트리밍에서는 Decode 응답 헤더가 도착하면 전송 슬롯을 반환하므로 Decode worker 3개가 동시에 생성할 수 있습니다. 비스트리밍에서는 응답 완료까지 슬롯을 잡을 수 있으므로 이 비교에는 기본 streaming workload를 사용합니다. 지표와 메모리 설정은 [공통 가이드](prefill-decode.md#router-메모리-한도)를 참고합니다.

4분할은 같은 물리 GPU에서 Decode worker의 수와 자원 배분을 바꾼 실험입니다. 2분할보다 빠르다는 가정 없이 동일 workload의 처리량, TTFT와 지연을 비교합니다.

## 종료와 기존 구성 재개

결과를 복사한 뒤 4분할 클러스터만 종료합니다. 해당 클러스터의 결과 PVC도 삭제됩니다.

```sh
make down DEVICE=gpu GPU_SHARING=mps MPS_REPLICAS=4
make up DEVICE=gpu GPU_SHARING=mps MPS_REPLICAS=2
make pd-deploy MPS_REPLICAS=2 PD_MODE=aggregated
```

4분할 manifest는 [Aggregation profile](../../k8s/inference-distributed/profiles/mps-4-aggregated.yaml), [Disaggregation profile](../../k8s/inference-distributed/profiles/mps-4-disaggregated.yaml)에 있습니다. 검증은 공통 가이드의 PD 테스트와 `tests/test_gpu_cluster.py`로 실행합니다.
