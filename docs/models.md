# 로컬 모델 볼륨

GGUF 모델 파일을 호스트에 내려받고 kind 노드와 Pod에 읽기 전용으로 마운트합니다. 다운로드에는 `curl`과 `sha256sum` 또는 `shasum`이 필요합니다. 모델 ID, 커밋과 SHA-256은 [모델 설정](../config/models/qwen2.5-0.5b-gguf.env)에 고정되어 있습니다.

## 다운로드와 연결

저장소 루트에서 실행합니다. 모델 파일에 약 1GB의 디스크 공간이 필요합니다.

```sh
./scripts/download-model.sh
./scripts/local-k8s.sh up
```

중단되면 같은 명령으로 이어받습니다. 다운로드한 파일과 기존 파일 모두 SHA-256을 검증한 뒤 사용합니다. 검증에 실패한 기존 파일은 별도로 옮기고 다시 실행합니다.

| 위치 | 경로 |
| --- | --- |
| 호스트 | `.models/qwen2.5-0.5b/` |
| kind 노드 | `/models/qwen2.5-0.5b/` |
| 아래 예제의 Pod | `/model/` |

`up`은 노드 생성 시 호스트 모델 디렉터리를 `/models`에 읽기 전용으로 bind mount합니다. Pod의 `hostPath`는 kind 노드 내부 경로를 가리킵니다. 다른 디스크를 쓰려면 다운로드와 클러스터 생성에 같은 경로를 지정합니다. 이후 `up`에도 같은 값을 사용합니다. 상대 경로는 명령 실행 디렉터리 기준이며, 경로에 콜론은 사용할 수 없습니다.

```sh
export LOCAL_K8S_MODELS_DIR=/path/to/models
./scripts/download-model.sh
./scripts/local-k8s.sh up
```

기존 클러스터에 마운트가 없으면 `up`이 오류를 출력합니다. 노드 데이터를 백업한 뒤 재생성합니다. 호스트의 `.models/`는 삭제되지 않습니다.

```sh
./scripts/local-k8s.sh down
./scripts/local-k8s.sh up
```

## 마운트 검증

[검증 Job](../config/models/qwen2.5-0.5b-check.yaml)은 일반 사용자 권한으로 모델 파일 존재와 읽기 전용 마운트를 확인합니다. 추론 라이브러리 없이 실행하며, 완료 후 5분 뒤 삭제됩니다. 이미지가 없으면 처음 실행할 때 다운로드합니다.

```sh
job=$(./scripts/local-k8s.sh kubectl create -f config/models/qwen2.5-0.5b-check.yaml -o name)
./scripts/local-k8s.sh kubectl wait --for=condition=Complete "$job" --timeout=180s
./scripts/local-k8s.sh kubectl logs "$job"
```

## 추론 Pod에서 사용

모델 파일은 `/model/qwen2.5-0.5b-instruct-q4_k_m.gguf` 경로로 지정합니다. 볼륨 설정은 [API 서버 Deployment](../k8s/llama-base/deployment.yaml)를 참고합니다. 모델 볼륨은 읽기 전용이며, 런타임 캐시와 출력은 `/tmp`에 저장합니다.

## 문제 해결

- `hostPath type check failed`: 다운로드 완료 여부와 `/models` 마운트를 확인합니다. `Directory`를 사용하므로 잘못된 경로를 빈 디렉터리로 생성하지 않습니다.
- `Permission denied`: 모델 디렉터리에 탐색 권한, 파일에 읽기 권한이 있어야 합니다. 다운로드 스크립트는 일반 사용자도 읽을 수 있는 권한으로 생성합니다.
