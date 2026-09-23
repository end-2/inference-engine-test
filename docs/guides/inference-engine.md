# CPU 추론 엔진

Manifest 적용과 ConfigMap 변경 방법은 [manifest 관리](manifests.md)를 참고합니다.

기본 엔진은 Transformers + PyTorch CPU이며 llama.cpp도 선택할 수 있습니다. 두 엔진 모두 base, enhanced/batch, enhanced/cache를 제공합니다. 이 문서는 Transformers의 실행과 설정을 먼저 설명하고 [llama.cpp](#llamacpp) 차이를 뒤에 정리합니다.

## Transformers

`src/transformers_cpu/`는 로컬 `HuggingFaceTB/SmolLM2-135M-Instruct`를 PyTorch CPU에서 실행합니다. base는 직렬 추론, enhanced/batch는 요청 배칭, enhanced/cache는 요청 간 prefix KV 재사용을 제공합니다. 배칭과 prefix 캐시는 독립적인 구현입니다.

### 모델과 로컬 실행

Python 3.12 환경에서 실행합니다. 모델 가중치, 토크나이저, 설정은 [고정 revision](../../config/models/smollm2-135m-transformers.env)과 [SHA-256 목록](../../config/models/smollm2-135m-transformers.sha256)으로 검증합니다. 다운로드에는 `curl`과 `sha256sum` 또는 `shasum`이 필요합니다. 선택한 모델 파일을 저장할 디스크와 가중치, KV 캐시, 런타임을 수용할 메모리를 확보합니다.

```sh
./scripts/download-transformers-model.sh
python3.12 -m venv /tmp/transformers-cpu-venv
. /tmp/transformers-cpu-venv/bin/activate
# Linux에서는 CPU 전용 PyTorch를 먼저 설치합니다.
python -m pip install torch==2.10.0 --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r src/transformers_cpu/requirements.txt
PYTHONPATH=src python -m transformers_cpu.base.server --model .models/smollm2-135m
```

macOS에서는 CPU 인덱스 설치 명령을 생략하고 requirements만 설치합니다. 모델은 항상 CPU에 배치하며 기본 dtype은 `float32`입니다. `--dtype bfloat16`도 지원하지만 CPU와 커널에 따라 성능이 달라집니다. 의존성 버전은 [requirements](../../src/transformers_cpu/requirements.txt)를 따릅니다.

다운로드는 검증된 파일을 보존하며 중단된 파일을 이어받습니다. 전체 파일의 검증이 끝난 뒤 `.models/smollm2-135m/`를 공개합니다. `LOCAL_K8S_MODELS_DIR`로 모델 루트를 변경할 수 있으며 클러스터 생성에도 같은 값을 사용합니다. 서버는 로컬 파일만 읽으며 원격 모델 코드나 자동 다운로드를 사용하지 않습니다.

모델은 영어 중심의 SmolLM2-135M-Instruct를 사용하며, Llama 모델 클래스로 로딩하고 모델의 채팅 템플릿을 적용합니다. CPU 스레드는 실행 환경에 맞춰 `--n-threads`로 지정합니다.

### API와 구현 선택

`GET /healthz`와 `GET /readyz`는 서버 상태를, `GET /v1/models`는 제공하는 모델을 반환합니다. `POST /v1/chat/completions`는 `messages`의 대화 내용을 받아 응답을 생성합니다. `stream: true`는 SSE 응답을 사용하며 정상 종료 시 `[DONE]`을 전송합니다. 모델 ID는 `HuggingFaceTB/SmolLM2-135M-Instruct`입니다. `max_tokens` 또는 `max_completion_tokens`, `temperature`, `top_p`, `ignore_eos`, `stream_options.include_usage`를 지원합니다.

```sh
curl http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"HuggingFaceTB/SmolLM2-135M-Instruct","messages":[{"role":"user","content":"Say hello in one short sentence."}],"max_tokens":32}'
```

| 구현 | Python 모듈 | Docker 타깃, 이미지 이름 |
| --- | --- | --- |
| Base | `transformers_cpu.base.server` | `transformers-base` |
| Batch | `transformers_cpu.enhanced.batch.server` | `transformers-enhanced-batch` |
| Cache | `transformers_cpu.enhanced.cache.server` | `transformers-enhanced-cache` |
| Base + Prometheus | `transformers_cpu.base_metric.server` | `transformers-base-metric` |

로컬 실행 명령의 모듈을 바꾸어 구현을 선택합니다. 공통 CLI와 기본값은 각 모듈의 `--help`를 참고하세요. 입력과 출력의 합은 `--n-ctx`를 넘을 수 없으며 입력을 자동으로 자르지 않습니다. 토큰 수는 실제 입력 및 생성 ID로 계산하며 종료 EOS는 출력 토큰 수에서 제외합니다. SSE 텍스트는 UTF-8과 단어 경계를 보존하므로 한 청크가 여러 토큰을 포함할 수 있습니다.

Base와 cache는 Transformers의 `generate()`로 생성하며 KV 갱신과 종료 조건을 라이브러리에 맡깁니다. 샘플링은 `temperature > 0`일 때만 활성화하고 `top_k=0`으로 top-k 제한을 끕니다. 요청의 `temperature`, `top_p`에 모델 파일의 샘플링 기본값을 추가로 적용하지 않습니다. `ignore_eos`는 종료 조건만 끄는 대신 EOS 토큰을 억제합니다.

스트리밍은 `TextStreamer`로 디코딩하며 base와 cache는 `skip_prompt=True`로 입력 텍스트를 제외합니다. 사용량은 생성 ID에서 입력과 마지막 EOS를 제외해 계산합니다. 마지막 생성 단계에서 EOS가 나오면 `finish_reason`은 `stop`입니다. 생성 전 취소된 요청은 모델을 호출하지 않습니다. 생성 중 취소는 `StoppingCriteria`가 토큰 생성 후 확인하므로 진행 중인 연산과 해당 토큰 출력을 즉시 중단하지 않습니다.

Base + Prometheus는 같은 직렬 엔진에 `/metrics`의 `transformers_*` 요청, 토큰 수, TTFT 지표를 추가합니다. 로컬 실행에는 `src/transformers_cpu/base_metric/requirements.txt`도 설치합니다. [멀티 노드 availability](availability-test.md)와 [HPA](hpa-test.md)는 이 이미지를 사용합니다.

### 요청 배칭

[배칭 작업자](../../src/transformers_cpu/enhanced/batch/engine.py)는 `--batch-wait-ms` 동안 모은 요청을 `--max-parallel` 크기까지 함께 실행합니다. 길이가 다른 입력은 토크나이저의 왼쪽 패딩과 `prepare_inputs_for_generation()`의 position ID 준비를 사용합니다. 샘플링에는 Transformers의 `TemperatureLogitsWarper`, `TopPLogitsWarper`, `SuppressTokensLogitsProcessor`를 사용합니다. 각 요청의 샘플링 옵션과 출력 제한, 취소 상태를 분리하고, 종료된 행은 다음 decode 전에 KV와 배치에서 제거합니다.

일반 `generate()`가 제공하지 않는 요청별 생성 설정, 스트림 분배와 완료 행 제거는 [배치 백엔드](../../src/transformers_cpu/enhanced/batch/backend.py)의 루프에서 처리합니다. 진행 중인 배치에는 새 요청을 추가하지 않습니다. 새 요청은 다음 배치를 기다리므로 긴 출력이 대기 시간을 늘릴 수 있습니다. 모델 연산은 한 작업자만 실행하고 HTTP 스레드는 결과를 기다립니다. 작업자 오류는 대기 요청에 전달되며 health와 readiness가 실패합니다. 요청 간 prefix 캐시는 유지하지 않습니다.

### Prefix KV 캐시

[캐시 엔진](../../src/transformers_cpu/enhanced/cache/engine.py)은 `generate()`가 반환된 뒤 `DynamicCache.crop()`으로 입력 길이만 남겨 safetensors로 저장합니다. 생성 토큰의 KV는 저장하지 않습니다. 토큰 ID의 최장 공통 prefix를 복원하여 `past_key_values`로 전달하고 나머지 입력을 계산합니다. 입력 전체가 일치하면 마지막 토큰을 다시 계산해 logits를 얻습니다. 모든 구현은 한 요청의 decode 안에서 KV를 사용하며, cache 구현은 이를 요청 사이에도 재사용합니다. 생성 중 예외나 프로세스 종료가 발생하면 해당 요청의 새 snapshot은 저장하지 않습니다.

| CLI 옵션 | 용도 |
| --- | --- |
| `--cache-dir` | 캐시 저장 루트 |
| `--cache-ram-mib` | 직렬화한 KV와 토큰 ID의 RAM 예산, 0이면 비활성화 |
| `--cache-disk-mib` | namespace별 디스크 예산, 0이면 비활성화 |
| `--cache-min-prefix` | 저장과 복원을 허용하는 최소 prefix 토큰 수 |

RAM LRU에서 밀려난 항목은 디스크로 이동하며, 디스크 hit는 크기가 허용하면 RAM으로 올라옵니다. 정상 종료 시 RAM 항목을 저장합니다. 체크섬 오류나 잘못된 텐서는 버리고 다시 계산합니다. 모델 파일 해시와 구조, head 크기, 라이브러리 버전, dtype, 컨텍스트와 CPU 설정으로 namespace를 분리하고 단일 writer 잠금을 사용합니다. 저장된 응답 텍스트를 재사용하지 않습니다.

RAM 예산은 실행 중인 모델 KV, 역직렬화 버퍼, Python 인덱스를 포함하지 않습니다. 디스크 쓰기는 동기식입니다. 이전 namespace는 자동 삭제하지 않으며, 강제 종료 시 RAM에만 있던 항목은 유실될 수 있습니다.

### Docker와 Kubernetes

[Dockerfile](../../src/Dockerfile)은 `src/`를 컨텍스트로 사용하며 Transformers 타깃은 CPU PyTorch wheel을 설치합니다. 가중치는 이미지에 포함하지 않습니다.

```sh
make download-model
./scripts/local-k8s.sh up
make build-image load-image
./scripts/local-k8s.sh kubectl apply -f k8s/transformers-base/
./scripts/local-k8s.sh kubectl rollout status deployment/transformers-base --timeout=300s
./scripts/local-k8s.sh kubectl port-forward service/transformers-base 8000:8000
```

각 디렉터리에는 Deployment와 Service manifest가 있으며 cache는 PVC도 포함합니다. 배칭과 캐시는 다음 명령으로 전환합니다.

```sh
make build-image load-image VARIANT=transformers-enhanced-batch
./scripts/local-k8s.sh kubectl apply -f k8s/transformers-enhanced-batch/

make build-image load-image VARIANT=transformers-enhanced-cache
./scripts/local-k8s.sh kubectl apply -f k8s/transformers-enhanced-cache/
```

세 구성 중 하나만 선택해 적용합니다. 같은 `Deployment/transformers-base`와 `Service/transformers-base`를 교체하며, 다른 구현으로 전환해도 캐시 PVC는 유지됩니다. 성능 측정 시 같은 노드의 다른 추론 작업을 함께 실행하지 않습니다.

배포 전에는 `./scripts/local-k8s.sh kubectl apply --dry-run=server -f k8s/transformers-base/`로 API 서버 검증을 실행할 수 있습니다. 위 명령은 매니페스트의 기본 이미지 태그를 사용합니다. 다른 `IMAGE_TAG`로 빌드했다면 선택한 `deployment.yaml`의 `image`도 같은 태그로 맞춥니다.

CPU, 메모리와 `--n-threads`는 각 Deployment에서 설정합니다.

모델은 kind 노드의 `/models/smollm2-135m`에서 `/model`로 읽기 전용 마운트합니다. 측정 Pod의 CPU와 메모리는 requests와 limits를 동일하게 설정합니다. 실제 자원값은 [base Deployment](../../k8s/transformers-base/deployment.yaml)를 참고하세요. 캐시 구현은 [전용 PVC](../../k8s/transformers-enhanced-cache/cache.yaml)를 `/cache`에 연결하며 클러스터의 기본 StorageClass가 필요합니다.

### 검증

테스트는 위 Python 환경에 `httpx`와 메트릭 의존성을 추가해 실행합니다. SmolLM2와 같은 Llama 구조의 작은 가중치를 임시 생성하여 CPU 연산, 배치 패딩과 완료 행 제거, 취소, 캐시 복원과 손상 복구를 검증합니다.

```sh
python -m pip install -r src/transformers_cpu/base_metric/requirements.txt httpx
python -m unittest discover -s tests -p 'test_transformers_*.py' -v
sh tests/test-download-transformers-model.sh
# 실행 중인 로컬 클러스터의 API discovery를 사용합니다.
sh tests/test-transformers-manifests.sh
TEST_TRANSFORMERS_MODEL_PATH="$PWD/.models/smollm2-135m" \
  python -m unittest discover -s tests -p 'test_transformers_engine.py' -v
# 실행 중인 API에 실제 HTTP와 SSE 요청
SERVED_MODEL_NAME=HuggingFaceTB/SmolLM2-135M-Instruct python tests/test-api-llamacpp.py
```

실제 모델 테스트는 `generate` 결과, SSE 내용과 디스크 캐시 복원을 검증합니다.

## llama.cpp

llama.cpp는 GGUF 모델을 CPU에서 실행합니다. base는 직렬 추론, enhanced/batch는 continuous batching, enhanced/cache는 RAM과 디스크 prefix KV 캐시를 제공합니다. 배칭과 캐시는 독립적으로 실행합니다. 의존성과 CPU 빌드 옵션은 [Dockerfile](../../src/Dockerfile)에서 관리합니다.

### 엔진 전환

Transformers와 llama.cpp는 서로 다른 Deployment를 사용합니다. 같은 클러스터에서 엔진을 전환할 때는 기존 엔진의 Pod를 먼저 중지합니다. 유휴 Pod도 자원을 예약하므로 함께 배포하면 새 Pod가 CPU나 메모리 부족으로 Pending 상태에 머물 수 있습니다.

Transformers에서 llama.cpp로 전환하려면 실행 중인 벤치마크를 마친 뒤 다음을 실행합니다.

```sh
./scripts/local-k8s.sh kubectl scale deployment/transformers-base --replicas=0
./scripts/local-k8s.sh kubectl wait --for=delete pod -l app=transformers-base --timeout=120s
```

반대 방향은 위 명령의 `transformers-base`를 `base-llamacpp`로 바꿉니다. 처음 선택하는 엔진이라면 중지 단계는 필요 없습니다. 이후 대상 엔진의 매니페스트를 적용하거나 벤치마크를 실행하면 해당 Deployment가 다시 시작됩니다. PVC와 모델은 유지됩니다.

### llama.cpp 배포

저장소 루트에서 `VARIANT=base-llamacpp`를 지정해 모델과 이미지를 준비합니다.

```sh
make download-model VARIANT=base-llamacpp
make up
make build-image load-image VARIANT=base-llamacpp
./scripts/local-k8s.sh kubectl apply -f k8s/base-llamacpp/
```

위 배포 절차를 완료한 뒤 서버 준비를 기다리고 포트를 연결합니다.

```sh
./scripts/local-k8s.sh kubectl rollout status deployment/base-llamacpp --timeout=300s
./scripts/local-k8s.sh kubectl port-forward service/base-llamacpp 8000:8000
```

다른 터미널에서 호출합니다. 모델 이름은 [모델 설정](../../config/models/qwen2.5-0.5b-gguf-llamacpp.env)의 `SERVED_MODEL_NAME`과 같습니다.

```sh
curl http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"Qwen/Qwen2.5-0.5B-Instruct","messages":[{"role":"user","content":"안녕하세요"}],"max_completion_tokens":32}'
```

`GET /healthz`, `GET /readyz`는 모델 로드 후 상태를 반환하고, `GET /v1/models`는 모델 이름을 반환합니다. 채팅은 `system`, `user`, `assistant` 역할과 문자열 또는 텍스트 파트 배열을 지원합니다. 출력 길이는 `max_tokens` 또는 `max_completion_tokens` 중 하나로 지정합니다.

`stream: true`는 SSE 응답을 사용합니다. `stream_options: {"include_usage": true}`를 함께 지정하면 마지막 데이터 청크에 토큰 사용량이 포함됩니다. 정상 종료는 `[DONE]`, 생성 실패는 `error` 객체로 구분합니다.

### 실행과 길이 제한

서버 옵션은 `PYTHONPATH=src python -m llamacpp.base.server --help`, 배포 값은 [Deployment](../../k8s/base-llamacpp/deployment.yaml)를 참고하세요. 프롬프트는 GGUF 채팅 템플릿을 적용한 뒤 토큰화합니다. 입력 제한, 출력 제한 또는 입력과 요청 출력의 합이 컨텍스트 크기를 넘으면 HTTP 400을 반환하며 길이를 자동으로 줄이지 않습니다.

토큰 사용량은 실제 입력과 생성된 토큰 ID를 기준으로 계산합니다. `ignore_eos: true`는 종료 토큰을 억제해 지정 길이 측정에 사용합니다. 모델 접근은 단일 스레드로 직렬화되며, 연결 종료 시 진행 중인 생성은 다음 중단 검사에서 멈춥니다. 프롬프트 처리 중에는 중단까지 시간이 걸릴 수 있습니다.

### llama.cpp base 검증

대표 질문에 대한 응답 품질은 [간단한 품질 확인](quality-check.md)을 참고하세요.

API 회귀 테스트는 모델 없이 실행할 수 있습니다. 별도 Python 환경에서 실행합니다.

```sh
python -m pip install fastapi==0.141.1 httpx==0.28.1
python -m unittest discover -s tests -p 'test_server_llamacpp.py' -v
```

실제 모델의 토큰 집계와 중단 동작은 추론 의존성을 설치한 뒤 검증합니다. 네이티브 라이브러리 빌드에는 C/C++ 컴파일러와 CMake가 필요합니다.

```sh
python -m pip install -r src/llamacpp/base/requirements.txt
TEST_MODEL_PATH="$PWD/.models/qwen2.5-0.5b/qwen2.5-0.5b-instruct-q4_k_m.gguf" \
  python -m unittest discover -s tests -p 'test_engine_llamacpp.py' -v
```

실행 중인 서버의 HTTP 및 SSE 응답은 다음 명령으로 검증합니다.

```sh
python tests/test-api-llamacpp.py
```

다른 주소는 `API_SERVER_URL`, 다른 모델 이름은 `SERVED_MODEL_NAME`으로 지정합니다.

### llama.cpp 구현 선택

| 구현 | Python 모듈 | 이미지 타깃 |
| --- | --- | --- |
| Base | `llamacpp.base.server` | `base-llamacpp` |
| Batch | `llamacpp.enhanced.batch.server` | `enhanced-batch-llamacpp` |
| Cache | `llamacpp.enhanced.cache.server` | `enhanced-cache-llamacpp` |
| Base + Prometheus | `llamacpp.base_metric.server` | `base-metric-llamacpp` |

base 배포에서 모델과 클러스터를 준비한 뒤 선택한 이미지를 빌드하고 적용합니다.

```sh
make build-image load-image VARIANT=enhanced-batch-llamacpp
./scripts/local-k8s.sh kubectl apply -f k8s/enhanced-batch-llamacpp/
./scripts/local-k8s.sh kubectl rollout status deployment/base-llamacpp --timeout=300s
```

캐시는 위 명령의 `enhanced-batch-llamacpp`를 `enhanced-cache-llamacpp`로 바꿉니다. 세 구성은 같은 `Deployment/base-llamacpp`와 `Service/base-llamacpp:8000`을 교체하므로 하나만 적용합니다. Deployment selector는 유지하고 Pod의 `inference-variant` 레이블과 이미지로 구현을 구분합니다. 측정 자원은 base와 동일하게 `requests=limits`를 사용합니다.

Base + Prometheus는 [가용성 테스트](availability-test.md#llamacpp)와 [HPA 테스트](hpa-test.md#llamacpp)에 사용합니다. 부하 설정은 [AIPerf](aiperf.md), 성능 비교는 [벤치마크](benchmark.md), 응답 품질은 [품질 확인](quality-check.md)을 참고하세요.

### Continuous batching

[배칭 작업자](../../src/llamacpp/enhanced/batch/batching.py)는 하나의 native context를 소유합니다. 요청마다 sequence ID, sampler, 생성 토큰, UTF-8 스트림 디코더를 분리합니다. 디코딩 중인 요청의 토큰을 먼저 배치에 넣고, 남는 공간에 새 프롬프트 조각을 배치합니다. 완료되거나 취소된 요청의 KV를 제거하고 대기 요청에 슬롯을 할당합니다.

HTTP 작업자 스레드는 스케줄러의 결과를 기다립니다. 모델과 토크나이저는 배칭 작업자만 접근합니다. native decode 실패 시 대기 중인 호출을 오류로 종료하고 health/readiness를 실패로 반환합니다.

| CLI 옵션 | 용도 |
| --- | --- |
| `--max-parallel` | 활성 요청 슬롯 수. `--n-batch` 이하여야 함 |
| `--prefill-chunk` | 요청당 한 스케줄링 단계에서 처리하는 입력 토큰 상한 |
| `--n-batch` | 모든 요청을 합쳐 native decode에 제출하는 토큰 상한 |
| `--n-ubatch` | native 계산의 물리 배치 상한 |
| `--n-threads-batch` | prefill 및 다중 토큰 decode 스레드 수. 생략하면 `--n-threads` 값 사용 |
| `--n-ctx` | 요청 하나의 입력과 출력 합계 제한 |

native KV 공간은 `n_ctx × max_parallel`을 기준으로 할당하며, 라이브러리의 정렬 때문에 실제 크기는 늘어날 수 있습니다. 배칭 버전은 요청 간 prefix 캐시를 유지하지 않습니다. 기본값은 `PYTHONPATH=src python -m llamacpp.enhanced.batch.server --help`, 배포값은 [Deployment](../../k8s/enhanced-batch-llamacpp/deployment.yaml)를 참고하세요.

### RAM과 디스크 계층형 캐시

[캐시 엔진](../../src/llamacpp/enhanced/cache/engine.py)은 base의 직렬 생성 경로에 prefix 조회와 복원을 추가합니다. 입력 prefill 이후 첫 토큰을 샘플링한 시점에 입력의 native sequence KV만 저장합니다. Python scores 배열과 생성 응답은 저장하지 않습니다.

조회는 토큰 ID의 최장 공통 prefix를 찾습니다. 현재 native context보다 더 긴 prefix를 재사용할 수 있을 때 복원합니다. 상태 복원 후 새 suffix를 계산하며, 입력 전체가 일치하면 마지막 입력 토큰을 다시 계산해 logits를 갱신합니다.

1. RAM hit는 해당 항목의 LRU 순서를 갱신합니다.
2. RAM 한도를 넘으면 오래된 항목을 디스크로 내립니다.
3. 디스크 hit는 체크섬 검증 후 RAM으로 올립니다. RAM보다 큰 항목은 디스크에 유지합니다.
4. 디스크 한도를 넘으면 디스크 LRU 항목을 제거합니다. 정상 종료 시 남은 RAM 항목도 저장합니다.

디스크 쓰기는 동기식이며 임시 파일, fsync, atomic rename을 사용합니다. 프로세스 강제 종료 전 RAM에만 있던 항목은 유실될 수 있습니다. 손상된 항목은 버리고 재계산합니다. 모델 파일, native 라이브러리, 패키지 버전, 컨텍스트 크기와 아키텍처로 namespace를 구분하며, namespace별 단일 writer 잠금을 사용합니다.

| CLI 옵션 | 용도 |
| --- | --- |
| `--cache-dir` | 캐시 저장 루트 |
| `--cache-ram-mib` | native 상태와 토큰 ID의 RAM 예산. 0은 RAM 계층 비활성화 |
| `--cache-disk-mib` | namespace별 디스크 파일 예산. 0은 디스크 계층 비활성화 |
| `--cache-min-prefix` | 저장과 복원을 허용하는 최소 공통 prefix 토큰 수 |

RAM 예산에는 Python 인덱스, 컨테이너와 복원 중 임시 버퍼가 포함되지 않습니다. 디스크 예산은 namespace별이며 이전 모델 namespace는 자동 삭제하지 않습니다. 인덱스는 메모리에서 선형 탐색합니다. 기본값은 `PYTHONPATH=src python -m llamacpp.enhanced.cache.server --help`를 참고하세요.

[캐시 Deployment](../../k8s/enhanced-cache-llamacpp/deployment.yaml)는 `/cache`에 [PVC](../../k8s/enhanced-cache-llamacpp/cache.yaml)를 마운트합니다. 다른 구현으로 전환하거나 추론 Pod를 재시작해도 PVC는 유지됩니다. 클러스터의 기본 StorageClass가 필요합니다.

### llama.cpp enhanced 검증

모델 없는 검증에는 base API 테스트와 같은 `fastapi`, `httpx` 환경을 사용합니다.

```sh
python -m unittest discover -s tests -p 'test_enhanced_*.py' -v
```

native 통합 검증에는 각 이미지와 같은 `llama-cpp-python` 버전 및 실제 GGUF가 필요합니다.

```sh
TEST_MODEL_PATH="$PWD/.models/qwen2.5-0.5b/qwen2.5-0.5b-instruct-q4_k_m.gguf" \
  python -m unittest discover -s tests -p 'test_enhanced_native_llamacpp.py' -v
```

배칭의 다중 요청 decode, 취소, 슬롯 재사용, 캐시의 spill, promotion, 손상 복구, 재시작, HTTP/SSE 호환성을 검증합니다.
