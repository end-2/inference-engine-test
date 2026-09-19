# CPU 추론 API

배칭과 계층형 KV 캐시 구현의 배포·설정은 [확장 구현 가이드](llama-enhanced.md)를 참고하세요.

[README](../README.md)의 배포 절차를 완료한 뒤 서버 준비를 기다리고 포트를 연결합니다.

```sh
./scripts/local-k8s.sh kubectl rollout status deployment/llama-base --timeout=300s
./scripts/local-k8s.sh kubectl port-forward service/llama-base 8000:8000
```

다른 터미널에서 호출합니다. 모델 이름은 [모델 설정](../config/models/qwen2.5-0.5b-gguf.env)의 `SERVED_MODEL_NAME`과 같습니다.

```sh
curl http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"Qwen/Qwen2.5-0.5B-Instruct","messages":[{"role":"user","content":"안녕하세요"}],"max_completion_tokens":32}'
```

`GET /healthz`, `GET /readyz`는 모델 로드 후 상태를 반환하고, `GET /v1/models`는 모델 이름을 반환합니다. 채팅은 `system`, `user`, `assistant` 역할과 문자열 또는 텍스트 파트 배열을 지원합니다. 출력 길이는 `max_tokens` 또는 `max_completion_tokens` 중 하나로 지정합니다.

`stream: true`는 SSE 응답을 사용합니다. `stream_options: {"include_usage": true}`를 함께 지정하면 마지막 데이터 청크에 토큰 사용량이 포함됩니다. 정상 종료는 `[DONE]`, 생성 실패는 `error` 객체로 구분합니다.

## 실행과 길이 제한

서버 옵션은 `PYTHONPATH=src python -m base.server --help`, 배포 값은 [Deployment](../k8s/llama-base/deployment.yaml)를 참고하세요. 프롬프트는 GGUF 채팅 템플릿을 적용한 뒤 토큰화합니다. 입력 제한, 출력 제한 또는 입력과 요청 출력의 합이 컨텍스트 크기를 넘으면 HTTP 400을 반환하며 길이를 자동으로 줄이지 않습니다.

토큰 사용량은 실제 입력과 생성된 토큰 ID를 기준으로 계산합니다. `ignore_eos: true`는 종료 토큰을 억제해 지정 길이 측정에 사용합니다. 모델 접근은 단일 스레드로 직렬화되며, 연결 종료 시 진행 중인 생성은 다음 중단 검사에서 멈춥니다. 프롬프트 처리 중에는 중단까지 시간이 걸릴 수 있습니다.

## 검증

API 회귀 테스트는 모델 없이 실행할 수 있습니다. 별도 Python 환경에서 실행합니다.

```sh
python -m pip install fastapi==0.141.1 httpx==0.28.1
python -m unittest discover -s tests -p 'test_llama_server.py' -v
```

실제 모델의 토큰 집계와 중단 동작은 추론 의존성을 설치한 뒤 검증합니다. 네이티브 라이브러리 빌드에는 C/C++ 컴파일러와 CMake가 필요합니다.

```sh
python -m pip install -r src/base/requirements.txt
TEST_MODEL_PATH="$PWD/.models/qwen2.5-0.5b/qwen2.5-0.5b-instruct-q4_k_m.gguf" \
  python -m unittest discover -s tests -p 'test_llama_engine.py' -v
```

실행 중인 서버의 HTTP 및 SSE 응답은 다음 명령으로 검증합니다.

```sh
python tests/test-llama-api.py
```

다른 주소는 `API_SERVER_URL`, 다른 모델 이름은 `SERVED_MODEL_NAME`으로 지정합니다.
