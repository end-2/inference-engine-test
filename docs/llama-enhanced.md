# CPU 추론 확장 구현

`enhanced-batch`는 continuous batching, `enhanced-cache`는 RAM·디스크 계층형 prefix KV 캐시를 제공합니다. 두 구현은 독립적이며 [base API](llama-api.md)의 요청, 응답, SSE, 토큰 집계와 길이 제한을 유지합니다. 의존성과 CPU 빌드 옵션은 base와 같습니다.

## 코드와 이미지 구성

`src/base/`는 공통 API·CLI와 기본 추론 엔진을 제공합니다. `src/enhanced/batch/`는 설정과 배칭 엔진·스케줄러를 추가하고, `src/enhanced/cache/`는 base 엔진을 상속해 prefix KV 복원·저장을 추가합니다. 확장 서버는 base의 앱 생성 함수를 사용하며 엔진 설정과 실행 스레드 구성을 확장합니다.

[Dockerfile](../src/Dockerfile)은 `src/`를 빌드 컨텍스트로 사용합니다. [공통 의존성](../src/base/requirements.txt)과 base 코드를 포함한 runtime 단계 위에 타깃별 Python 패키지만 복사합니다. 기본 타깃은 `base`입니다.

```sh
docker build --target base -t local/llama-base:0.1.0 src
docker build --target enhanced-batch -t local/llama-enhanced-batch:0.1.0 src
docker build --target enhanced-cache -t local/llama-enhanced-cache:0.1.0 src
```

컨테이너와 로컬 실행은 Python 모듈 진입점을 사용합니다. 저장소 루트에서 `PYTHONPATH=src python -m base.server`, `PYTHONPATH=src python -m enhanced.batch.server`, `PYTHONPATH=src python -m enhanced.cache.server`로 실행합니다.

## 배포와 AIPerf

각 디렉터리는 같은 `Deployment/llama-base`와 `Service/llama-base:8000`을 선언합니다. 매니페스트를 적용하면 현재 구현을 교체하며, 하나의 구현만 활성화됩니다. Deployment selector는 유지하고 Pod의 `inference-variant` 레이블과 이미지로 구현을 구분합니다. `k8s/` 전체를 한 번에 적용하지 마세요.

기존 AIPerf Job과 측정 스크립트를 사용합니다.

```sh
make benchmark VARIANT=enhanced-batch
make benchmark VARIANT=enhanced-cache
# base로 복귀하여 측정
make benchmark VARIANT=base
```

측정 없이 배포하려면 이미지를 빌드·로드한 뒤 해당 매니페스트만 적용합니다.

```sh
make build-image load-image VARIANT=enhanced-batch
./scripts/local-k8s.sh kubectl apply -f k8s/llama-enhanced-batch/
./scripts/local-k8s.sh kubectl rollout status deployment/llama-base --timeout=300s
```

캐시 버전은 위 명령의 `enhanced-batch`를 `enhanced-cache`로 바꿉니다. CPU·메모리 requests/limits는 base와 동일합니다. 공통 부하 설정과 결과 해석은 [AIPerf 가이드](aiperf.md)를 참고하세요.

## Continuous batching

[배칭 작업자](../src/enhanced/batch/batching.py)는 하나의 native context를 소유합니다. 요청마다 sequence ID, sampler, 생성 토큰, UTF-8 스트림 디코더를 분리합니다. 디코딩 중인 요청의 토큰을 먼저 배치에 넣고, 남는 공간에 새 프롬프트 조각을 배치합니다. 완료·취소된 요청의 KV를 제거하고 대기 요청에 슬롯을 할당합니다.

HTTP 작업자 스레드는 스케줄러의 결과를 기다립니다. 모델과 토크나이저는 배칭 작업자만 접근합니다. native decode 실패 시 대기 중인 호출을 오류로 종료하고 health/readiness를 실패로 반환합니다.

| CLI 옵션 | 용도 |
| --- | --- |
| `--max-parallel` | 활성 요청 슬롯 수. `--n-batch` 이하여야 함 |
| `--prefill-chunk` | 요청당 한 스케줄링 단계에서 처리하는 입력 토큰 상한 |
| `--n-batch` | 모든 요청을 합쳐 native decode에 제출하는 토큰 상한 |
| `--n-ubatch` | native 계산의 물리 배치 상한 |
| `--n-threads-batch` | prefill 및 다중 토큰 decode 스레드 수. 생략하면 `--n-threads` 값 사용 |
| `--n-ctx` | 요청 하나의 입력·출력 합계 제한 |

native KV 공간은 `n_ctx × max_parallel`을 기준으로 할당하며, 라이브러리의 정렬 때문에 실제 크기는 늘어날 수 있습니다. 배칭 버전은 요청 간 prefix 캐시를 유지하지 않습니다. 기본값은 `PYTHONPATH=src python -m enhanced.batch.server --help`, 배포값은 [Deployment](../k8s/llama-enhanced-batch/deployment.yaml)를 참고하세요.

## RAM·디스크 계층형 캐시

[캐시 엔진](../src/enhanced/cache/engine.py)은 base의 직렬 생성 경로에 prefix 조회·복원을 추가합니다. 입력 prefill 이후 첫 토큰을 샘플링한 시점에 입력의 native sequence KV만 저장합니다. Python scores 배열과 생성 응답은 저장하지 않습니다.

조회는 토큰 ID의 최장 공통 prefix를 찾습니다. 현재 native context보다 더 긴 prefix를 재사용할 수 있을 때 복원합니다. 상태 복원 후 새 suffix를 계산하며, 입력 전체가 일치하면 마지막 입력 토큰을 다시 계산해 logits를 갱신합니다.

1. RAM hit는 해당 항목의 LRU 순서를 갱신합니다.
2. RAM 한도를 넘으면 오래된 항목을 디스크로 내립니다.
3. 디스크 hit는 체크섬 검증 후 RAM으로 올립니다. RAM보다 큰 항목은 디스크에 유지합니다.
4. 디스크 한도를 넘으면 디스크 LRU 항목을 제거합니다. 정상 종료 시 남은 RAM 항목도 저장합니다.

디스크 쓰기는 동기식이며 임시 파일, fsync, atomic rename을 사용합니다. 프로세스 강제 종료 전 RAM에만 있던 항목은 유실될 수 있습니다. 손상된 항목은 버리고 재계산합니다. 모델 파일, native 라이브러리, 패키지 버전, 컨텍스트 크기와 아키텍처로 namespace를 구분하며, namespace별 단일 writer 잠금을 사용합니다.

| CLI 옵션 | 용도 |
| --- | --- |
| `--cache-dir` | 캐시 저장 루트 |
| `--cache-ram-mib` | native 상태와 토큰 ID의 RAM 예산. 0은 RAM 계층 비활성화 |
| `--cache-disk-mib` | namespace별 디스크 파일 예산. 0은 디스크 계층 비활성화 |
| `--cache-min-prefix` | 저장·복원을 허용하는 최소 공통 prefix 토큰 수 |

RAM 예산에는 Python 인덱스·컨테이너와 복원 중 임시 버퍼가 포함되지 않습니다. 디스크 예산은 namespace별이며 이전 모델 namespace는 자동 삭제하지 않습니다. 인덱스는 메모리에서 선형 탐색합니다. 기본값은 `PYTHONPATH=src python -m enhanced.cache.server --help`를 참고하세요.

[캐시 Deployment](../k8s/llama-enhanced-cache/deployment.yaml)는 `/cache`에 [PVC](../k8s/llama-enhanced-cache/cache.yaml)를 마운트합니다. 다른 구현으로 전환하거나 추론 Pod를 재시작해도 PVC는 유지됩니다. 클러스터의 기본 StorageClass가 필요합니다.

## 측정 조건

배칭은 동시성별 전체 처리량과 TTFT·ITL p95를 함께 비교합니다. 캐시는 신규 입력, 반복 입력, 공통 prefix 입력을 구분합니다. 기존 AIPerf의 짧은 입력 집합은 RAM에 모두 들어갈 수 있으므로 디스크 경로를 측정할 때 RAM 예산을 낮추거나 입력 집합을 늘립니다.

캐시 버전의 Pod 재시작은 디스크 캐시를 비우지 않습니다. `make benchmark VARIANT=enhanced-cache CACHE_POLICY=clear-per-concurrency`는 첫 조건을 포함해 각 동시성의 워밍업 전에 PVC cache를 삭제합니다. 기본값은 cache 보존입니다. 초기화 순서와 결과 기록은 [AIPerf 가이드](aiperf.md#동시성별-pvc-cache-초기화)를 참고하세요.

## 검증

모델 없는 검증에는 base API 테스트와 같은 `fastapi`, `httpx` 환경을 사용합니다.

```sh
python -m unittest discover -s tests -p 'test_enhanced_*.py' -v
```

native 통합 검증에는 각 이미지와 같은 `llama-cpp-python` 버전 및 실제 GGUF가 필요합니다.

```sh
TEST_MODEL_PATH="$PWD/.models/qwen2.5-0.5b/qwen2.5-0.5b-instruct-q4_k_m.gguf" \
  python -m unittest discover -s tests -p 'test_enhanced_native.py' -v
```

배칭의 다중 요청 decode·취소·슬롯 재사용, 캐시의 spill·promotion·손상 복구·재시작, HTTP/SSE 호환성을 검증합니다.
