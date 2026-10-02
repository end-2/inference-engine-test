# MPS GPU 공유 클러스터

`GPU_SHARING=mps`는 GPU 0을 공유 리소스 2개로 등록하는 별도 kind 클러스터를 만듭니다. 한 worker에서 두 Pod가 `nvidia.com/gpu.shared: 1`씩 요청할 수 있습니다. CPU 클러스터와 GPU 독점 모드의 기본 동작은 유지됩니다.

`MPS_REPLICAS=4`는 기존 설정을 보존하면서 `local-k8s-gpu-mps4`와 [별도 4분할 설정](../../config/cluster/mps-4.yaml)을 선택합니다. Aggregation 4개와 Prefill 1개, Decode 3개를 비교하는 실행 절차는 [4분할 PD 가이드](prefill-decode-4.md)에 있습니다. 생략 시 `MPS_REPLICAS=2`이며 기존 클러스터의 분할 수를 다른 값으로 변경하는 명령은 거부합니다.

## 준비와 생성

[GPU 환경의 도구와 런타임](benchmark.md#gpu-벤치마크)을 먼저 준비합니다. MPS 클러스터와 기존 GPU 클러스터는 같은 물리 GPU 0을 사용하므로 GPU 워크로드를 동시에 실행하지 않습니다. MPS를 새로 시작할 때 GPU에 CUDA 프로세스가 있으면 `up`이 해당 PID를 출력하고 중단합니다. 기존 추론 Deployment를 0 replicas로 변경하거나 해당 GPU 작업을 종료한 뒤 실행합니다.

```sh
make install DEVICE=gpu
make download-model
make up DEVICE=gpu GPU_SHARING=mps
make status DEVICE=gpu GPU_SHARING=mps
```

| 설정 | GPU 독점 모드 | MPS 모드 |
| --- | --- | --- |
| `GPU_SHARING` | `none` (기본값) | `mps` |
| 기본 클러스터 이름 | `local-k8s-gpu` | `local-k8s-gpu-mps` |
| worker 리소스 | `nvidia.com/gpu: 1` | `nvidia.com/gpu.shared: 2` |

MPS 모드의 kubeconfig는 `.local-k8s/<클러스터 이름>/kubeconfig`에 저장합니다. `CLUSTER_NAME`으로 이름을 바꿀 수 있지만, 이미 존재하는 클러스터의 공유 모드와 분할 수는 변경하지 않습니다. 생성, 이미지 로드, 조회와 삭제에 같은 `GPU_SHARING`, `MPS_REPLICAS`와 `CLUSTER_NAME`을 사용합니다.

[MPS 설정](../../config/cluster/mps.yaml)은 각 CUDA 클라이언트의 메모리 한도와 연산 스레드 한도를 절반으로 설정합니다. 8 GiB GPU에서는 메모리 한도가 4 GiB입니다. Pod마다 CUDA 프로세스 1개를 사용하는 구성이 기준이며, 여러 프로세스의 메모리를 합산한 Pod 한도나 처리량 50% 보장을 의미하지 않습니다. 설정 동작은 [NVIDIA device plugin 문서](https://github.com/NVIDIA/k8s-device-plugin#with-cuda-mps)를 참고합니다.

## 두 Pod 추론 예제

SmolLM2 모델과 기존 GPU 이미지를 사용하는 [Deployment와 Service](../../k8s/gpu-mps/transformers-base.yaml)를 배포합니다. Deployment는 2 replicas이며 각 Pod가 공유 GPU 리소스 1개를 요청합니다. 기본 GPU Deployment의 CPU 요청량도 조정해 두 Pod가 함께 배치되도록 구성했습니다.

```sh
make build-image load-image DEVICE=gpu GPU_SHARING=mps VARIANT=transformers-base
GPU_SHARING=mps ./scripts/local-k8s-gpu.sh kubectl apply -f k8s/gpu-mps/transformers-base.yaml
GPU_SHARING=mps ./scripts/local-k8s-gpu.sh kubectl rollout status deployment/transformers-mps --timeout=300s
GPU_SHARING=mps ./scripts/local-k8s-gpu.sh kubectl get pods -l app=transformers-mps -o wide
GPU_SHARING=mps ./scripts/local-k8s-gpu.sh kubectl port-forward service/transformers-mps 8000:8000
```

API 요청 형식은 [추론 엔진 가이드](inference-engine.md)를 따릅니다. 다른 모델을 배포할 때도 `runtimeClassName: nvidia`와 `nvidia.com/gpu.shared: 1`을 사용합니다. 네 로컬 모델의 동시 실행 결과와 검증 조건은 [MPS 모델 보고서](../reports/gpu/mps-check-20260930/summary.md)에 있습니다.

`make benchmark`와 `make benchmark-suite`는 GPU 독점 측정용이므로 MPS 모드를 받지 않습니다. MPS 추론 서버는 위의 배포 절차로 실행합니다.
Prefill과 Decode 분리 여부를 비교하는 소스, 전용 배포와 AIPerf 실행은 [PD 비교 가이드](prefill-decode.md)를 참고합니다.

## 검증과 종료

새 클러스터의 `up`은 선택한 분할 수만큼 Pod를 실행하는 CUDA smoke test를 자동 수행합니다. GPU 메모리 쓰기와 읽기 결과, 동일 MPS 서버에 연결된 클라이언트 수를 확인하고 테스트 리소스를 제거합니다. 재실행 시 선택한 공유 리소스가 모두 비어 있어야 합니다.

```sh
GPU_SHARING=mps ./scripts/local-k8s-gpu.sh kubectl scale deployment/transformers-mps --replicas=0
make test DEVICE=gpu GPU_SHARING=mps
GPU_SHARING=mps ./scripts/local-k8s-gpu.sh kubectl scale deployment/transformers-mps --replicas=2
```

`down`은 worker의 일반 Pod를 종료한 뒤 MPS 데몬을 종료하고 해당 클러스터를 삭제합니다. 노드 내부 데이터는 삭제되고 호스트 모델은 유지됩니다. 기존 GPU 클러스터의 중지했던 추론 Deployment는 필요할 때 다시 시작합니다.

```sh
make down DEVICE=gpu GPU_SHARING=mps
```

GPU 없이 실행하는 구성과 수명주기 테스트:

```sh
python3 -m unittest discover -s tests -p 'test_gpu_*.py' -v
sh tests/test-local-k8s.sh
```
