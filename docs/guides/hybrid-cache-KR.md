# Jamba hybrid 배치와 HiCache

`huggingface.jamba.hybrid.server`는 Jamba의 Attention KV, Mamba convolution 상태와 SSM 상태를 함께 관리합니다. 기존 Transformers 및 Mamba 엔진과 별도 모듈이며 같은 HTTP와 SSE API를 제공합니다. `model_type=jamba`이고 Attention과 Mamba 레이어를 모두 포함하는 로컬 체크포인트가 필요합니다. 기존 SmolLM2 또는 Mamba-130m 가중치는 사용할 수 없습니다.

## 실행

의존성은 [Transformers requirements](../../src/huggingface/requirements.txt)를 사용합니다. 모델 디렉터리에는 설정, safetensors 가중치와 토크나이저가 있어야 합니다.

```sh
PYTHONPATH=src python -m huggingface.jamba.hybrid.server \
  --model /path/to/jamba --served-model-name jamba-hybrid \
  --device cuda --dtype float16 \
  --max-parallel 4 --batch-wait-ms 5 \
  --cache-dir /tmp/jamba-hicache \
  --cache-gpu-mib 64 --cache-ram-mib 256 --cache-disk-mib 1024
```

CPU에서는 `--device cpu --dtype float32`를 사용합니다. CPU 실행은 GPU 캐시 계층을 비활성화합니다. API 요청의 `model`은 `--served-model-name`과 일치해야 합니다.

```sh
curl http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"jamba-hybrid","messages":[{"role":"user","content":"Explain prefix caching."}],"temperature":0,"max_tokens":32}'
```

Docker 타깃은 CPU용 `transformers-hybrid`, GPU용 `transformers-hybrid-gpu`입니다.

```sh
docker build -f src/Dockerfile.gpu --target transformers-hybrid-gpu \
  -t local/transformers-hybrid-gpu:0.1.0 src
docker run --rm --gpus all -p 8000:8000 \
  -v /path/to/jamba:/model:ro \
  local/transformers-hybrid-gpu:0.1.0 \
  --model /model --device cuda --dtype float16
```

디스크 캐시를 컨테이너 재시작 후 유지하려면 UID 1000이 쓸 수 있는 디렉터리를 연결하고 `--cache-dir`로 지정합니다. Kubernetes AIPerf 매니페스트는 Jamba를 제공하지 않습니다.

## 상태 버퍼와 배치

[HybridBuffer](../../src/huggingface/jamba/hybrid/state.py)는 `max_parallel`과 `n_ctx`에 맞춰 Attention KV 및 Mamba 상태 공간을 미리 확보합니다. KV는 기존 버퍼에 추가하므로 decode마다 전체 KV를 `torch.cat()`으로 다시 만들지 않습니다. Jamba의 PyTorch 경로가 교체한 Mamba 상태는 같은 버퍼에 복사하며, SSM의 float32 누적 정밀도를 유지합니다. 커널 내부의 임시 텐서 할당은 남아 있습니다.

[배치 백엔드](../../src/huggingface/jamba/hybrid/backend.py)는 다음과 같이 처리합니다.

- prefix 길이와 복원 길이가 같은 요청을 묶어 prefill합니다. 캐시 miss는 prefix 전체를 한 번에 계산합니다.
- checkpoint가 prefix 전체와 일치하면 중간 prefill 버퍼 복사를 생략하고 decode 버퍼에 바로 복원합니다.
- 복원한 Mamba 상태에 suffix를 추가할 때는 한 토큰씩 계산합니다. 현재 Jamba 구현의 상태 갱신 조건입니다.
- 길이가 다른 요청은 Attention KV에만 왼쪽 padding을 적용하고, 각 요청의 정확한 Mamba 상태를 넣어 함께 decode합니다.
- EOS, 출력 제한 또는 취소로 완료된 행은 KV와 Mamba 상태에서 함께 제거합니다.
- 같은 샘플링 설정은 배치 단위로 처리하고, 생성 토큰은 단계마다 한 번만 CPU로 옮깁니다.
- padding 때문에 `n_ctx`를 초과할 조합은 하위 배치로 나눕니다. 진행 중인 배치에 새 요청을 추가하지 않습니다.

`--mamba-kernels auto`는 CUDA 장치와 Jamba에서 사용할 수 있는 가속 커널이 모두 있으면 사용합니다. `off`는 PyTorch 경로를 사용하며 `required`는 가속 커널이 없으면 시작을 거부합니다. 제공 Docker 이미지는 `mamba-ssm`과 `causal-conv1d`를 설치하지 않으므로 PyTorch 경로로 동작합니다.

CUDA Graph는 이 모듈에 적용하지 않습니다. 현재 Jamba의 mask 생성과 Mamba fallback은 동적인 shape와 텐서 교체를 사용하므로 기존 Llama 전용 그래프를 재사용할 수 없습니다.

## Prefix checkpoint와 계층 이동

checkpoint는 **입력의 마지막 토큰 직전**에서 KV, convolution 상태와 SSM 상태를 함께 저장합니다. 마지막 입력 토큰은 다시 계산해 logits를 얻습니다. 생성 토큰의 상태는 prefix 캐시에 저장하지 않습니다.

Mamba 상태는 과거 위치로 잘라낼 수 없습니다. 따라서 저장된 토큰 전체가 요청 prefix와 일치하는 checkpoint 중 가장 긴 항목만 복원합니다. 예를 들어 `[1, 2, 3]` checkpoint는 `[1, 2, 3, 4]` 입력에 사용할 수 있지만 `[1, 2, 9, 4]` 입력에는 사용할 수 없습니다. 중간 경계 checkpoint는 자동 생성하지 않습니다.

[HiCache](../../src/huggingface/jamba/hybrid/hicache.py)의 계층은 다음과 같습니다.

| 계층 | 저장 형태 | 한도 초과 시 |
| --- | --- | --- |
| GPU | 독립적으로 복사한 KV와 Mamba 텐서 | LRU 항목을 CPU RAM으로 이동 |
| CPU RAM | GPU 실행 시 pinned 텐서, CPU 실행 시 일반 텐서 | LRU 항목을 safetensors로 직렬화해 디스크로 이동 |
| 디스크 | 토큰 ID와 checksum을 포함한 `.kv` 파일 | LRU 파일 삭제 |

항목은 한 계층에 보관하며, hit 시 예산이 허용하는 상위 계층으로 이동합니다. GPU와 RAM 예산은 텐서 payload 및 토큰당 8바이트를 합산합니다. 디스크는 파일 크기를 계산합니다. 한 계층의 전체 예산보다 큰 항목은 하위 계층으로 넘기고, 모든 계층에 들어갈 수 없으면 보관하지 않습니다. GPU 캐시 복사 중 CUDA OOM이 발생하면 해당 항목을 RAM 또는 디스크로 넘깁니다.

`--cache-gpu-mib`, `--cache-ram-mib`, `--cache-disk-mib`는 각 계층의 예산이며 0이면 비활성화합니다. `--cache-min-prefix`는 저장 및 복원할 최소 토큰 수입니다. 기본값은 [EngineSettings](../../src/huggingface/jamba/hybrid/engine.py)를 참고하고, 전체 CLI 옵션은 `python -m huggingface.jamba.hybrid.server --help`로 확인합니다.

활성 배치 버퍼, 모델 가중치, prefill 결과 복사본, 역직렬화 버퍼 및 Python 객체는 캐시 예산에 포함되지 않습니다. 활성 추론 중 OOM에 대한 자동 재시도는 하지 않습니다. prefix 캐시의 복사본은 활성 버퍼와 분리되어 있어 배치 갱신과 eviction이 저장된 상태를 변경하지 않습니다.

모델 파일 해시, 라이브러리 버전, dtype, 장치와 커널 경로로 namespace를 분리합니다. 디스크는 단일 writer를 허용하고 정상 종료 시 상위 계층을 저장합니다. checksum이나 텐서 구조가 잘못된 항목은 삭제하고 다시 계산합니다. 이전 namespace는 자동 삭제하지 않습니다.

이 구현은 [SGLang HiCache의 GPU, host, storage 계층 구조](https://docs.sglang.ai/advanced_features/hicache_design.html)를 참고한 프로젝트 내부 구현입니다. 저장소는 로컬 파일이며, I/O는 동기식입니다. SGLang 런타임, radix page 공유, 비동기 prefetch 및 분산 storage backend는 포함하지 않습니다.

## 검증

```sh
PYTHONPATH=src:tests python -m unittest \
  test_transformers_hybrid test_transformers_server \
  test_transformers_batch test_enhanced_cache_llamacpp -v
```

테스트는 작은 무작위 Jamba 모델을 생성해 캐시 없는 기준 출력과 cold 및 warm cache, 배치 출력의 일치를 확인합니다. prefix 경계, 버퍼 재사용, 행 제거, 취소, SSE, 계층 승격과 퇴출, 재시작 및 손상 복구를 검사합니다. CUDA PyTorch 환경에서는 float16과 float32 GPU 검증도 실행합니다. 이 검증은 실제 Jamba 체크포인트의 품질이나 처리량 벤치마크를 대체하지 않습니다.

## Base와 성능 비교

[직렬 base](../../src/huggingface/jamba/base/engine.py)는 같은 Jamba 모델을 Transformers `generate()`로 실행합니다. 요청 내부의 dynamic KV와 Mamba 상태는 사용하며 요청 간 prefix 캐시와 배치는 사용하지 않습니다. HTTP로 실행하려면 모듈을 `huggingface.jamba.base.server`로 지정합니다.

벤치마크에는 AI21의 학습된 개발용 [Jamba-tiny-dev](https://huggingface.co/ai21labs/Jamba-tiny-dev)를 사용합니다. 모델 revision과 파일 체크섬은 [모델 설정](../../config/models/jamba-tiny-dev-transformers.env)에 고정되어 있습니다.

```sh
./scripts/download-transformers-model.sh jamba-tiny-dev
python scripts/benchmark-hybrid.py \
  --model .models/jamba-tiny-dev --device cuda --dtype float16 \
  --prompt-lengths 64,256 --max-tokens 32 --concurrencies 1,2,4,8 \
  --repetitions 3 --waves 2 \
  --report-dir docs/reports/gpu/hybrid/benchmark-suite-local
```

결과 디렉터리는 비어 있어야 합니다. 조건은 base, 배치만 적용, cold cache, GPU hit, RAM hit, disk hit입니다. warm 조건은 요청 묶음마다 해당 계층에 checkpoint를 배치하며, 복원된 토큰 수와 실제 hit 계층을 검사합니다. 모든 측정 출력은 같은 모델의 base 출력 토큰 ID와 대조하며 불일치가 있으면 실패합니다.

HTTP와 입력 토큰화는 제외한 엔진 벤치마크입니다. 요청 대기열과 배치 대기 시간은 포함하며 TTFT는 첫 생성 토큰 기준입니다. 모델 로딩과 워밍업, warm cache 준비는 제외합니다. 실행 순서는 반복마다 순환하고, 디스크 조건은 OS page cache를 비우지 않습니다. AIPerf 보고서와 측정 범위가 다릅니다.

`run.json`에는 모델과 소스 SHA-256, 입력 및 기준 출력, 실행 설정과 검증 개수가 기록됩니다. `summary.md`, `summary.csv`, `summary.jsonl`은 base 대비 처리량과 지연을, `runs.csv`와 로컬 `requests.jsonl`은 개별 측정 결과를 제공합니다.

RTX 2060 SUPER에서 실행한 [base 및 hybrid 비교 결과](../reports/gpu/hybrid/README.md)에서 전체 조건과 검증 결과를 확인할 수 있습니다.
