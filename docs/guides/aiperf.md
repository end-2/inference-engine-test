# AIPerf 측정

CPU 추론 서버에 동시성별 부하를 보내 처리량, TTFT, ITL과 응답 지연을 측정합니다. 자동 실행, 캐시 정책, 반복 측정과 결과 해석은 [벤치마크 가이드](benchmark.md)를 참고하세요.

## 기본 벤치마크 설정

기본 대상은 SmolLM2 Transformers 서버입니다. 아래 값은 이 저장소의 Job에 명시된 설정입니다.

| 설정 | 원본 |
| --- | --- |
| 동시성, 요청 수, 입력과 출력 길이, seed | [AIPerf Job](../../k8s/aiperf/job.yaml) |
| 모델과 토크나이저 revision | [모델 설정](../../config/models/smollm2-135m-transformers.env) |
| 추론 자원, 스레드와 토큰 제한 | [Deployment](../../k8s/transformers-base/deployment.yaml) |
| 클러스터와 도구 버전 | [kind 설정](../../config/cluster/kind.yaml), [versions.env](../../config/versions.env) |

측정 Pod는 CPU와 메모리 `requests=limits`를 유지합니다.

### AIPerf 옵션과 설정값

| 옵션 또는 환경 변수 | 설정값 | 설명 |
| --- | --- | --- |
| `--model` / `MODEL_ID` | `HuggingFaceTB/SmolLM2-135M-Instruct` | 요청에 전달할 서버 모델 이름입니다. |
| `--url` / `API_URL` | `http://transformers-base:8000` | 클러스터 내부 추론 Service 주소입니다. |
| `--tokenizer` | `/tokenizer` | 입력 생성과 토큰 계산에 사용할 로컬 토크나이저 경로입니다. |
| `--endpoint-type`, `--streaming` | `chat`, 활성화 | 채팅 요청을 스트리밍으로 보내 TTFT와 ITL을 측정합니다. |
| `--use-server-token-count` | 활성화 | 서버가 반환하는 토큰 수를 사용합니다. |
| `--concurrency` / `CONCURRENCIES` | `1,2,4,8` | 동시에 처리 중인 요청 수를 각 값으로 설정해 측정합니다. 자동 runner는 동시성마다 별도 Job을 생성합니다. |
| `--sequence-distribution` | `64,32:50;256,64:50` | 입력 64토큰과 출력 32토큰, 입력 256토큰과 출력 64토큰 조합을 각각 50% 비중으로 생성합니다. 입력에는 채팅 템플릿 토큰이 추가됩니다. |
| `--num-dataset-entries` / `DATASET_ENTRIES` | `16` | 합성 데이터셋 항목 수입니다. 본 요청 수보다 작으므로 항목을 재사용합니다. |
| `--dataset-sampling-strategy` | `sequential` | 데이터셋 항목을 순서대로 선택합니다. |
| `--random-seed`, `--parameter-sweep-same-seed` | `42`, 활성화 | 난수 seed를 고정하고 sweep의 각 조건에서 같은 seed를 사용합니다. |
| `--extra-inputs` | `ignore_eos:true` | EOS로 조기 종료하지 않도록 요청해 지정한 출력 길이를 맞춥니다. |
| `--workers-max` | `1` | AIPerf 부하 생성 worker 수의 상한입니다. 동시 요청 수는 `--concurrency`로 정합니다. |
| `--warmup-request-count`, `--warmup-concurrency` | `2`, `1` | 동시성 조건마다 본 측정 전에 요청 2개를 동시성 1로 실행합니다. |
| `--request-count` | `100` | 동시성 조건별 본 측정 요청 수이며 워밍업 요청은 별도입니다. |
| `--request-timeout-seconds` | `3600` | 개별 요청의 제한 시간은 3,600초입니다. |
| `--no-server-metrics` | 활성화 | AIPerf의 서버 메트릭 수집을 끕니다. runner의 Kubernetes 자원 표본 수집은 별도입니다. |
| `--ui` | `none` | 대화형 UI 없이 실행합니다. |
| `--artifact-dir` | `/results/$(POD_NAME)` | Job의 결과 저장 경로입니다. 자동 runner는 `/results/<run-id>/c<동시성>`으로 변경합니다. |

AIPerf 컨테이너는 CPU `1`, 메모리 `1Gi`를 requests와 limits에 동일하게 지정합니다. Job 제한 시간은 `activeDeadlineSeconds: 14400`이며 개별 요청 timeout과 별개입니다. 자동 runner는 `--job-timeout` 값으로 덮어쓰며 기본값은 3,600초입니다.

[llama.cpp 프로필](../../k8s/aiperf-qwen2.5/job.yaml)은 모델을 `Qwen/Qwen2.5-0.5B-Instruct`, 주소를 `http://base-llamacpp:8000`, 호스트 토크나이저 경로를 `/models/qwen2.5-0.5b/tokenizer`로 변경합니다. 공통 부하 옵션은 동일하며, 자동 runner는 선택한 서버에 맞춰 모델과 주소를 설정합니다.

## 토크나이저 준비

자동 측정은 토크나이저를 함께 준비합니다. 수동으로 준비하려면 backend에 맞는 명령을 사용합니다.

```sh
make download-tokenizer
make download-tokenizer VARIANT=base-llamacpp
```

서버와 AIPerf는 같은 모델 revision의 토크나이저를 사용합니다. AIPerf Pod에는 `/tokenizer`로 읽기 전용 마운트하며, 다운로드와 클러스터 생성에 같은 `LOCAL_K8S_MODELS_DIR`를 지정합니다.

## 매니페스트 검증

```sh
sh tests/test-aiperf-manifests.sh
```

실행 오류 진단은 [벤치마크 문제 해결](benchmark.md#검증과-문제-해결)을 참고하세요.
