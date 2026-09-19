# AIPerf 측정

자동 측정은 조건마다 추론 Pod를 재시작하고 결과를 호스트에 저장합니다. Pod 재시작 없이 비교하려면 아래의 단일 Job sweep을 사용합니다. 두 방식 모두 [공통 Job](../k8s/aiperf/job.yaml)의 부하 설정을 사용합니다.

## Pod 재시작을 포함한 자동 측정

Docker, Python 3, 설치된 kind와 kubectl이 필요합니다. 저장소 루트에서 실행합니다.

```sh
make benchmark
# make 없이 실행
./scripts/run-benchmark.py
```

모델·토크나이저 다운로드와 검증, 클러스터 준비, 추론 및 AIPerf 이미지 빌드·로드, 배포를 자동 수행합니다. 빌드 경로의 내용이 이미지에 기록한 해시와 같으면 빌드를 생략하고, 모든 노드의 이미지 ID가 호스트와 같으면 로드를 생략합니다. 태그만 같고 내용이 다르면 다시 준비합니다. 해시 기록이 없는 이미지는 최초 한 번 빌드합니다.

각 동시성 `1,2,4,8`에 대해 추론 Deployment를 재시작하고 새 Pod의 준비를 기다린 뒤 워밍업 8회와 본 측정 100회를 수행합니다. `ignore_eos`를 사용해 지정한 출력 길이 전에 종료되지 않도록 하고, 결과의 성공 요청 수와 출력 길이를 검증합니다. 조건마다 별도 Job을 순차 실행합니다. 실행 중인 다른 AIPerf Job이 있으면 중단합니다. 완료 후 추론 서버와 클러스터는 유지합니다.

결과는 `docs/reports/bench-<UTC 시각>-<이미지>/`에 저장됩니다.

- `summary.md`, `summary.csv`: 동시성별 처리량, TTFT와 응답 지연
- `run.json`, `inference.json`, `nodes.json`: 이미지 ID, 실행 상태와 환경
- `c1/`, `c2/`, `c4/`, `c8/`: 새 추론 Pod UID, Job 설정, AIPerf 로그와 원본 결과

각 조건의 원본 데이터는 다음 파일로 보존합니다.

| 파일 | 내용 |
| --- | --- |
| `resources.jsonl` | kubelet Summary API의 노드 및 해당 추론·AIPerf Pod/컨테이너 통계. CPU 누적 시간, 사용량, 메모리, 원본 통계 시각과 호스트 수집 시각 포함 |
| `resources.csv` | 노드·Pod·컨테이너별 CPU 코어 수, 누적 CPU 시간, 구간 평균 CPU 코어 수, 메모리 사용량 |
| `artifacts/profile_export.jsonl` | 요청 ID, 시작·종료 시각, 워밍업/본 측정 구분, TTFT, 지연, 토큰 수, 청크 간 지연 등 AIPerf 요청별 원본 |
| `requests.csv` | 요청별 메타데이터와 지표를 열로 펼친 데이터. 배열 지표는 JSON 문자열로 보존 |
| `artifacts/inputs.json` | 생성한 입력 데이터 |

자원 수집은 Job 생성 전부터 완료까지 기본 5초 간격으로 수행합니다. 실제 간격에는 API 호출 시간이 더해지며 `--sample-interval`로 변경합니다. kubelet의 갱신 주기 때문에 같은 원본 시각의 표본이 반복될 수 있습니다. `cpu_cores`는 `usageNanoCores / 1e9`, `cpu_percent_one_core`는 한 코어를 100%로 표현합니다. `cpu_interval_cores`는 원본 시각과 누적 CPU 시간의 차이로 계산하며 첫 표본·중복 시각·카운터 초기화에서는 비어 있습니다. 메모리 단위는 bytes입니다. 노드 통계에는 다른 워크로드도 포함되므로 추론 비용 분석에는 `role=inference`, `scope=pod`를 사용하고 Pod와 컨테이너 행을 중복 합산하지 마세요.

요청의 `request_start_ns`/`request_end_ns`는 Unix epoch 나노초, 자원 통계의 `cpu_time`/`memory_time`과 `sampled_at`은 UTC 시각입니다. `benchmark_phase=profiling`인 요청을 선택해 같은 시간대의 CPU·메모리와 비교할 수 있습니다. CPU는 표본 구간의 합산 값이므로 동시 실행된 개별 요청의 CPU 비용을 직접 나타내지는 않습니다. 원본 JSONL은 정밀도와 모든 지표를 유지하므로 상세 분석의 기준으로 사용합니다.

수집에는 Kubernetes 노드 `proxy/stats/summary` 읽기 권한이 필요하며 기본 kind 관리자 설정에서는 추가 설치가 필요하지 않습니다. 수집 오류나 추론·AIPerf Pod CPU 표본 누락은 실행 실패로 기록합니다.

측정 실패 시 다음 조건으로 진행하지 않으며 완료된 결과와 진단 로그를 남깁니다. 조건별 기본 제한은 1시간이며 `--job-timeout`으로 변경할 수 있습니다.

동일한 API·실행 옵션을 지원하는 다른 구현은 이미지와 빌드 경로를 바꿉니다.

```sh
make benchmark INFERENCE_IMAGE=local/llama-custom:0.1.0 INFERENCE_CONTEXT=src/custom
```

이미 빌드하거나 pull한 이미지는 `INFERENCE_CONTEXT=`로 빌드를 생략합니다. 실행 인자나 Service가 다르면 해당 매니페스트와 대상을 지정합니다. 사용자 지정 매니페스트에도 모델 마운트와 동일한 자원 requests/limits를 설정하세요.

```sh
./scripts/run-benchmark.py --image local/custom:0.1.0 --build-context '' \
  --manifests k8s/custom --deployment custom --container api \
  --api-url http://custom:8000
```

전체 옵션은 `./scripts/run-benchmark.py --help`에서 확인합니다. 기본 모델과 토크나이저를 계속 사용하며, 다른 모델을 서빙할 때는 해당 볼륨과 AIPerf 토크나이저 설정도 맞춰야 합니다.

## 토크나이저 준비

호스트에서 토크나이저를 한 번 다운로드합니다. `curl`과 `sha256sum` 또는 `shasum`이 필요하며 Python은 필요하지 않습니다.

```sh
./scripts/download-tokenizer.sh
```

[토크나이저 설정](../config/models/qwen2.5-0.5b-tokenizer.env)의 커밋에서 필요한 파일만 내려받고 [SHA-256 목록](../config/models/qwen2.5-0.5b-tokenizer.sha256)으로 검증합니다. 중단 후 재실행하면 검증이 끝난 파일을 재사용합니다. 모든 파일이 준비된 후 최종 디렉터리에 배치하며, 기존 디렉터리는 체크섬을 검증하고 네트워크 없이 재사용합니다.

| 위치 | 경로 |
| --- | --- |
| 호스트 | `.models/qwen2.5-0.5b/tokenizer/` |
| kind 노드 | `/models/qwen2.5-0.5b/tokenizer/` |
| AIPerf Pod | `/tokenizer/` — 읽기 전용 |

모델과 동일한 `LOCAL_K8S_MODELS_DIR` 및 기존 `/models` 마운트를 사용합니다. 사용자 지정 경로는 다운로드와 클러스터 생성 시 같아야 합니다. [모델 볼륨 가이드](models.md)를 참고하세요. 클러스터를 삭제해도 호스트의 토크나이저는 남습니다.

AIPerf의 `--model`은 API 모델 이름, `--tokenizer`는 로컬 경로입니다. 준비된 토크나이저를 사용하므로 측정 시 Hugging Face 연결은 필요하지 않습니다. AIPerf 0.12의 로컬 경로 로딩을 위해 `HF_HUB_OFFLINE`과 `TRANSFORMERS_OFFLINE`은 설정하지 않습니다.

## Pod 재시작 없는 단일 Job sweep

[추론 API](llama-api.md)를 먼저 배포합니다. 동시성 목록은 [Job](../k8s/aiperf/job.yaml)의 `CONCURRENCIES`에서 지정합니다. 각 조건은 순차 실행되며 같은 데이터 seed를 사용합니다.

```sh
./scripts/build-benchmark-images.sh
./scripts/load-benchmark-images.sh
./scripts/local-k8s.sh kubectl rollout status deployment/llama-base --timeout=300s
./scripts/local-k8s.sh kubectl apply -k k8s/aiperf
./scripts/local-k8s.sh kubectl wait --for=condition=Complete job/aiperf --timeout=14400s
./scripts/local-k8s.sh kubectl logs job/aiperf
```

한 번 적용하면 Job, 결과 PVC와 reader Pod가 준비됩니다. Job 내부의 AIPerf가 동시성 조건을 차례로 측정하고 조건별 결과와 sweep 집계를 저장합니다. `CONCURRENCIES`를 쉼표로 구분한 목록으로 바꾸면 측정 조건을 변경할 수 있습니다. 단일 값도 지원합니다.

입출력 길이 분포, 조건별 요청 수, 워밍업과 제한 시간은 [Job](../k8s/aiperf/job.yaml)에서 관리합니다. `activeDeadlineSeconds`는 전체 sweep 제한이며, 조건 수나 반복 횟수를 늘리면 완료 대기 시간과 함께 조정합니다. 클라이언트 worker는 하나로 고정해 조건마다 프로세스 수가 달라지지 않도록 합니다. CPU와 메모리는 `requests`와 `limits`를 동일하게 유지합니다.

입력 길이에는 서버의 채팅 템플릿 토큰이 추가되므로 서버의 입력 및 컨텍스트 제한에 여유가 필요합니다. `--use-server-token-count`로 서버 토큰 사용량을 사용하며, `ignore_eos`로 조기 종료를 억제합니다.

## 결과와 재실행

결과는 PVC의 `/results/<Pod 이름>/`에 저장되며 그 아래 조건별 디렉터리와 `sweep_aggregate/profile_export_aiperf_sweep.json` 집계 파일이 생성됩니다. reader Pod가 준비되면 호스트로 복사합니다.

```sh
./scripts/local-k8s.sh kubectl wait --for=condition=Ready pod/aiperf-results --timeout=120s
./scripts/local-k8s.sh kubectl cp aiperf-results:/results ./reports
```

완료 Job은 자동 정리되지만 PVC 결과는 남습니다. 완료 후 즉시 재실행하거나 설정을 바꾸려면 Job을 삭제하고 다시 적용합니다. 새 Pod 이름으로 결과가 분리됩니다.

```sh
./scripts/local-k8s.sh kubectl delete job aiperf --ignore-not-found=true
./scripts/local-k8s.sh kubectl apply -k k8s/aiperf
```

클러스터 삭제 전 필요한 결과를 호스트로 복사하세요.

## 검증과 문제 해결

```sh
sh tests/test-aiperf-manifests.sh
sh tests/test-download-tokenizer.sh
python3 -m unittest discover -s tests -p test_benchmark_runner.py
```

실제 AIPerf 실행 검증은 AIPerf 이미지와 동일한 버전을 설치한 별도 Python 환경에서 실행합니다. 로컬 테스트 API에 짧은 sweep을 실행하며, 외부 네트워크를 차단하고 빈 Hugging Face 캐시에서 토크나이저 재사용을 확인합니다. 다른 토크나이저 경로는 `TEST_TOKENIZER_PATH`로 지정합니다.

```sh
python -m pip install aiperf==0.12.0
python tests/test-aiperf-sweep.py
```

- `hostPath type check failed`: 토크나이저 다운로드 완료 여부와 노드의 `/models` 마운트를 확인합니다.
- 토크나이저 체크섬 오류: 해당 토크나이저 디렉터리를 별도로 옮기고 다시 다운로드합니다.
- HTTP 404: Job의 `MODEL_ID`와 서버 모델 이름을 확인합니다.
- HTTP 400: 입력·출력 제한과 채팅 템플릿을 포함한 컨텍스트 크기를 확인합니다.
- Pending: 추론 Pod와 Job의 CPU·메모리 요청량을 수용할 수 있는지 확인합니다.
