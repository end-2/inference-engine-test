# 간단한 응답 품질 확인

대표 질문 7개로 추론 서버의 응답 품질을 확인합니다. [품질 확인 스크립트](../../scripts/check-quality.py)는 질문을 순차 전송하고 응답, 검사 기준과 판정을 JSON으로 저장합니다.

SmolLM2는 영어 질문을, Qwen은 한국어 질문을 사용합니다. 영어 결과와 한국어 결과의 통과 수를 같은 품질 점수로 비교하지 않습니다.

## 실행

검사 대상은 `/v1/chat/completions`를 제공하는 실행 중인 서버입니다. 스크립트는 Python 3 표준 라이브러리만 사용하며 base, enhanced-batch와 enhanced-cache의 공통 API에서 실행할 수 있습니다.

Docker와 kind를 사용하는 아래 예제는 SmolLM2 base 서버를 준비하고 로컬 8000번 포트로 연결합니다. 저장소 루트에서 실행합니다.

```sh
./scripts/local-k8s.sh install
make download-model VARIANT=transformers-base
make up
make build-image load-image VARIANT=transformers-base
./scripts/local-k8s.sh kubectl apply -f k8s/transformers-base
./scripts/local-k8s.sh kubectl rollout status deployment/transformers-base --timeout=300s
```

```sh
./scripts/local-k8s.sh kubectl port-forward service/transformers-base 8000:8000
```

다른 터미널에서 저장소 루트를 기준으로 실행합니다.

```sh
python3 scripts/check-quality.py --output reports/transformers/quality-base.json
```

`--url`과 `--model`로 서버와 모델을 지정합니다. 기본 서버는 `http://127.0.0.1:8000`, 모델은 SmolLM2이며 `API_SERVER_URL`, `SERVED_MODEL_NAME`으로 변경할 수 있습니다. 언어를 고정하려면 `--language en` 또는 `--language ko`를 사용합니다.

llama.cpp 서버는 해당 서비스에 포트를 연결한 뒤 `python3 scripts/check-quality.py --backend llamacpp`로 검사합니다. 기본 모델은 Qwen2.5입니다.

기본 출력 상한은 128토큰, 요청별 timeout은 60초입니다. `--max-tokens`와 `--timeout`으로 변경하며, 출력 상한은 서버에서 허용하는 값 이하여야 합니다.

`--output`을 생략하면 `reports/<backend>/quality-<UTC 시각>.json`에 저장합니다. 같은 경로를 지정하면 기존 파일을 덮어씁니다.

## 검사 항목과 판정

| 항목 | 확인 방식 |
| --- | --- |
| 지시 수행 | `PASS`라는 답을 제시하는지 자동 확인 |
| 간단한 계산 | `17 + 25`의 계산 결과가 `42`인지 자동 확인 |
| 정보 추출 | 제시한 주문번호를 정확하게 답하는지 자동 확인 |
| JSON 내용 | `name`이 `Mina`이고 `count`가 3인지 자동 확인 |
| 대화 맥락 | 앞서 알려준 고양이 이름을 답하는지 자동 확인 |
| 요약 | 선택한 언어로 핵심 사실 보존 여부를 사람이 확인 |
| 영어 문장 바꾸기 또는 한국어 번역 | 영어 검사는 쉬운 영어로 바꾸기, 한국어 검사는 번역의 의미 보존을 사람이 확인 |

질문 세트와 판정 기준은 결과의 `language`, `criterion`, `answer`에 기록합니다. 자동 검사는 정답 내용을 확인하며 요약, 번역과 판단이 모호한 응답은 `REVIEW`로 남깁니다. `REVIEW`는 사람이 응답과 기준을 대조해 판정합니다.

출력에는 `PASS`, `FAIL`, `REVIEW`, `ERROR`를 구분합니다. 자동 검사 실패는 `FAIL`, HTTP 오류, 잘못된 API 응답, 빈 응답이나 출력 상한 도달은 `ERROR`입니다.

한 항목이 실패해도 나머지 질문을 실행하고 결과를 저장합니다. `FAIL` 또는 `ERROR`가 있으면 종료 코드 1, 나머지는 0입니다. 종료 코드가 0이어도 `REVIEW` 항목은 수동으로 검토해야 합니다.

요청은 `temperature=0`, `top_p=1`, `ignore_eos=false`를 사용합니다. 정상 종료를 허용하므로 고정 출력 길이 성능 측정과 조건이 다릅니다.

이 검사는 기본 응답을 확인하는 용도이며 종합 품질 점수나 구현 간 품질 동등성을 보장하지 않습니다.

## 스크립트 검증

모델 없이 로컬 테스트 서버로 정상 응답, 오답, API 오류와 출력 잘림 처리를 확인합니다.

```sh
python3 -m unittest discover -s tests -p 'test_quality_check.py'
```
