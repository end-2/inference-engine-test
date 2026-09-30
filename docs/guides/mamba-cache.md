# Mamba 상태 캐시

`state-spaces/mamba-130m-hf`로 요청 간 prefix 상태 재사용을 측정합니다. 모델 revision과 파일 체크섬은 [모델 설정](../../config/models/mamba-130m-transformers.env)과 [SHA-256 목록](../../config/models/mamba-130m-transformers.sha256)에 고정되어 있습니다. SmolLM2용 KV 엔진과 별도 구현입니다.

| 구성 | Python 진입점 | VARIANT |
| --- | --- | --- |
| 요청마다 prompt 계산 | `transformer.mamba.server` | `transformers-mamba-base` |
| prefix 상태 재사용 | `transformer.mamba.cache.server` | `transformers-mamba-cache` |

두 구성 모두 생성 중에는 Mamba의 recurrent cache를 사용합니다. 비교 대상은 요청 간 prefix 상태 재사용 여부입니다. 서버는 요청을 직렬 처리하며 동시성 증가는 대기열에 반영됩니다. Mamba 배칭과 CUDA Graph는 지원하지 않습니다.

## GPU 실행

[GPU 환경](benchmark.md#gpu-벤치마크)을 준비한 뒤 저장소 루트에서 실행합니다.

```sh
make download-model DEVICE=gpu VARIANT=transformers-mamba-cache
make benchmark DEVICE=gpu VARIANT=transformers-mamba-base
make benchmark DEVICE=gpu VARIANT=transformers-mamba-cache
```

각 명령은 이미지 빌드, 로드, 배포와 AIPerf 측정을 포함합니다. Mamba의 기본 엔진과 캐시 엔진은 `Deployment/transformers-mamba-base`를 공유합니다. GPU 벤치마크 실행기는 다른 추론 엔진을 중지해 GPU를 확보합니다. 결과는 `docs/reports/gpu/mamba/`에 저장됩니다.

검증 환경처럼 이미지가 이미 GPU worker와 control-plane에 로드되어 있으면 다음 명령으로 빌드를 생략할 수 있습니다. 기본 엔진은 `--image`, `--manifests`, `--cache-policy`를 생략합니다.

```sh
python scripts/run-benchmark.py --backend mamba --device gpu \
  --build-context '' --benchmark-build-context '' --concurrencies 1 \
  --image local/transformers-mamba-cache-gpu:0.1.0 \
  --manifests k8s/gpu/transformers-mamba-cache --cache-policy clear-before-sweep
```

전체 반복은 기본 엔진, 동시성마다 캐시 초기화, sweep 시작 시에만 초기화하는 세 조건으로 구성됩니다. 각 조건은 동시성 `1,2,4,8`에서 warmup 2개와 측정 요청 100개를 사용합니다.

```sh
make benchmark-suite DEVICE=gpu VARIANT=transformers-mamba-base REPETITIONS=3
```

서버만 배포하려면 다음 명령을 사용합니다. 단일 GPU 환경에서는 실행 중인 다른 추론 Deployment를 먼저 0 replicas로 변경합니다.

```sh
make build-image load-image DEVICE=gpu VARIANT=transformers-mamba-cache
./scripts/local-k8s-gpu.sh kubectl apply -f k8s/gpu/transformers-mamba-cache
./scripts/local-k8s-gpu.sh kubectl rollout status deployment/transformers-mamba-base --timeout=300s
./scripts/local-k8s-gpu.sh kubectl port-forward service/transformers-mamba-base 8000:8000
```

CPU는 `DEVICE=cpu`와 `k8s/transformers-mamba-cache`를 사용합니다. 로컬 실행 의존성은 [Transformers requirements](../../src/transformer/requirements.txt)를 따릅니다.

```sh
PYTHONPATH=src python -m transformer.mamba.cache.server \
  --model .models/mamba-130m --device cuda --dtype float16 \
  --cache-dir /tmp/mamba-cache
```

## 캐시 규칙

- 각 레이어의 convolution 상태와 SSM 상태를 safetensors로 직렬화합니다. RAM LRU와 disk spill은 기존 저장소를 재사용하며 별도 namespace와 PVC를 사용합니다.
- prompt의 마지막 토큰 직전 상태를 저장합니다. 동일 prompt의 cache hit에서도 마지막 토큰은 다시 계산해 다음 토큰 logits를 얻습니다.
- 저장한 prefix 전체가 입력의 시작 부분과 일치할 때만 복원합니다. 더 긴 상태를 자르거나 중간에서 갈라진 prefix의 상태를 재사용하지 않습니다.
- 복원 뒤 남은 prefix 토큰은 하나씩 처리합니다. 긴 suffix가 남으면 전체 prompt를 한 번에 처리하는 기본 엔진보다 느릴 수 있습니다.
- 생성 시작 전에 상태를 저장하므로 생성 토큰과 취소된 생성의 상태가 checkpoint에 섞이지 않습니다. 복원할 때 요청 전용 버퍼로 복사합니다.
- 모델 파일, 라이브러리 버전, 커널 경로, dtype, device, context 제한과 스레드 수가 namespace에 반영됩니다. 손상된 checkpoint는 버리고 prompt를 다시 계산합니다.

캐시 옵션은 `--cache-dir`, `--cache-ram-mib`, `--cache-disk-mib`, `--cache-min-prefix`입니다. 최소 길이는 마지막 토큰을 제외한 저장 prefix 길이에 적용합니다. RAM과 disk 예산을 모두 0으로 설정하면 요청 간 재사용을 끕니다. 캐시 상태 텐서 크기는 입력 길이와 무관하지만 저장한 토큰 ID와 checkpoint 수에 따른 비용은 별도로 발생합니다.

## 모델과 커널

이 체크포인트는 instruction 모델이 아니며 chat template이 없습니다. 단일 user 메시지는 원문으로 전달하고, 여러 메시지는 `System:`, `User:`, `Assistant:` 형식으로 연결합니다. 토크나이저에 chat template이 있으면 해당 template을 사용합니다. API 모델 이름은 `state-spaces/mamba-130m-hf`입니다.

제공 이미지의 Mamba 실행 경로는 PyTorch입니다. `mamba-ssm`과 `causal-conv1d` 가속 커널은 설치하지 않습니다. CUDA 장치에서도 이 경로로 동작하며 시작 로그에 `kernel_backend`가 기록됩니다. 전용 커널 성능은 별도로 호환성을 확인하고 측정해야 합니다.

## 테스트

Transformers 의존성과 HTTP 테스트용 `httpx`, metric 테스트용 [requirements](../../src/transformer/base_metric/requirements.txt)가 필요합니다.

```sh
python -m unittest discover -s tests -p 'test_transformers_*.py' -v
python -m unittest discover -s tests -p 'test_enhanced_cache_llamacpp.py' -v
python -m unittest discover -s tests -p 'test_gpu_benchmark.py' -v
sh tests/test-download-transformers-model.sh
```

작은 무작위 모델로 prefix 일치와 분기, 손상 복구, 재시작, streaming, sampling, 취소와 요청 간 격리를 검사합니다. CUDA가 있으면 FP32와 FP16도 검사합니다.

실제 모델의 기본, cold, warm, disk 복원 출력을 대조하고 직렬 지연을 측정하려면 다음 명령을 사용합니다.

```sh
python scripts/check-mamba-cache.py --model .models/mamba-130m \
  --device cuda --dtype float16 --prompt-lengths 64,256 \
  --max-tokens 16 --repetitions 3 --report reports/mamba/summary.json
```

이 검사는 HTTP와 대기열을 제외합니다. `first_text_ms`는 TextStreamer의 첫 비어 있지 않은 문자열 콜백까지의 시간이며 첫 생성 토큰의 시간과 다를 수 있습니다. `cold`는 snapshot 저장 비용을 포함하고 `warm`은 동일 prompt 재사용을 측정합니다. 재시작은 입력 길이마다 1회 측정합니다.

실제 기본 서버와 캐시 서버를 각각 실행한 상태에서는 HTTP, SSE와 동시 요청의 결과를 비교할 수 있습니다.

```sh
TEST_MAMBA_BASE_URL=http://127.0.0.1:18081 \
TEST_MAMBA_CACHE_URL=http://127.0.0.1:18082 \
python -m unittest discover -s tests -p 'test_transformers_mamba_api.py' -v
```
