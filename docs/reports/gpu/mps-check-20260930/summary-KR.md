# kind MPS 2분할 모델 실행 검증

2026-09-30 UTC, RTX 2060 SUPER 8 GiB에서 MPS 공유 리소스 2개를 구성하고 `.models/`의 네 모델을 두 Pod에서 동시에 실행했습니다. 동일 모델 4개 조합과 서로 다른 모델 2개 조합에서 생성 요청 48건이 모두 성공했습니다.

## 환경과 설정

- 클러스터: `kind-local-k8s-gpu`, 노드: `local-k8s-gpu-worker`.
- NVIDIA 드라이버: `580.126.09`, device plugin Helm chart: `0.20.1`.
- PyTorch: `2.10.0+cu128`, Transformers: `4.57.6`.
- 각 Pod는 CUDA 프로세스 1개로 실행하고 `nvidia.com/gpu.shared: 1`을 요청했습니다.
- worker에 `nvidia.com/mps.capable=true`를 설정하고 다음 구성을 Helm의 `config.map.mps`와 `config.default=mps`로 적용했습니다.

```yaml
version: v1
sharing:
  mps:
    renameByDefault: true
    resources:
      - name: nvidia.com/gpu
        replicas: 2
```

노드의 `nvidia.com/gpu.shared` 할당량은 2였습니다. MPS 제어 명령으로 메모리 한도 `4G`와 active thread percentage `50.0`을 확인했습니다. 각 조합에서 같은 MPS 서버에 연결된 클라이언트 PID 2개를 확인했으며, 두 프로세스의 추론 실행 구간이 겹쳤습니다. Transformers 클라이언트에는 SM 16개가 표시됐습니다.

## 결과

| Pod A 모델 | Pod B 모델 | 실행 방식 | 성공 요청 | GPU 전체 메모리 관측 최대 (MiB) |
| --- | --- | --- | ---: | ---: |
| SmolLM2-135M | SmolLM2-135M | FP16 | 8/8 | 836 |
| Mamba-130M | Mamba-130M | FP16 | 8/8 | 1512 |
| Jamba-tiny-dev | Jamba-tiny-dev | FP16 | 8/8 | 1700 |
| Qwen2.5-0.5B | Qwen2.5-0.5B | GGUF Q4_K_M | 8/8 | 1572 |
| SmolLM2-135M | Qwen2.5-0.5B | FP16, GGUF Q4_K_M | 8/8 | 1204 |
| Mamba-130M | Jamba-tiny-dev | FP16 | 8/8 | 1606 |

메모리는 추론 중 `nvidia-smi`를 약 1초와 상태 조회 소요 시간 간격으로 읽은 GPU 전체 사용량이며, 두 Pod와 MPS 서버를 포함합니다. 샘플 사이의 순간 최대값이나 개별 Pod 사용량은 아닙니다.

각 Pod는 배치 크기 1로 입력 128토큰과 512토큰을 사용해 64토큰씩 생성했습니다. 입력 길이마다 2회 실행했으며, 별도의 32토큰 입력과 8토큰 생성 warmup은 요청 수에서 제외했습니다. 각 조합의 모델 로딩과 warmup이 끝난 뒤 같은 시작 시각을 전달했습니다.

Mamba와 Jamba는 전용 Mamba CUDA 확장 없이 PyTorch CUDA 경로로 실행했습니다. Jamba의 `use_mamba_kernels`는 `False`입니다. Qwen은 `n_ctx=1024`, `n_batch=512`, `n_gpu_layers=-1`을 사용했고, 두 Pod 모두 25/25 레이어 GPU offload를 로그에서 확인했습니다.

## 적용 범위와 기록

이 결과는 로컬 가중치를 사용한 모델 로딩과 CUDA 토큰 생성 검증입니다. HTTP 서버, 큰 배치, 긴 문맥, 요청 간 캐시, 장시간 부하와 생성 품질은 측정하지 않았습니다. MPS 한도는 CUDA 클라이언트 기준이며, 여러 CUDA 프로세스를 실행하는 Pod 전체에 대한 4 GiB 한도로 해석하지 않습니다.

이미지 식별자, 클라이언트 메모리와 조합별 결과는 [summary.json](summary.json)에 있습니다. 실행 스크립트, Pod 명세, 생성 결과와 MPS 로그는 저장소 루트의 `.local-k8s/mps-check-20260930/`에 보관했습니다.

검증 후 테스트 namespace와 MPS Pod를 제거하고 Helm 설정, 모든 기존 Deployment 명세와 GPU의 `Default` compute mode를 복원했습니다. `nvidia.com/gpu` 할당량은 다시 1이며, 기존 llama.cpp 서버의 readiness와 HTTP 상태 응답이 정상입니다.
