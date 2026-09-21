# Inference engine test (CPU)

단일 노드 kind에서 SmolLM2를 Transformers + PyTorch CPU로 실행하고, base, batch, prefix KV cache 구현의 성능을 AIPerf로 비교합니다. llama.cpp 구현도 별도로 선택할 수 있습니다.

## 준비 사항

- Docker가 실행 중인 호스트, POSIX 셸, Python 3.10 이상과 `make`
- 도구 설치 시 `curl` 또는 `wget`, 체크섬 검증용 `sha256sum` 또는 `shasum`과 인터넷 연결
- 모델 다운로드 시 `curl`과 인터넷 연결
- 추론 실행 전 [CPU, 메모리, 디스크 요구사항](docs/guides/requirements.md#cpu-메모리와-디스크)에 맞는 Docker 자원 확보

## 빠른 시작

저장소 루트에서 실행합니다. 모델 다운로드와 검증, 클러스터 생성, 이미지 빌드와 로드, 배포와 반복 측정을 자동 수행합니다.

### make 사용

```sh
make install
make benchmark-suite
```

기본 실험은 세 구현마다 동시성 `1,2,4,8`을 3회 반복합니다. 결과는 `docs/reports/transformers/benchmark-suite-*/summary.md`에 저장됩니다. 측정값, 캐시 정책과 실행 시간은 [벤치마크 가이드](docs/guides/benchmark.md)을 참고하세요. `make benchmark`와 `make benchmark-suite`는 필요 시 이미지 빌드부터 kind 로드, 배포와 AIPerf 실행까지 포함해 자동 수행합니다.

단일 sweep만 측정하려면 `VARIANT`로 구현을 선택합니다.

```sh
make benchmark # transformers-base (기본값)
make benchmark VARIANT=transformers-enhanced-batch
make benchmark VARIANT=transformers-enhanced-cache
```

llama.cpp는 `make benchmark VARIANT=base-llamacpp`로 선택하며, `enhanced-batch-llamacpp`와 `enhanced-cache-llamacpp`도 같은 방식으로 실행합니다. 보고서는 `docs/reports/llamacpp/`와 `docs/reports/transformers/`에 backend별로 저장됩니다.

### 스크립트 직접 실행

`make` 명령은 `scripts/` 실행 파일을 감싼 형태입니다. 동일하게 직접 실행할 수 있습니다. `VARIANT`는 `make` 전용 편의 변수이며, 스크립트에서는 이미지와 매니페스트를 직접 지정합니다.

```sh
./scripts/local-k8s.sh install # make install과 동일
./scripts/local-k8s.sh up      # make up과 동일
python3 scripts/run-benchmark-suite.py # make benchmark-suite와 동일, 기본 backend는 transformers
python3 scripts/run-benchmark-suite.py --backend llamacpp # llama.cpp 전체 반복

./scripts/run-benchmark.py # make benchmark와 동일
./scripts/run-benchmark.py --help # 전체 옵션 확인
# enhanced 예시
./scripts/run-benchmark.py --image local/transformers-enhanced-batch:0.1.0 --manifests k8s/transformers-enhanced-batch
./scripts/run-benchmark.py --image local/transformers-enhanced-cache:0.1.0 --manifests k8s/transformers-enhanced-cache --cache-policy clear-per-concurrency
```

| 목적 | make | 스크립트 직접 실행 |
| --- | --- | --- |
| 도구 설치 | `make install` | `./scripts/local-k8s.sh install` |
| 클러스터 생성/삭제 | `make up`, `make down` | `./scripts/local-k8s.sh up`, `./scripts/local-k8s.sh down` |
| 클러스터 상태 | `make status`, `make test` | `./scripts/local-k8s.sh status`, `./scripts/local-k8s.sh test` |
| 단일 sweep | `make benchmark` | `./scripts/run-benchmark.py` |
| 전체 반복 | `make benchmark-suite` | `python3 scripts/run-benchmark-suite.py` |

서버만 실행하는 방법은 [추론 엔진 가이드](docs/guides/inference-engine.md), llama.cpp 배포는 같은 문서의 [llama.cpp 절](docs/guides/inference-engine.md#llamacpp)를 참고하세요. 사용 후 `make down` 또는 `./scripts/local-k8s.sh down`으로 클러스터와 노드 내부 PVC 데이터를 삭제합니다. 호스트 모델과 수집된 보고서는 유지됩니다.

상세 내용은 [클러스터 사용](docs/guides/local-k8s.md), [모델 관리](docs/guides/models.md), [AIPerf 설정](docs/guides/aiperf.md), [벤치마크 실행과 결과 분석](docs/guides/benchmark.md), [품질 체크](docs/guides/quality-check.md), [멀티 노드 서비스 안정성 테스트](docs/guides/availability-test.md), [CPU HPA 테스트](docs/guides/hpa-test.md), [테스트 결과](docs/reports/README.md)를 참고하세요.
