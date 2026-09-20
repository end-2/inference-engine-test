# Kubernetes 서비스 안정성 테스트

engine worker 하나가 응답하지 않을 때 요청 실패, 지연, EndpointSlice 변경과 Pod 복구를 관찰합니다. [매니페스트](../k8s/availability-test/kustomization.yaml)는 `availability-test` 네임스페이스에 설치합니다. API 요청 형식은 [공통 API 가이드](llama-api.md)를 따릅니다.

같은 관측 구성으로 CPU 부하 변화에 따른 replica 증가·축소를 확인하려면 [CPU HPA 테스트](hpa-test.md)를 사용합니다.

## 배치와 준비

| 노드 라벨 | 워크로드 |
| --- | --- |
| `workload=engine` — worker 2개 | `llama-base-metric` Deployment, replica 2 |
| `workload=monitor` — worker 1개 | AIPerf, Prometheus, Grafana, kube-state-metrics, AIPerf 결과 reader, Image Renderer(출력 시) |

추론 Pod는 hostname 기준 **preferred pod anti-affinity**로 서로 다른 노드를 우선합니다. 필수 제약이 아니므로 장애 후 남은 engine 노드에 두 Pod가 배치될 수 있습니다. 정상 상태의 분산 여부는 실험 전에 확인합니다. 노드 복귀만으로 이미 배치된 Pod가 자동 재분산되지는 않습니다.

모든 테스트 컨테이너는 CPU·메모리 `requests=limits`를 사용합니다. 추론 Pod별 2 CPU/2 GiB, monitor 워크로드 합계 1.86 CPU/1952 MiB와 시스템 여유분이 필요합니다. 장애 후 replica 2 복구까지 확인하려면 engine 노드 하나에 추론용 4 CPU/4 GiB가 들어갈 여유가 있어야 합니다. kind 노드들은 같은 Docker 호스트 자원을 공유하므로 실제 호스트 장애 격리나 독립적인 물리 노드 성능을 재현하지 않습니다.

아래는 기존 클러스터와 분리된 이름으로 실행하는 예입니다. 모든 터미널에서 같은 `CLUSTER_NAME`을 사용합니다. 기존 클러스터 이름을 사용할 경우 `up`은 토폴로지를 변경하지 않으므로 [클러스터 재생성 안내](local-k8s.md)를 따릅니다.

```sh
export CLUSTER_NAME=availability-test
export PATH="$PWD/.bin:$PATH"
./scripts/download-model.sh
./scripts/download-tokenizer.sh
KIND_CONFIG=config/cluster/kind-multi-node.yaml ./scripts/local-k8s.sh up
./scripts/build-inference-images.sh base-metric
./scripts/load-inference-images.sh base-metric
./scripts/build-benchmark-images.sh
./scripts/load-benchmark-images.sh
./scripts/local-k8s.sh kubectl apply -k k8s/availability-test
./scripts/local-k8s.sh kubectl -n availability-test rollout status deployment/llama-base-metric --timeout=300s
./scripts/local-k8s.sh kubectl -n availability-test rollout status deployment/prometheus --timeout=300s
./scripts/local-k8s.sh kubectl -n availability-test rollout status deployment/kube-state-metrics --timeout=300s
./scripts/local-k8s.sh kubectl -n availability-test rollout status deployment/grafana --timeout=300s
./scripts/local-k8s.sh kubectl get nodes -L workload
./scripts/local-k8s.sh kubectl -n availability-test get pods -o wide
```

로컬 이미지 태그와 자원 설정은 각 매니페스트가 기준입니다. 모델·토크나이저는 기존 `/models` 읽기 전용 마운트를 사용합니다. 모니터링 이미지 다운로드와 kind의 `standard` StorageClass가 필요합니다. Prometheus·Grafana 데이터와 AIPerf 결과는 monitor 노드의 PVC에 보존되며 클러스터 삭제 시 사라집니다.

## 네 가지 실험 재실행

Python 3.10 이상, Docker CLI와 위 배포가 필요합니다. 아래 명령은 선택한 kind 클러스터의 추론 Pod를 새로 만들고 engine 노드 하나에 실제 장애를 주입합니다. 각 명령은 독립 실행이며 순서에 의존하지 않습니다.

```sh
export CLUSTER_NAME=local-k8s
./scripts/local-k8s.sh kubectl -n availability-test scale deployment/aiperf --replicas=0
./scripts/local-k8s.sh kubectl -n availability-test wait --for=delete pod -l app=aiperf --timeout=150s
./scripts/local-k8s.sh kubectl -n availability-test scale deployment/grafana-renderer --replicas=0

# 읽기 전용 사전 검사
python3 scripts/run-availability-test.py --scenario pause-300s --dry-run

# 아래에서 원하는 실험 한 개 실행
python3 scripts/run-availability-test.py --scenario pause-300s
python3 scripts/run-availability-test.py --scenario sigkill-300s
python3 scripts/run-availability-test.py --scenario pause-60s
python3 scripts/run-availability-test.py --scenario sigkill-60s
```

`--cluster`로 클러스터 이름을, `--victim-node`로 engine worker를 지정할 수 있습니다. 스크립트는 해당 클러스터의 격리 kubeconfig와 Docker kind 라벨을 확인합니다. 동일 클러스터에 대한 스크립트 중복 실행은 lock으로 막습니다.

매 실행에서 `not-ready`와 `unreachable`의 NoExecute toleration을 선택한 값으로 명시하고, 새 추론 Pod가 노드별 1개인지 확인합니다. 새 AIPerf 실행으로 90초 예열, 150초 정상 관찰, 장애 주입, 대체 Pod Ready 후 90초, 노드 Ready 회복 후 90초를 수집합니다. `sigkill`은 Docker 자동 재시작을 일시 해제한 뒤 `SIGKILL`을 보냅니다. 정상 실행은 준비·데이터 추출 시간을 제외하고 60초 조건 약 9분, 300초 조건 약 13분이 걸립니다.

관찰이 끝나면 AIPerf를 중지해 결과를 저장하고 PVC에서 복사합니다. `reports/availability-<시나리오>-<UTC>/`에 다음 데이터를 저장합니다.

| 파일·디렉토리 | 수집 데이터 |
| --- | --- |
| `run.json`, `actions.jsonl` | 실험 설정, 장애·복구 시각, 실행 상태 |
| `aiperf/` | 요청별 JSONL과 AIPerf 자체 집계 결과 |
| `prometheus/`, `metric-range.json` | 요청·지연·TTFT·노드·Pod·EndpointSlice 시계열과 조회 범위 |
| `kubernetes-snapshots.jsonl.gz`, `state-changes.jsonl` | Kubernetes 객체 표본과 상태 변화 |
| `resources.jsonl.gz` | kubelet CPU·메모리 표본 |
| `docker-events.jsonl`, `docker-states.jsonl` | 대상 노드 컨테이너 이벤트와 상태 |
| `*.log`, 단계별 `*.txt`·`*-docker.json` | 클라이언트·서버·controller 로그와 단계별 상태 |

각 실행은 새 디렉토리를 사용하며 `run.json`의 `status=complete`를 확인합니다. 실행은 `scripts/run-availability-test.py`, 객체·자원 수집은 `scripts/availability_test/observe.py`, Prometheus 추출은 `scripts/availability_test/metrics.py`가 담당합니다. 보고서와 그래프는 자동 생성하지 않습니다.

완료 후 모든 노드를 복구하고 추론 Pod를 engine 노드별 1개로 재생성합니다. AIPerf는 replica 0, toleration은 선택한 값을 유지합니다. renderer는 사전 검사에서 replica 0을 확인하며 실행 중 시작하지 않습니다. 예외·Ctrl+C·SIGTERM 때는 노드 복구와 Docker 재시작 정책 복원을 시도하고 `status=failed`를 기록합니다. 실행 프로세스 자체의 SIGKILL이나 호스트 종료 때는 cleanup이 실행될 수 없으므로 `run.json`의 대상 노드와 원래 정책을 확인해 복구합니다.

기본 manifest는 admission 기본 toleration 300초를 사용합니다. 60초만 수동 적용하려면 `scenarios/toleration-60s.yaml`을 `kubectl patch --type=merge --patch-file`로 전달합니다. 이 파일은 독립적인 Kubernetes 리소스가 아닌 Deployment patch입니다. eviction 대기는 Pod의 NoExecute toleration이고 노드 감지 시간과 별개입니다. 설정 의미는 [Kubernetes taint/toleration 문서](https://kubernetes.io/docs/concepts/scheduling-eviction/taint-and-toleration/)와 [controller 노드 감지 옵션](https://kubernetes.io/docs/reference/command-line-tools-reference/kube-controller-manager/)에서 확인할 수 있습니다.

## 지속 부하와 지표

[AIPerf 설정](../k8s/availability-test/aiperf.yaml)은 Service `http://llama-base-metric:8000`에 동시성 **4**로 스트리밍 요청을 계속 발행합니다. 요청 제한 시간은 30초이며 실패 후에도 다음 요청을 발행합니다. 매 요청 새 연결을 사용해 Service의 연결 단위 분산을 측정합니다. keep-alive 고정 연결을 사용하는 클라이언트와는 다른 조건입니다.

[반복 실행 스크립트](../k8s/availability-test/aiperf/run.sh)는 `RUN_SECONDS`마다 집계를 저장하고 다음 실행을 시작합니다. 기본 구간은 1시간이며 요청 개수 제한은 없습니다. 구간 경계에는 진행 요청 정리, 결과 저장, 초기화에 따른 짧은 부하 공백이 있으므로 장애 실험은 한 구간 안에서 수행합니다. 시작 시 추론 Pod가 준비되기 전의 실패도 기록됩니다. AIPerf Pod의 Running 상태만으로 부하 발생을 판단하지 말고 로그와 요청 카운터 증가를 확인합니다.

`src/base-metric`은 기존 base 추론 엔진과 API를 재사용하고 `/metrics`를 추가합니다. Prometheus는 EndpointSlice로 개별 Pod 주소를 발견해 5초 간격으로 수집합니다. Service 주소 하나를 번갈아 scrape하지 않으므로 Pod별 카운터가 섞이지 않습니다. unready endpoint도 삭제되기 전까지 수집 대상으로 남깁니다.

| 지표 | 의미 |
| --- | --- |
| `llama_requests_total{status_code,outcome}` | 완료 요청. `success`, `error`, `disconnected`를 구분하고 HTTP 200 SSE 오류도 `error`로 집계 |
| `llama_requests_in_flight` | 큐 대기와 스트리밍을 포함한 처리 중 요청 |
| `llama_request_duration_seconds` | 요청 도착부터 응답 마지막 body 전송까지의 서버 지연 histogram |
| `llama_time_to_first_token_seconds` | 큐 대기를 포함한 첫 비어 있지 않은 스트리밍 콘텐츠 전송까지의 histogram |
| `llama_tokens_total{kind}` | 엔진이 반환한 prompt/completion 토큰 수. 클라이언트 전달 성공과 별개 |
| `up{job="llama-base-metric"}` | 각 Pod의 scrape 도달 가능 여부. 엔드포인트 삭제 후 해당 시계열은 사라짐 |
| `availability:service_ready_endpoints` / `availability:service_unready_endpoints` | Service별 ready/unready endpoint 개수. Service는 존재하지만 endpoint가 없으면 0 |
| `kube_endpointslice_endpoints` | endpoint별 주소·노드·대상 Pod·ready/serving/terminating 조건 |
| `kube_node_status_condition` / `kube_deployment_status_replicas_available` | 노드 Ready와 Deployment 가용 replica 수 |

HTTP 지표는 chat POST만 집계하며 probe와 `/metrics` 호출은 제외합니다. 노드가 멈추면 마지막 scrape 이후 서버 카운터를 회수할 수 없고, 서버에 도착하지 못한 요청은 서버 지표에 없습니다. **사용자 관점의 실패율·timeout·TTFT·ITL은 AIPerf 요청별 결과를 기준**으로 Prometheus 상태 변화와 비교합니다. 서버 TTFT는 전송 시점까지, AIPerf TTFT는 클라이언트 수신 시점까지 측정합니다.

kube-state-metrics는 테스트 네임스페이스의 **모든 Service EndpointSlice**를 수집하므로 `llama-base-metric`과 `prometheus` Service 모두 관찰됩니다. Prometheus 자체의 EndpointSlice 상태와 추론 Service의 상태를 별도로 볼 수 있습니다.

## 관찰과 장애 주입

각 명령은 별도 터미널에서 실행합니다.

```sh
export CLUSTER_NAME=availability-test
./scripts/local-k8s.sh kubectl -n availability-test port-forward service/grafana 3000:3000
```

`http://localhost:3000`에 익명 Viewer로 접속하면 준비된 대시보드가 열립니다. Service는 ClusterIP이며 기본 사용 경로는 로컬 port-forward입니다.

```sh
export CLUSTER_NAME=availability-test
./scripts/local-k8s.sh kubectl -n availability-test port-forward service/prometheus 9090:9090
```

Prometheus에서 `up`과 아래 식을 확인합니다. 대시보드는 엔진 노드 Ready, Pod별 scrape·in-flight, 요청 처리량·지연·TTFT·토큰 처리량, Service별 EndpointSlice 상태를 제공합니다.

```promql
availability:service_ready_endpoints{service="llama-base-metric"}
availability:service_ready_endpoints{service="prometheus"}
```

원본 변경 이벤트를 보관하려면 장애 전부터 watch를 실행합니다. 첫 출력에는 현재 객체 목록이 포함됩니다. 실험 종료 시 각 watch를 Ctrl-C로 끝냅니다. EndpointSlice는 API 서버의 인지 상태이며 실시간 네트워크 도달 가능성과 같지 않습니다.

```sh
export CLUSTER_NAME=availability-test
mkdir -p reports/availability
./scripts/local-k8s.sh kubectl -n availability-test get endpointslices \
  --watch --output-watch-events -o json > reports/availability/endpointslices.watch.json
# 다른 터미널
./scripts/local-k8s.sh kubectl get nodes \
  --watch --output-watch-events -o json > reports/availability/nodes.watch.json
# 다른 터미널
./scripts/local-k8s.sh kubectl -n availability-test logs -f deployment/aiperf --timestamps \
  > reports/availability/aiperf.log
```

1. 추론 Pod 두 개가 서로 다른 engine 노드에 있고 ready endpoint가 2인지 확인합니다. 요청 카운터가 증가하는 정상 구간을 1분 이상 수집합니다.
2. 아래 명령으로 engine 노드 하나를 pause합니다. kind 노드의 모든 프로세스를 정지하므로 drain이나 정상 종료 없이 노드가 응답하지 않는 상황을 재현합니다.
3. 요청 실패·timeout 발생, Pod scrape 실패, 노드 Ready 변경, ready endpoint 감소, 남은 Pod의 부하 증가를 같은 시간축에서 비교합니다. 노드 감지와 기본 NoExecute toleration 대기 때문에 endpoint 제외와 대체 Pod 생성은 즉시 일어나지 않습니다. 기본 manifest는 300초 toleration을 사용하며 재실행 스크립트는 선택한 값을 명시합니다.
4. 대체 Pod 준비와 ready endpoint 회복을 관찰한 뒤 노드를 unpause합니다. 남은 노드 자원이 부족하면 대체 Pod는 Pending으로 남습니다.

```sh
export CLUSTER_NAME=availability-test
ENGINE_NODE=$(./scripts/local-k8s.sh kubectl get nodes -l workload=engine \
  -o jsonpath='{.items[0].metadata.name}')
printf '%s pause %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$ENGINE_NODE" \
  >> reports/availability/faults.log
docker pause "$ENGINE_NODE"

# 충분히 관찰한 뒤 같은 터미널에서 복구
docker unpause "$ENGINE_NODE"
printf '%s unpause %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$ENGINE_NODE" \
  >> reports/availability/faults.log
./scripts/local-k8s.sh kubectl wait --for=condition=Ready "node/$ENGINE_NODE" --timeout=180s
```

재실험 전에 부하를 멈추고 필요하면 추론 Deployment를 재시작해 두 노드 분산을 다시 확인합니다. 재시작 구간을 장애 측정 구간에 섞지 않습니다.

## 중단과 결과 추출

AIPerf를 scale 0으로 줄이면 runner가 SIGINT를 전달해 결과 저장을 요청합니다. Pod가 종료된 뒤 reader를 통해 PVC를 복사합니다. 반복 실행별 요청 JSONL, 집계 JSON/CSV, 5초 구간 집계와 로그가 `/results/<Pod>/<UTC>-<순번>/` 아래에 저장됩니다. 장시간 실행 시 결과 PVC 사용량을 확인하고 필요한 결과를 내보냅니다.

```sh
./scripts/local-k8s.sh kubectl -n availability-test scale deployment/aiperf --replicas=0
./scripts/local-k8s.sh kubectl -n availability-test wait --for=delete pod -l app=aiperf --timeout=150s
./scripts/local-k8s.sh kubectl -n availability-test wait --for=condition=Ready pod/aiperf-results --timeout=120s
./scripts/local-k8s.sh kubectl -n availability-test cp aiperf-results:/results reports/availability/aiperf
```

Prometheus port-forward를 유지한 상태에서 아래와 같이 필요한 시계열을 JSON으로 추출합니다. `START`와 `END`에는 `faults.log`를 포함한 측정 구간의 UTC 시각을 지정합니다. 같은 방식으로 `query`를 바꿔 요청 counter/histogram, 노드 상태, 원본 EndpointSlice 지표를 저장합니다.

```sh
START=2026-09-20T00:00:00Z
END=2026-09-20T00:15:00Z
curl -fsSG http://localhost:9090/api/v1/query_range \
  --data-urlencode 'query=availability:service_ready_endpoints{namespace="availability-test"}' \
  --data-urlencode "start=$START" --data-urlencode "end=$END" \
  --data-urlencode 'step=5s' > reports/availability/ready-endpoints.json
```

재개는 `scale deployment/aiperf --replicas=1`로 수행합니다. 결과 추출과 노드 unpause 후 `kubectl delete -k k8s/availability-test`로 워크로드·PVC를 정리하거나 `./scripts/local-k8s.sh down`으로 전용 클러스터를 삭제합니다.

## Grafana 패널 PNG 추출

[공식 Grafana Image Renderer](https://grafana.com/docs/grafana/latest/setup-grafana/image-rendering/)를 remote rendering 서비스로 연결합니다. 기존 플러그인 방식은 지원 종료되어 별도 [renderer Deployment](../k8s/availability-test/grafana-renderer.yaml)를 사용합니다. 기본 replica는 0이며 **부하 측정 종료 후** 실행합니다. 작은 패널을 순차 출력하는 로컬 구성으로 CPU 2/메모리 2 GiB를 추가 예약합니다. 큰 대시보드나 동시 렌더링은 공식 자원 권장량에 맞춰 조정합니다. 공유 인증 토큰은 로컬 테스트 전용 값입니다.

Grafana port-forward를 유지하고 측정 구간을 고정해 요청합니다. 패널 ID는 [대시보드 JSON](../k8s/availability-test/grafana/availability.json)이 기준이며 `2`는 Service ready endpoints, `8`은 TTFT p95, `10`은 가용 replica입니다.

```sh
./scripts/local-k8s.sh kubectl -n availability-test scale deployment/grafana-renderer --replicas=1
./scripts/local-k8s.sh kubectl -n availability-test rollout status deployment/grafana-renderer --timeout=180s
mkdir -p reports/availability/figures
START=2026-09-20T04:59:29.798Z
END=2026-09-20T05:11:10.660Z
curl --fail --show-error --silent --max-time 120 --get \
  http://localhost:3000/render/d-solo/availability-test/kubernetes-service-availability \
  --data-urlencode 'panelId=2' \
  --data-urlencode "from=$START" --data-urlencode "to=$END" \
  --data-urlencode 'tz=UTC' --data-urlencode 'timezone=utc' \
  --data-urlencode 'width=1400' --data-urlencode 'height=500' \
  --data-urlencode 'theme=light' --data-urlencode 'timeout=90' \
  --output reports/availability/figures/grafana-endpoints.png
./scripts/local-k8s.sh kubectl -n availability-test scale deployment/grafana-renderer --replicas=0
```

PNG는 Grafana `/render/d-solo`가 공식 렌더러에 위임해 생성합니다. Prometheus에 해당 구간 데이터가 남아 있어야 하며, 캡처 시간과 데이터 시간 범위를 별도로 기록합니다.

## 검증

```sh
python -m pip install -r src/base-metric/requirements.txt fastapi httpx
python -m unittest discover -s tests -p test_base_metric.py
./.bin/kubectl kustomize k8s/availability-test > /tmp/availability-test.yaml
./scripts/local-k8s.sh kubectl apply --dry-run=client -f /tmp/availability-test.yaml
docker run --rm --entrypoint promtool \
  -v "$PWD/k8s/availability-test/prometheus:/etc/prometheus:ro" \
  prom/prometheus:v3.5.0 check config /etc/prometheus/prometheus.yml
docker run --rm --entrypoint promtool \
  -v "$PWD/k8s/availability-test/prometheus:/etc/prometheus:ro" \
  -v "$PWD/tests:/tests:ro" \
  prom/prometheus:v3.5.0 test rules /tests/availability-rules.test.yml
```

설정 근거: [AIPerf 옵션](https://github.com/ai-dynamo/aiperf/blob/v0.12.0/docs/cli-options.md), [Prometheus EndpointSlice discovery](https://prometheus.io/docs/prometheus/latest/configuration/configuration/#kubernetes_sd_config), [kube-state-metrics EndpointSlice 지표](https://github.com/kubernetes/kube-state-metrics/blob/v2.18.0/docs/metrics/service/endpointslice-metrics.md).
