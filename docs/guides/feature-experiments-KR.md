# 기능별 성능 실험

기능별 구현은 HTTP 요청 경로를 공유하고 스케줄링과 모델 상태 처리는 각 엔진에서 담당합니다.

## 소스 경계

| 모듈 | 역할 |
| --- | --- |
| `src/inference/api.py` | 요청 검증, SSE, 취소와 응답 토큰 집계 |
| `src/inference/contracts.py` | 엔진 인터페이스, 생성 요청과 결과 타입 |
| `src/inference/cache.py` | RAM과 디스크의 snapshot 저장, 조회와 퇴출 |
| `src/inference/metrics.py` | 선택적으로 활성화하는 요청과 생성 지표 |
| `src/huggingface/runtime/` | 모델 간 공통 직렬 생성, 배치 큐, 샘플링과 서버 설정 |
| `src/huggingface/{llama,mamba,jamba}/` | 모델 로딩과 기본값, baseline과 기능별 구현 |
| `src/llamacpp/{base,batch,cache,metrics}/` | GGUF 추론과 선택적 지표 수집 |

```text
src/
├── inference/
├── huggingface/
│   ├── runtime/
│   ├── llama/      # base, batch/gpu, cache, metrics, inference_distributed
│   ├── mamba/      # base, cache
│   └── jamba/      # base, hybrid
└── llamacpp/       # base, batch, cache, metrics
```

각 Hugging Face 모델 계열은 `model.py`에서 로딩을, `serving.py`에서 HTTP 기본값을 정의합니다. `base/`는 직렬 비교 진입점을 제공합니다. 기능별 구현은 같은 계열의 모델과 `runtime/`을 사용하며, 공통 코드는 비교 진입점이나 다른 모델 계열을 import하지 않습니다. 패키지 이름은 설치된 `transformers` 라이브러리와 구분되도록 `huggingface`를 사용합니다.

Python 진입점은 이 구조를 따릅니다. HTTP 벤치마크 suite는 [inference.json](../../benchmarks/inference.json)에서 Docker 빌드 대상, 이미지 이름과 variant ID를 연결하며, 이 식별자들은 Python 패키지 이름과 별개입니다.

엔진은 `prepare_prompt`, `complete`, `stream`, `close`를 구현합니다. `stream`은 callback으로 텍스트를 전달하고 토큰 수와 종료 사유를 반환합니다. `complete`는 텍스트도 반환합니다. Executor는 서버 설정에서 생성하여 직렬과 배치 구현의 동시성 동작을 유지합니다. 지표 수집은 metric 진입점에서만 활성화합니다.

## 실험 설정

`benchmarks/`는 성능 비교 조건과 부하 정의를 관리하며, `benchmarks/aiperf/`에 AIPerf 이미지 빌드 구성을 둡니다. `config/`는 클러스터, 도구 버전과 모델 준비 설정을, `k8s/`는 배포 차트를 관리합니다.

[inference.json](../../benchmarks/inference.json)은 기능별 이미지와 빌드 대상, CPU와 GPU Helm 프로필, 모델, AIPerf 프로필과 기본 suite 조건을 연결합니다. GPU 이미지와 빌드 대상은 설정된 이미지 이름에 `-gpu`를 붙입니다. 기존 Make 변수와 runner CLI 옵션으로 개별 설정을 덮어쓸 수 있습니다.

새 구현은 엔진 인터페이스, Docker 빌드 대상과 Helm 프로필을 추가하고 연결 정보와 비교 조건을 등록합니다. 비교할 때 baseline 설정, 모델 revision, 부하, 자원 제한과 측정 범위를 고정합니다.

Suite JSON은 `backend`, `device`, 비어 있지 않은 `conditions` 목록을 정의합니다. 각 조건은 고유한 `name`, 등록된 `variant`, `cache_policy`를 가지며 Transformers GPU 배칭에는 `cuda_graph`도 지정할 수 있습니다. 설정 파일에서 backend와 device를 선택하고 반복 수는 CLI로 지정합니다.

```sh
make benchmark-suite BENCHMARK_CONFIG=benchmarks/cuda-graph.json REPETITIONS=3
# Runner 직접 실행
python3 scripts/run-benchmark-suite.py --config benchmarks/cuda-graph.json --repetitions 3
```

[CUDA Graph 실험](../../benchmarks/cuda-graph.json)은 직렬 base, Graph를 끈 GPU batch, Graph를 필수로 적용한 GPU batch를 비교합니다. 두 batch 조건은 같은 이미지와 Helm 프로필을 사용하며 `--cuda-graph`만 변경합니다. 실행 순서는 반복마다 순환하고 동시성마다 새 추론 Pod로 시작합니다. `run.json`에 확정된 연결 정보와 조건을 기록하며 `--resume`은 이 기록을 사용합니다.

## CUDA Graph 선택과 실행 증거

GPU batch 서버는 `--cuda-graph auto|off|required`를 지원합니다.

| 모드 | 동작 |
| --- | --- |
| `auto` | 기본값. 지원 조건에서는 Graph를 적용하고 나머지는 eager로 실행합니다. |
| `off` | Eager GPU batch 구현을 사용합니다. |
| `required` | Greedy decoding, `ignore_eos=true`, CUDA와 Graph 컨텍스트 제한을 요구하며 지원하지 않는 작업은 실패합니다. |

```sh
make benchmark DEVICE=gpu VARIANT=transformers-enhanced-batch CUDA_GRAPH=off
```

`GET /runtime`은 실제 `eager` 또는 `cuda_graph` 경로별 완료 batch와 요청 수를 반환합니다. Graph 모드를 명시한 벤치마크는 부하 종료 후 이를 수집하여 `c*/runtime.json`과 `run.json`에 기록하고, 모드나 실행 경로가 실험 조건과 다르면 실패합니다. 횟수는 워밍업을 포함한 Pod 전체 실행 구간 기준이며 profiling 구간의 처리량 지표가 아닙니다. 실패한 batch 호출은 집계하지 않습니다. 실행 진단을 제공하지 않는 엔진은 빈 객체를 반환합니다.

HTTP suite는 `measurement_scope=http_chat_completions`를 기록합니다. [Hybrid 엔진 벤치마크](hybrid-cache-KR.md#base와-성능-비교)는 `engine_generation_first_token`을 기록하며 HTTP와 토큰화를 제외하고 첫 생성 토큰을 측정합니다. 결과를 비교할 때 두 측정 범위를 구분합니다.

## 검증

기존 서버와 모델 테스트 의존성이 설치된 환경에서 실행합니다.

```sh
PYTHONPATH=src:tests python -m unittest discover -s tests -p 'test_*.py'
```

API 동작, 취소, 캐시 복원, 작은 모델의 출력 일치, Graph 선택과 실험 연결을 검사합니다. CUDA 실행 검사는 CUDA PyTorch 환경이 필요합니다. 성능 수치는 대상 하드웨어에서 해당 벤치마크를 실행해 확인합니다.
