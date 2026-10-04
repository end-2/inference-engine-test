> English version: [English](mmlu-check.md)

# MMLU 정확도 검사

`make mmlu-check`는 Kubernetes Job에서 실행 중인 `/v1/chat/completions` 서버에 영어 MMLU 문항을 전송하고 생성된 A, B, C, D 답안을 채점합니다. Transformers, llama.cpp와 Mamba의 공통 API를 지원합니다.

서버의 채팅 템플릿을 적용한 생성 답안 평가입니다. [원본 MMLU 평가기](https://github.com/hendrycks/test/blob/master/evaluate.py)는 선택지의 로그 확률을 비교합니다. 결과는 `generated-choice-v1`, 예시 수와 평가 과목을 함께 표기하며 공개된 MMLU 점수와 동일한 조건으로 해석하지 않습니다.

## 실행

[추론 엔진 가이드](inference-engine-KR.md)로 클러스터와 서버를 준비하거나 benchmark 실행 후 남아 있는 서버를 사용합니다. Docker, Python 3.10 이상과 저장소에서 설치한 kubectl, kind, Helm이 필요합니다. Job은 클러스터 내부 서비스 DNS로 연결하므로 포트 포워딩이 필요하지 않습니다.

저장소 루트에서 [공식 데이터셋](https://github.com/hendrycks/test)을 내려받고 한 과목의 10문항을 검사합니다.

```sh
make mmlu-check MMLU_ARGS='--download-data --subjects abstract_algebra --limit 10'
```

[실행기](../../scripts/run-mmlu.py)는 Python 평가 이미지를 빌드하고 클러스터에 로드한 뒤 PVC와 파일 전송용 Pod를 생성합니다. 선택한 데이터 파일을 PVC로 복사한 다음 [평가 Job](../../k8s/mmlu/values.yaml)을 시작합니다. 실제 요청과 채점은 Job에서 실행합니다. 완료 후 결과와 로그를 호스트로 가져오고 Job, 전송용 Pod와 PVC를 삭제합니다. 추론 서버는 계속 실행됩니다.

`--download-data`는 호스트 데이터 디렉터리가 없을 때만 공식 아카이브를 내려받아 test와 dev CSV를 `.datasets/mmlu/`에 보관합니다. 실행 간에 기존 데이터를 재사용합니다. 최초 데이터와 이미지 다운로드에는 인터넷 연결이 필요하며 평가 Pod는 추론 서비스에만 연결하면 됩니다. 오프라인에서는 `--data-dir /path/to/data`로 기존 데이터를 지정합니다. `test/<subject>_test.csv`와 예시용 `dev/<subject>_dev.csv` 구조를 사용합니다. CSV는 헤더 없이 질문, 선택지 네 개와 정답 문자로 구성된 6열입니다.

전체 test 문항을 평가하거나 서버와 최소 정확도를 지정합니다.

```sh
make mmlu-check
make mmlu-check VARIANT=base-llamacpp MMLU_ARGS='--subjects abstract_algebra --limit 10'
make mmlu-check DEVICE=gpu MMLU_ARGS='--subjects abstract_algebra --limit 10'
make mmlu-check MMLU_ARGS='--url http://my-server:8000 --model my-model --min-accuracy 0.3'
make mmlu-check MMLU_ARGS='--few-shot 5 --output docs/reports/transformers/mmlu-base.json'
```

`VARIANT`는 [inference.json](../../benchmarks/inference.json)에 정의된 백엔드 기본 서비스와 모델을 선택합니다. 평가할 구현은 먼저 배포해야 합니다. `DEVICE`는 CPU 또는 GPU 클러스터를 선택합니다. 다른 서비스를 사용하려면 `--url`에 Pod에서 접근 가능한 주소를, `--model`에 서버의 served model 이름을 지정합니다. `127.0.0.1`은 평가 Pod 자신을 가리킵니다. 환경 변수 `API_SERVER_URL`과 `SERVED_MODEL_NAME`으로도 지정할 수 있습니다.

## 평가 조건

| 옵션 | 동작 |
| --- | --- |
| `--subjects NAME [NAME ...]` | 지정 과목만 평가, 생략하면 모든 test CSV 사용 |
| `--limit N` | 과목당 최대 N문항 표본 추출, 생략하면 전체 문항 |
| `--seed N` | 표본 추출 시드, 기본 0. 다른 과목의 추가나 제외와 관계없이 해당 과목의 표본 유지 |
| `--few-shot N` | 같은 과목의 앞쪽 dev 예시를 0~5개 포함, 기본 0 |
| `--max-tokens N` | 출력 상한, 기본 16토큰 |
| `--timeout SECONDS` | 요청별 timeout, 기본 60초 |
| `--min-accuracy FRACTION` | 선택적 최소 전체 정확도, 0~1 |
| `--namespace NAME` | Job과 서비스가 사용할 기존 네임스페이스, 기본 `default` |
| `--node NAME` | 평가와 전송용 Pod를 배치할 노드, 기본 control-plane 노드 |
| `--job-timeout SECONDS` | Job 제한 시간, 기본 14400초. 전체 평가나 느린 모델에서는 늘릴 수 있음 |
| `--ready-timeout SECONDS` | 전송용 Pod 준비 제한 시간, 기본 300초 |
| `--image NAME:TAG` | 실행기가 빌드하고 로드할 평가 이미지, 기본 `local/mmlu:0.1.0` |
| `--keep-resources` | 결과 수집 후 리소스를 보존해 점검 |

저장소의 짧은 context 프로필에서 입력 길이를 줄이도록 예시 없는 평가가 기본입니다. 긴 질문이나 예시 5개를 포함한 프롬프트는 서버 제한을 초과할 수 있습니다. 모델이 지원하는 context 범위에서 프롬프트와 출력이 들어가도록 서버의 `--max-input-tokens`와 `--n-ctx`를 설정하거나 `--few-shot`을 줄입니다. 입력 제한으로 거절된 문항은 오류로 기록하며 질문을 자르거나 예시 수를 자동으로 줄이지 않습니다.

요청은 순차 실행하며 `temperature=0`, `top_p=1`, `ignore_eos=false`를 사용합니다. 각 문항은 새 대화로 전송합니다. 구현 간 비교에서는 모델, 데이터셋 해시, 표본 시드, 예시 수와 서버 context 설정을 맞춥니다. 문항 수나 과목을 제한한 결과는 부분 평가입니다.

## 채점과 결과

대문자 답안 앞뒤 공백, 선택적인 `Answer:` 접두사와 뒤쪽 `.` 또는 `)` 하나를 허용합니다. 설명이나 여러 선택지가 포함된 답변은 `INVALID`입니다. 추출한 답안이 정답과 같으면 `CORRECT`, 다른 선택지이면 `INCORRECT`입니다. HTTP 실패, 잘못되거나 빈 응답, 출력 잘림을 포함해 finish reason이 `stop`이 아닌 응답은 `ERROR`입니다.

정확도는 정답 수를 시도한 모든 문항 수로 나누며 형식 오류와 요청 오류도 분모에 포함합니다. 과목별 정확도도 같은 규칙을 적용합니다. 전체 정확도는 과목별 백분율의 단순 평균이 아니라 문항 수에 따른 가중 평균입니다.

기본 결과 경로는 `docs/reports/<backend>/mmlu-<UTC>/summary.json`이며 GPU 결과는 `docs/reports/gpu/<backend>/` 아래에 저장합니다. `--output`으로 다른 호스트 JSON 파일을 지정하면 해당 경로의 기존 결과를 덮어씁니다. 전체와 과목별 점수, 실행 조건, 데이터 파일 SHA-256 해시, 표본 행 번호, 프롬프트, 정답과 예측, 원본 API 응답과 오류를 저장합니다. PVC의 `.jsonl` 파일에 완료한 문항을 즉시 기록하고 결과 수집 시 호스트로 가져옵니다. `<output-stem>-run/`에는 렌더링한 워크로드, 실행 정보, Pod 정보와 로그를 저장합니다.

Job이 정확도 기준 미달이나 API 오류로 실패해도 결과를 수집합니다. 완전한 JSON 결과를 가져오지 못하면 PVC와 전송용 Pod를 보존하고 가능한 JSONL을 수집한 뒤 실행 라벨을 출력합니다. Ctrl+C는 Job을 중단하고 부분 결과 수집을 시도한 후 종료 코드 130을 반환합니다. 중단된 Job은 JSONL만 남을 수 있습니다. 보존된 리소스는 해당 클러스터 스크립트와 네임스페이스를 지정해 삭제합니다.

```sh
./scripts/local-k8s.sh kubectl -n default delete job,pod,pvc -l mmlu-run=<run-id>
```

요청 오류, 준비 실패 또는 `--min-accuracy` 미달이면 종료 코드 1, 그 외에는 0입니다. 최소 정확도를 지정하지 않으면 오답과 형식 오류는 점수에 반영하지만 명령을 실패시키지 않습니다. 종료 코드 0은 평가 완료를 의미하며 최소 모델 품질을 보장하지 않습니다.

## 검증

```sh
python3 -m unittest discover -s tests -p 'test_mmlu*.py'
```

테스트는 로컬 예제 데이터, HTTP 서버와 Helm 렌더링을 사용하며 모델이나 데이터셋을 내려받지 않습니다.

## 호스트에서 직접 실행

외부에서 접근 가능한 API는 표준 라이브러리 평가기로 직접 검사할 수도 있습니다.

```sh
python3 scripts/check-mmlu.py --url http://127.0.0.1:8000 --subjects abstract_algebra --limit 10
```

접근 가능한 서버나 포트 포워딩이 필요합니다. 기본 결과 경로는 `docs/reports/<backend>/mmlu-<UTC>.json`이며 Ctrl+C는 부분 JSON 결과를 저장합니다.
