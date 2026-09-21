# 로컬 모델 관리

SmolLM2-135M-Instruct와 Qwen2.5-0.5B-Instruct의 다운로드, SHA-256 검증과 Kubernetes 볼륨 연결을 설명합니다. 모델은 호스트에 저장하고 kind 노드와 Pod에 읽기 전용으로 마운트합니다. 다운로드에는 `curl`, 인터넷 연결과 `sha256sum` 또는 `shasum`이 필요합니다. 디스크와 실행 자원은 [요구사항](requirements.md#cpu-메모리와-디스크)을 참고하세요.

## 모델과 설정

`make`의 기본 `VARIANT`는 `transformers-base`입니다. 모델 ID와 revision은 각 설정 파일에 고정되어 있습니다.

| 모델 | 실행 엔진 또는 용도 | 다운로드 설정과 체크섬 |
| --- | --- | --- |
| `HuggingFaceTB/SmolLM2-135M-Instruct` | Transformers | [설정](../../config/models/smollm2-135m-transformers.env), [파일별 SHA-256](../../config/models/smollm2-135m-transformers.sha256) |
| `Qwen/Qwen2.5-0.5B-Instruct-GGUF`, Q4_K_M | llama.cpp | [설정과 GGUF SHA-256](../../config/models/qwen2.5-0.5b-gguf-llamacpp.env) |
| `Qwen/Qwen2.5-0.5B-Instruct` | AIPerf 토크나이저 | [설정](../../config/models/qwen2.5-0.5b-tokenizer-llamacpp.env), [파일별 SHA-256](../../config/models/qwen2.5-0.5b-tokenizer-llamacpp.sha256) |

## 다운로드

저장소 루트에서 사용할 모델의 명령을 실행합니다. `make benchmark`와 `make benchmark-suite`는 선택한 백엔드의 다운로드와 검증을 자동 수행합니다.

### SmolLM2-135M-Instruct

Transformers로 실행하는 기본 모델입니다.

```sh
make download-model
# 스크립트 직접 실행: ./scripts/download-transformers-model.sh
```

가중치, 설정과 토크나이저를 함께 다운로드합니다. `make download-tokenizer`도 같은 스크립트를 실행하므로 모델을 준비했다면 별도로 실행할 필요가 없습니다.

### Qwen2.5-0.5B-Instruct

llama.cpp로 실행하는 Q4_K_M GGUF 모델입니다.

```sh
make download-model VARIANT=base-llamacpp
make download-tokenizer VARIANT=base-llamacpp
# 스크립트 직접 실행:
# ./scripts/download-model-llamacpp.sh
# ./scripts/download-tokenizer-llamacpp.sh
```

추론 서버는 GGUF 파일을 사용합니다. AIPerf 벤치마크에는 별도 토크나이저가 필요합니다. `enhanced-batch-llamacpp`와 `enhanced-cache-llamacpp`도 같은 모델을 사용합니다.

### 검증과 재시도

모든 다운로드 스크립트는 새 파일과 기존 파일의 SHA-256을 검증합니다. 중단되면 같은 명령을 다시 실행합니다.

- Qwen GGUF와 SmolLM2 다운로드는 중단된 파일을 이어받습니다.
- SmolLM2 모델과 Qwen 토크나이저는 임시 디렉터리의 검증된 파일을 재사용하고, 전체 파일 검증 후 최종 디렉터리로 이동합니다. 토크나이저의 미완료 파일은 다시 다운로드합니다.
- 기존 파일의 검증에 실패하면 자동으로 덮어쓰지 않습니다. 오류에 표시된 GGUF 파일 또는 모델/토크나이저 디렉터리를 별도로 옮긴 뒤 다시 실행합니다.

## 클러스터와 볼륨 연결

모델을 준비한 뒤 클러스터를 생성합니다. 클러스터 도구 설치와 설정은 [클러스터 가이드](local-k8s.md)를 참고하세요.

```sh
make up
```

`up`은 노드 생성 시 호스트 모델 루트(기본값: 저장소의 `.models/`)를 `/models`에 읽기 전용으로 bind mount합니다. Pod의 `hostPath`는 kind 노드 내부 경로를 가리킵니다.

| 용도 | 호스트 디렉터리 | kind 노드 디렉터리 | Pod 마운트 경로 |
| --- | --- | --- | --- |
| SmolLM2 추론 | `.models/smollm2-135m/` | `/models/smollm2-135m/` | `/model/` |
| SmolLM2 AIPerf 토크나이저 | `.models/smollm2-135m/` | `/models/smollm2-135m/` | `/tokenizer/` |
| Qwen2.5 추론 | `.models/qwen2.5-0.5b/` | `/models/qwen2.5-0.5b/` | `/model/` |
| Qwen2.5 AIPerf 토크나이저 | `.models/qwen2.5-0.5b/tokenizer/` | `/models/qwen2.5-0.5b/tokenizer/` | `/tokenizer/` |

Transformers 서버의 `--model`은 `/model`, llama.cpp 서버의 `--model`은 `/model/qwen2.5-0.5b-instruct-q4_k_m.gguf`입니다. 실제 볼륨 설정은 [Transformers Deployment](../../k8s/transformers-base/deployment.yaml), [llama.cpp Deployment](../../k8s/base-llamacpp/deployment.yaml)와 [AIPerf 가이드](aiperf.md)를 참고하세요. 서버 실행 방법은 [추론 엔진 가이드](inference-engine.md)에 있습니다.

### 저장 위치 변경

다른 디스크를 쓰려면 다운로드와 클러스터 생성에 같은 `LOCAL_K8S_MODELS_DIR`를 지정합니다. 이후 `up`과 벤치마크 실행에도 같은 값을 사용합니다. 상대 경로는 명령 실행 디렉터리 기준이며, 경로에 콜론은 사용할 수 없습니다.

```sh
export LOCAL_K8S_MODELS_DIR=/path/to/models
make download-model
make up
```

Qwen2.5를 사용할 때는 다운로드 명령에 `VARIANT=base-llamacpp`를 지정하고 토크나이저도 같은 모델 루트에 준비합니다.

기존 클러스터의 마운트가 없거나 지정한 경로와 다르면 `up`이 오류를 출력합니다. 노드 내부 PVC 등 필요한 데이터를 백업한 뒤 재생성합니다. 호스트 모델 디렉터리는 삭제되지 않습니다.

```sh
make down
make up
```

## Qwen2.5 GGUF 마운트 검증

[검증 Job](../../config/models/qwen2.5-0.5b-check-llamacpp.yaml)은 일반 사용자 권한으로 Qwen GGUF 파일 존재와 읽기 전용 마운트를 확인합니다. 추론 라이브러리 없이 실행하며, 완료 후 5분 뒤 삭제됩니다. 이미지가 없으면 처음 실행할 때 다운로드합니다. 이 Job은 SmolLM2 모델이나 추론 동작을 검증하지 않습니다.

```sh
job=$(./scripts/local-k8s.sh kubectl create -f config/models/qwen2.5-0.5b-check-llamacpp.yaml -o name)
./scripts/local-k8s.sh kubectl wait --for=condition=Complete "$job" --timeout=180s
./scripts/local-k8s.sh kubectl logs "$job"
```

## 문제 해결

- `hostPath type check failed`: 선택한 모델의 다운로드 완료 여부와 `/models` 마운트를 확인합니다. `Directory`를 사용하므로 잘못된 경로를 빈 디렉터리로 생성하지 않습니다.
- `Permission denied`: 모델 디렉터리에 탐색 권한, 파일에 읽기 권한이 있어야 합니다. 다운로드 스크립트는 `umask 022`로 새 파일과 디렉터리를 생성합니다.
- `Checksum mismatch` 또는 `Missing file or checksum mismatch`: 오류에 표시된 기존 파일이나 디렉터리를 별도로 옮긴 뒤 같은 다운로드 명령을 실행합니다.
