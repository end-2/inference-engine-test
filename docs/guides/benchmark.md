# 벤치마크 실행과 결과 분석

기본 엔진은 Transformers CPU이며 base, batch, prefix KV cache 구현의 처리량과 지연을 AIPerf로 비교합니다. llama.cpp도 선택할 수 있습니다. 추론 구현과 API는 [추론 엔진 가이드](inference-engine.md)를 참고하세요.

## 구성

| 항목 | 설정 |
| --- | --- |
| 클러스터 | 기본 단일 노드 kind, 추론 서버와 AIPerf Job 배치 |
| 모델 | SmolLM2 Transformers CPU, 서버와 AIPerf가 같은 revision의 토크나이저 사용 |
| 추론 구현 | base, enhanced/batch, enhanced/cache 중 선택 |
| 단일 측정 | 동시성별 추론 Pod 재시작 후 워밍업과 본 요청 실행 |
| 반복 측정 | 구현별 반복 실행, 회차마다 실행 순서 순환 |
| 관측 | AIPerf 요청별 결과와 Kubernetes 노드, Pod, 컨테이너 자원 표본 |

부하 조건과 옵션별 값은 [AIPerf 기본 벤치마크 설정](aiperf.md#기본-벤치마크-설정)을 따릅니다. 추론 자원과 스레드는 각 구현의 Deployment에서 관리하며 측정 Pod는 CPU와 메모리 `requests=limits`를 유지합니다.

## 준비

Docker, POSIX 셸, Python 3.10 이상과 make가 필요합니다. 모델과 이미지 다운로드 연결 및 [CPU, 메모리, 디스크 요구사항](requirements.md#cpu-메모리와-디스크)을 확인하고 저장소 루트에서 도구를 설치합니다.

```sh
./scripts/local-k8s.sh install
```

모델과 토크나이저 다운로드, 클러스터 생성, 이미지 빌드와 로드는 자동 runner가 수행합니다. 토크나이저를 수동으로 준비하려면 [AIPerf 가이드](aiperf.md#토크나이저-준비)를 참고하세요. 측정 중에는 다른 부하 실험을 중지합니다.

기본 실행은 단일 노드 클러스터를 사용합니다. 멀티 노드에서는 `--inference-node`와 `--benchmark-node`를 모두 지정하며, 캐시 PV의 node affinity에 맞춰 노드를 선택합니다. `up`은 기존 클러스터의 토폴로지를 변경하지 않습니다.

## 배포와 실행

### Pod 재시작을 포함한 자동 측정

```sh
make benchmark
# 배칭 또는 캐시 구현을 측정할 때 선택
make benchmark VARIANT=transformers-enhanced-batch
make benchmark VARIANT=transformers-enhanced-cache
```

각 명령은 모델 다운로드와 검증, 클러스터 준비, 이미지 빌드와 로드, 배포와 측정을 수행합니다. 실패하면 다음 조건으로 진행하지 않으며, 완료된 결과와 진단 로그를 남깁니다. 완료 후 서버와 클러스터는 유지됩니다.

make 없이 실행하려면 `./scripts/run-benchmark.py`를 사용합니다. 사용자 지정 이미지, 노드와 제한 시간 옵션은 `--help`에서 확인합니다.

### 동시성별 PVC cache 초기화

| `CACHE_POLICY` | 초기화 시점 |
| --- | --- |
| `preserve` | 디스크 캐시 유지 |
| `clear-before-sweep` | 첫 동시성의 워밍업 전 |
| `clear-per-concurrency` | 각 동시성의 워밍업 전 |

Transformers cache variant의 기본값은 `clear-before-sweep`이며 나머지 variant는 `preserve`입니다.

```sh
make benchmark VARIANT=transformers-enhanced-cache CACHE_POLICY=clear-per-concurrency
```

초기화는 추론 Pod 종료와 flush를 기다린 뒤 전용 PVC의 캐시 파일을 삭제합니다. 모델과 결과 PVC는 유지합니다. 워밍업과 본 요청 사이에는 캐시를 재사용하므로 모든 요청의 cache miss를 측정하는 조건은 아닙니다. 사용한 정책은 `run.json`에 기록됩니다.

### 전체 구현 반복 측정

base, batch, cache를 각각 3회 측정하며 회차마다 실행 순서를 순환합니다. cache는 sweep 직전에 초기화하고 동시성 사이에는 보존합니다.

```sh
make benchmark-suite
# 반복 수 변경
make benchmark-suite REPETITIONS=1
# 완료된 sweep을 유지하며 재개
python3 scripts/run-benchmark-suite.py --resume 'docs/reports/transformers/benchmark-suite-<UTC 시각>'
```

### llama.cpp 선택

Qwen2.5 GGUF와 로컬 토크나이저를 사용하는 [전용 프로필](../../k8s/aiperf-qwen2.5/)을 선택합니다.

```sh
make benchmark VARIANT=base-llamacpp
make benchmark VARIANT=enhanced-batch-llamacpp
make benchmark VARIANT=enhanced-cache-llamacpp
python3 scripts/run-benchmark-suite.py --backend llamacpp
```

llama.cpp suite는 base, batch, cache 초기화와 cache 보존의 네 조건을 반복합니다. 캐시 정책은 각각 `clear-per-concurrency`, `clear-before-sweep`입니다.

## 결과와 관찰

단일 측정 결과는 `docs/reports/<backend>/bench-<UTC 시각>-<이미지>/`에 저장합니다. `<backend>`는 `transformers` 또는 `llamacpp`입니다.

집계는 `docs/reports/<backend>/benchmark-suite-<UTC 시각>/`에 저장합니다. p95 집계는 실행별 p95의 평균입니다. `profiling_seconds`는 본 요청 시간, `job_and_collection_seconds`는 Job 생성부터 수집 완료까지의 시간입니다. 전체 sweep에는 Pod 준비와 캐시 초기화 시간이 포함됩니다.

| 파일 | 내용 |
| --- | --- |
| `summary.md`, `summary.csv`, `summary.jsonl` | 동시성별 지표 또는 반복 집계 |
| `run.json`, `inference.json`, `nodes.json` | 실행 상태, 이미지 ID와 환경 |
| `c*/artifacts/profile_export.jsonl`, `c*/requests.csv` | 요청별 원본과 지표 |
| `c*/resources.jsonl`, `c*/resources.csv` | 노드, Pod와 컨테이너 자원 표본 |
| suite의 `runs.csv` | 개별 실행 지표 |

추론 자원 분석에는 `role=inference`, `scope=pod`를 사용하고 Pod와 컨테이너 값을 중복 합산하지 않습니다. 요청 분석은 `benchmark_phase=profiling`을 선택합니다. 자원 표본은 구간 관측값이며 개별 요청의 CPU 비용을 나타내지 않습니다.

원본과 상세 로그의 Git 보관 범위는 [제외 규칙](../reports/.gitignore)을 따릅니다. `--reports-dir`은 지정한 경로를 그대로 사용합니다.

## 검증과 문제 해결

```sh
python3 -m unittest discover -s tests -p 'test_benchmark*.py'
```

- `Pending`: 추론 Pod와 Job의 CPU, 메모리 예약량을 확인합니다.
- `hostPath type check failed`: 모델과 토크나이저 다운로드, 노드의 `/models` 마운트를 확인합니다.
- HTTP 404: Job의 모델 이름과 서버 모델 이름을 확인합니다.
- HTTP 400: 채팅 템플릿을 포함한 입력 길이와 출력, 컨텍스트 제한을 확인합니다.
- 자원 수집 실패: 노드 `proxy/stats/summary` 읽기 권한과 Pod CPU 표본을 확인합니다.
