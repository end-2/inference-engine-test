# 벤치마크 실행과 결과 분석

AIPerf로 base, batch, prefix KV cache 구현의 처리량과 지연을 비교합니다. 기본 장치는 CPU이며 NVIDIA GPU도 선택할 수 있습니다.

추론 구현과 API는 [추론 엔진 가이드](inference-engine-KR.md)를 참고합니다.

소스 구조, 비교 조건 추가와 CUDA Graph 성능 분리 측정은 [기능별 실험 가이드](feature-experiments-KR.md)를 참고합니다.

## 구성

| 항목 | 설정 |
| --- | --- |
| 클러스터 | 기본 단일 노드 kind, 추론 서버와 AIPerf Job 배치 |
| 모델 | SmolLM2 Transformers CPU, 서버와 AIPerf가 같은 revision의 토크나이저 사용 |
| 추론 구현 | base, batch, cache 중 선택 |
| 단일 측정 | 동시성별 추론 Pod 재시작 후 워밍업과 본 요청 실행 |
| 반복 측정 | 구현별 반복 실행, 회차마다 실행 순서 순환 |
| 관측 | AIPerf 요청별 결과와 Kubernetes 노드, Pod, 컨테이너 자원 표본 |

부하 조건과 옵션별 값은 [AIPerf 기본 벤치마크 설정](aiperf-KR.md#기본-벤치마크-설정)을 따릅니다. 추론 자원과 스레드는 각 구현의 Deployment에서 관리하며 측정 Pod는 CPU와 메모리 `requests=limits`를 유지합니다.

## 준비

Docker, POSIX 셸, Python 3.10 이상과 make가 필요합니다. 모델과 이미지 다운로드 연결 및 [CPU, 메모리, 디스크 요구사항](requirements-KR.md#cpu-메모리와-디스크)을 확인하고 저장소 루트에서 도구를 설치합니다.

```sh
./scripts/local-k8s.sh install
```

모델과 토크나이저 다운로드, 클러스터 생성, 이미지 빌드와 로드는 자동 실행 스크립트가 수행합니다. 토크나이저를 수동으로 준비하는 방법은 [AIPerf 가이드](aiperf-KR.md#토크나이저-준비)를 참고합니다.

측정 중에는 다른 부하 실험을 중지합니다. 같은 클러스터에 다른 엔진을 이미 배포했다면 [엔진 전환](inference-engine-KR.md#엔진-전환)에 따라 기존 Pod를 중지합니다.

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

Runner는 [inference.json](../../benchmarks/inference.json)에서 이미지, 빌드 대상과 Helm 프로필을 선택합니다. `make`의 `VARIANT`는 이미지 이름을, runner는 backend별 variant ID를 사용합니다.

```sh
./scripts/run-benchmark.py --backend transformers --variant enhanced-batch
./scripts/run-benchmark.py --backend transformers --variant enhanced-cache --cache-policy clear-before-sweep
python3 scripts/run-benchmark-suite.py --backend transformers
```

`--image`, `--build-target`, `--manifests`, `--benchmark-manifests`로 개별 선택을 덮어쓸 수 있습니다. 노드와 제한 시간 옵션은 `--help`에서 확인합니다. AIPerf 이미지는 `benchmarks/aiperf/`에서 빌드합니다.

Make에서도 `BENCHMARK_ARGS`와 `BENCHMARK_SUITE_ARGS`로 실행 옵션을 전달할 수 있습니다. 짧은 동작 확인에는 동시성 하나와 요청 수, 출력 길이를 줄인 AIPerf 프로필을 선택합니다.

```sh
make benchmark BENCHMARK_ARGS='--concurrencies 1 --job-timeout 180'
make benchmark-suite BENCHMARK_SUITE_ARGS='--prepare-only'
```

### 동시성별 PVC cache 초기화

| `CACHE_POLICY` | 초기화 시점 |
| --- | --- |
| `preserve` | 디스크 캐시 유지 |
| `clear-before-sweep` | 첫 동시성의 워밍업 전 |
| `clear-per-concurrency` | 각 동시성의 워밍업 전 |

`make benchmark`는 Transformers와 Mamba의 cache variant에 `clear-before-sweep`을, 나머지 variant에 `preserve`를 기본 적용합니다. Runner를 직접 실행할 때의 기본값은 `preserve`이므로 캐시 조건을 비교할 때는 `--cache-policy`를 명시합니다.

```sh
make benchmark VARIANT=transformers-enhanced-cache CACHE_POLICY=clear-per-concurrency
```

캐시 초기화는 추론 Pod 종료와 flush를 기다린 뒤 전용 PVC의 캐시 파일을 삭제하는 방식으로 수행합니다. 모델과 결과 PVC는 유지하며, 사용한 정책은 `run.json`에 기록합니다.

워밍업과 본 요청 사이에는 캐시를 재사용하므로 모든 요청의 cache miss를 측정하는 조건은 아닙니다.

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

Qwen2.5 GGUF와 로컬 토크나이저를 사용하는 [전용 프로필](../../k8s/aiperf/profiles/qwen2.5.yaml)을 선택합니다.

```sh
make benchmark VARIANT=base-llamacpp
make benchmark VARIANT=enhanced-batch-llamacpp
make benchmark VARIANT=enhanced-cache-llamacpp
python3 scripts/run-benchmark-suite.py --backend llamacpp
```

llama.cpp suite는 base, batch, cache 초기화와 cache 보존의 네 조건을 반복합니다. 캐시 정책은 각각 `clear-per-concurrency`, `clear-before-sweep`입니다.

### Mamba 선택

```sh
make benchmark VARIANT=transformers-mamba-cache
python3 scripts/run-benchmark-suite.py --backend mamba
```

Mamba suite는 base, 동시성마다 캐시 초기화, sweep 시작 전에 캐시 초기화를 비교합니다. 모델 준비와 캐시 동작은 [Mamba 상태 캐시](mamba-cache-KR.md)를 참고합니다. Jamba는 별도의 [hybrid 엔진 벤치마크](hybrid-cache-KR.md#base와-성능-비교)를 사용합니다.

## 결과와 관찰

단일 측정 결과는 `docs/reports/<backend>/bench-<UTC 시각>-<이미지>/`에 저장합니다. `<backend>`는 `transformers`, `llamacpp`, `mamba`입니다.

반복 측정의 집계 결과는 `docs/reports/<backend>/benchmark-suite-<UTC 시각>/`에 저장합니다. p95 집계는 실행별 p95의 평균입니다.

`profiling_seconds`는 본 요청 시간, `job_and_collection_seconds`는 Job 생성부터 수집 완료까지의 시간입니다. 전체 sweep에는 Pod 준비와 캐시 초기화 시간이 포함됩니다.

| 파일 | 내용 |
| --- | --- |
| `summary.md`, `summary.csv`, `summary.jsonl` | 동시성별 지표 또는 반복 집계 |
| `run.json`, `inference.json`, `nodes.json` | 실행 상태, 이미지 ID와 환경 |
| `c*/artifacts/profile_export.jsonl`, `c*/requests.csv` | 요청별 원본과 지표 |
| `c*/resources.jsonl`, `c*/resources.csv` | 노드, Pod와 컨테이너 자원 표본 |
| suite의 `runs.csv` | 개별 실행 지표 |

추론 자원 분석에는 `role=inference`, `scope=pod`를 사용하고 Pod와 컨테이너 값을 중복 합산하지 않습니다. 요청 분석은 `benchmark_phase=profiling`을 선택합니다. 자원 표본은 구간 관측값이며 개별 요청의 CPU 비용을 나타내지 않습니다.

원본과 상세 로그의 Git 보관 범위는 [제외 규칙](../reports/.gitignore)을 따릅니다. `--reports-dir`은 지정한 경로를 그대로 사용합니다.

## GPU 벤치마크

GPU 클러스터는 CPU 클러스터와 별도인 `local-k8s-gpu`입니다. NVIDIA 드라이버, Docker의 NVIDIA 런타임, NVIDIA Container Toolkit, Go가 필요합니다. Toolkit의 `accept-nvidia-visible-devices-as-volume-mounts` 값을 활성화해야 합니다. `make install DEVICE=gpu`는 고정 버전의 nvkind, kind, kubectl과 Helm을 설치합니다. 시작 시 Docker의 GPU 접근, GPU 할당과 Pod의 `nvidia-smi` 접근을 검사합니다.

```sh
sudo nvidia-ctk config --set accept-nvidia-visible-devices-as-volume-mounts=true --in-place
```

```sh
make install DEVICE=gpu
make up DEVICE=gpu
make benchmark-suite DEVICE=gpu
make benchmark-suite DEVICE=gpu INFERENCE_BACKEND=llamacpp
```

단일 구현은 `make benchmark DEVICE=gpu VARIANT=transformers-enhanced-cache`처럼 선택합니다. 종료할 때는 `make down DEVICE=gpu`를 사용합니다. GPU 클러스터의 모델 디렉터리는 노드의 `/models`에 읽기 전용으로 마운트됩니다. GPU 하나는 추론 Pod 하나에 할당되고 AIPerf는 control-plane 노드에서 실행됩니다.

두 Pod에 GPU 공유 리소스를 할당하는 별도 환경은 [MPS 클러스터 가이드](gpu-mps-KR.md)를 참고합니다. 이 문서의 벤치마크는 `GPU_SHARING=none`을 사용합니다.

Transformers GPU 배치는 `make benchmark DEVICE=gpu VARIANT=transformers-enhanced-batch`로 측정합니다. GPU 전용 배치 구현과 CUDA Graph 적용 조건은 [추론 엔진 가이드](inference-engine-KR.md#요청-배칭)를 참고합니다.

GPU 측정은 동시성 `1,2,4,8`에서 같은 모델과 AIPerf 프로필을 사용합니다. Transformers는 `float16`, llama.cpp는 `n_gpu_layers=-1`로 실행합니다.

GPU 결과는 `docs/reports/gpu/<backend>/`에 저장합니다. `run.json`은 장치, dtype 또는 GPU 레이어 설정을 기록합니다. 각 동시성의 `gpu.csv`에는 GPU UUID, 사용률, 사용 메모리의 시계열이 있고 요약에는 평균과 최대값이 있습니다. CPU 결과는 기존 `docs/reports/<backend>/`에 저장합니다. 기존 CPU 결과와 이번 GPU 결과는 호스트 환경이 달라 성능 수치를 직접 비교하면 안 됩니다.

실측 1회차의 결과와 주의 사항은 [GPU 결과](../reports/gpu/README-KR.md)에 있습니다.

## 검증과 문제 해결

```sh
python3 -m unittest discover -s tests -p 'test_benchmark*.py'
```

- `Pending`: 추론 Pod와 Job의 CPU, 메모리 예약량을 확인합니다.
- `hostPath type check failed`: 모델과 토크나이저 다운로드, 노드의 `/models` 마운트를 확인합니다.
- HTTP 404: Job의 모델 이름과 서버 모델 이름을 확인합니다.
- HTTP 400: 채팅 템플릿을 포함한 입력 길이와 출력, 컨텍스트 제한을 확인합니다.
- 자원 수집 실패: 노드 `proxy/stats/summary` 읽기 권한과 Pod CPU 표본을 확인합니다.
