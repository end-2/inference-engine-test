# 멀티 노드 서비스 가용성 테스트

Manifest 적용과 ConfigMap 변경 방법은 [manifest 관리](manifests.md)를 참고합니다.

기본 절차는 Transformers CPU를 사용합니다. llama.cpp는 [엔진별 변경 사항](#llamacpp)을 적용하며 관찰과 판정 기준은 동일합니다. 추론 구현과 API는 [추론 엔진 가이드](inference-engine.md)를 참고하세요.

SmolLM2의 Transformers CPU base 서버 두 개에 AIPerf 부하를 보내면서 engine worker 하나를 pause 또는 SIGKILL합니다. 노드 상태, 대체 Pod와 Service endpoint 복구, 실제 요청 결과를 수집합니다.

## 구성

| 항목 | 설정 |
| --- | --- |
| kind | control-plane 1개, monitor worker 1개, engine worker 2개 |
| 모델 | 고정된 SmolLM2-135M-Instruct FP32 snapshot, 서버와 AIPerf가 같은 tokenizer 사용 |
| 서버 | `transformers-base-metric`, 자원과 스레드 설정은 배포 매니페스트에서 관리 |
| 배치 | engine worker에 분산, 장애 후 살아 있는 worker에 대체 Pod 허용 |
| AIPerf | monitor worker, concurrency 4, worker 1, timeout 30초, 매 요청 새 연결 |
| 입력과 출력 | `64,32:50;256,64:50`, 입력 16개, seed 42, sequential, `ignore_eos:true` |
| 관측 | Prometheus 5초 scrape, kube-state-metrics, Grafana, `/metrics`의 `transformers_*` 지표 |

모든 측정 컨테이너는 CPU와 메모리 `requests=limits`를 사용합니다. 자원 요청량은 배포 매니페스트에서 확인하며, 장애 후 남은 engine worker에 대체 Pod를 배치할 여유가 필요합니다. monitor와 Kubernetes 시스템 자원을 추가로 확보하고 다른 부하 실험은 중지합니다. kind 노드는 같은 Docker 호스트 자원을 공유합니다.

설정 원본은 [availability 매니페스트](../../k8s/availability-test-transformers/), [멀티 노드 토폴로지](../../config/cluster/kind-multi-node.yaml), [모델 snapshot](../../config/models/smollm2-135m-transformers.env)입니다.

## 준비

Docker, POSIX 셸, Python 3.10 이상이 필요합니다. 저장소 루트에서 실행합니다.

```sh
export CLUSTER_NAME=transformers-tests
export PATH="$PWD/.bin:$PATH"
./scripts/local-k8s.sh install
./scripts/download-transformers-model.sh
KIND_CONFIG=config/cluster/kind-multi-node.yaml ./scripts/local-k8s.sh up
./scripts/build-inference-images.sh transformers-base-metric
./scripts/load-inference-images.sh transformers-base-metric
./scripts/build-benchmark-images.sh
./scripts/load-benchmark-images.sh
```

기본 `local-k8s` 단일 노드 클러스터와 별도로 만듭니다. `up`은 기존 클러스터의 토폴로지를 바꾸지 않습니다. 같은 이름의 단일 노드 클러스터가 있으면 새 이름을 지정합니다. availability runner는 engine worker 2개, monitor worker 1개를 확인하며, 격리 kubeconfig를 사용합니다.

## 배포와 실행

같은 클러스터에서 HPA 테스트를 실행했다면 먼저 결과를 내보내고 `./scripts/local-k8s.sh kubectl delete -f k8s/hpa-test-transformers`로 정리합니다. 이 명령은 해당 테스트 PVC도 삭제합니다.

```sh
./scripts/local-k8s.sh kubectl apply -f k8s/availability-test-transformers/namespace.yaml
./scripts/local-k8s.sh kubectl apply -f k8s/availability-test-transformers
for deployment in transformers-base-metric prometheus kube-state-metrics grafana; do
  ./scripts/local-k8s.sh kubectl -n availability-test-transformers rollout status "deployment/$deployment" --timeout=300s
done
./scripts/local-k8s.sh kubectl -n availability-test-transformers wait --for=condition=Ready pod/aiperf-results --timeout=120s

python3 scripts/run-availability-test-transformers.py --scenario pause-60s --dry-run
python3 scripts/run-availability-test-transformers.py --scenario pause-60s
python3 scripts/run-availability-test-transformers.py --scenario sigkill-60s
```

`--scenario`는 `pause-60s`, `sigkill-60s`, `pause-300s`, `sigkill-300s`를 지원합니다. 숫자는 장애 지속 시간이 아닌 Pod의 `not-ready`와 `unreachable` NoExecute toleration입니다. 네 조건을 비교하려면 위 명령의 scenario를 바꾸어 순차 실행합니다.

각 실행은 Pod를 새로 분산 배치하고 90초 워밍업, 150초 정상 구간, 노드 장애, 대체 Pod Ready 후 90초, 노드 복구 후 90초를 관찰합니다. 소요 시간은 실행 환경과 복구 상태에 따라 달라지며 실제 시각은 `run.json`에 기록합니다.

`--cluster` 기본값은 `CLUSTER_NAME` 또는 `transformers-tests`입니다. `--victim-node`를 생략하면 첫 engine worker를 선택합니다. runner는 Docker kind cluster와 worker 소속을 검증하고 control-plane에 장애를 주지 않습니다. SIGKILL 동안 Docker 자동 재시작을 끄고 원래 정책을 복원합니다. 실패와 Ctrl+C에도 노드 복구와 AIPerf 중지를 시도합니다. availability와 HPA runner는 같은 cluster lock을 사용하므로 동시에 실행되지 않습니다.

추론 Pod는 hostname 기준 preferred pod anti-affinity로 분산하며 장애 후 남은 worker에 함께 배치될 수 있습니다. 노드 복귀만으로 자동 재분산되지는 않아 runner가 종료 시 Pod를 다시 생성합니다. 프로세스 SIGKILL이나 호스트 종료로 복구가 실행되지 않으면 `run.json`의 대상 노드와 원래 Docker 정책을 확인해 수동 복구합니다.

## 결과와 관찰

원본은 `reports/transformers/availability-<scenario>-<UTC>/`에 저장합니다. `run.json`, `actions.jsonl`, Kubernetes와 Docker 관측, 서버 로그, `aiperf/` 요청별 JSONL과 집계, Prometheus 시계열을 포함합니다. 요약 보고서는 [Transformers 결과 목록](../reports/transformers/README.md)에 있습니다.

Prometheus, Grafana와 AIPerf 결과는 monitor 노드의 PVC를 사용하며 기본 StorageClass와 모니터링 이미지 다운로드가 필요합니다. 클러스터 삭제 시 PVC 데이터도 사라집니다. 보고서와 그래프는 runner가 자동 생성하지 않습니다. 실패율, timeout, TTFT와 ITL은 AIPerf 요청별 결과로 판단합니다. 서버에 도착하지 않은 요청은 서버 지표에 포함되지 않습니다.

`status=complete`는 장애 주입, 대체 Pod, 노드 복구와 수집 절차의 완료를 뜻합니다. 장애 중 timeout 등 요청 오류가 발생할 수 있으므로 AIPerf 성공률은 별도로 확인합니다. 서버 HTTP 200 중 SSE 오류는 `transformers_requests_total{outcome="error"}`로 기록합니다. `/healthz`, `/readyz`, `/metrics`는 요청 지표에서 제외합니다.

```sh
./scripts/local-k8s.sh kubectl -n availability-test-transformers get pods -o wide
./scripts/local-k8s.sh kubectl -n availability-test-transformers port-forward service/grafana 3000:3000
```

Grafana의 `availability-test-transformers` 대시보드를 사용합니다. renderer는 기본 replicas 0이며 측정이 끝난 뒤에만 실행합니다. 종료 후 부하 Pod는 0개이고, 추론 Pod 2개는 두 worker로 다시 분산됩니다.

| 파일과 디렉토리 | 수집 데이터 |
| --- | --- |
| `run.json`, `actions.jsonl` | 실험 설정, 장애, 복구 시각, 실행 상태 |
| `aiperf/` | 요청별 JSONL과 AIPerf 자체 집계 결과 |
| `prometheus/`, `metric-range.json` | 요청, 지연, TTFT, 노드, Pod, EndpointSlice 시계열과 조회 범위 |
| `kubernetes-snapshots.jsonl.gz`, `state-changes.jsonl` | Kubernetes 객체 표본과 상태 변화 |
| `resources.jsonl.gz` | kubelet CPU와 메모리 표본 |
| `docker-events.jsonl`, `docker-states.jsonl` | 대상 노드 컨테이너 이벤트와 상태 |
| `*.log`, 단계별 `*.txt`, `*-docker.json` | 클라이언트, 서버, controller 로그와 단계별 상태 |

## 검증과 정리

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_transformers_metric.py'
python3 -m unittest discover -s tests -p 'test_availability_runner_transformers.py'
sh tests/test-hpa-manifests-transformers.sh
# 원본 결과를 수집한 뒤 테스트 namespace와 PVC 정리
./scripts/local-k8s.sh kubectl delete -f k8s/availability-test-transformers
```

metric 단위 테스트에는 Transformers 런타임과 `src/transformers_cpu/base_metric/requirements.txt`의 의존성이 필요합니다. 클러스터를 삭제하려면 같은 `CLUSTER_NAME`으로 `./scripts/local-k8s.sh down`을 실행합니다. 호스트에 수집된 결과와 모델은 유지됩니다.

## llama.cpp

위 절차에서 다음 값을 바꿉니다. 모든 터미널에서 선택한 `CLUSTER_NAME`을 동일하게 사용합니다.

| 항목 | Transformers 기본값 | llama.cpp |
| --- | --- | --- |
| 클러스터 예시 | `transformers-tests` | `availability-test-llamacpp` |
| 모델 준비 | `./scripts/download-transformers-model.sh` | `./scripts/download-model-llamacpp.sh`와 `./scripts/download-tokenizer-llamacpp.sh` |
| 추론 이미지와 Deployment | `transformers-base-metric` | `base-metric-llamacpp` |
| 매니페스트 | `k8s/availability-test-transformers` | `k8s/availability-test-llamacpp` |
| namespace와 대시보드 | `availability-test-transformers` | `availability-test-llamacpp` |
| runner | `scripts/run-availability-test-transformers.py` | `scripts/run-availability-test-llamacpp.py` |
| 결과 루트 | `reports/transformers/` | `reports/llamacpp/` |

모델은 [Qwen GGUF 설정](../../config/models/qwen2.5-0.5b-gguf-llamacpp.env)을 사용하며 서버와 AIPerf의 모델 및 토크나이저를 맞춥니다. 자원과 부하 설정은 [llama.cpp 매니페스트](../../k8s/availability-test-llamacpp/)를 기준으로 합니다. 같은 클러스터의 다른 테스트를 정리할 때도 해당 엔진의 namespace와 매니페스트를 선택합니다.

재실행 전에 AIPerf와 renderer를 중지합니다. 각 시나리오는 독립 실행하며 순서에 의존하지 않습니다.

```sh
export CLUSTER_NAME=availability-test-llamacpp
./scripts/local-k8s.sh kubectl -n availability-test-llamacpp scale deployment/aiperf --replicas=0
./scripts/local-k8s.sh kubectl -n availability-test-llamacpp wait --for=delete pod -l app=aiperf --timeout=150s
./scripts/local-k8s.sh kubectl -n availability-test-llamacpp scale deployment/grafana-renderer --replicas=0
python3 scripts/run-availability-test-llamacpp.py --scenario pause-60s --dry-run
python3 scripts/run-availability-test-llamacpp.py --scenario pause-60s
```

llama.cpp metric 검증은 다음 명령을 사용합니다.

```sh
python -m pip install -r src/llamacpp/base_metric/requirements.txt fastapi httpx
python -m unittest discover -s tests -p 'test_base_metric_llamacpp.py'
```
