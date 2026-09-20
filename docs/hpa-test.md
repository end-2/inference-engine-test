# CPU HPA 스케일 아웃과 축소 테스트

CPU 사용률에 따른 스케일 아웃 전용, 스케일 아웃→인 두 시나리오를 실행합니다. 후자는 목표 replica까지 증가한 뒤 클라이언트 요청량을 줄여 최소 replica로 축소하고, 축소 후의 응답 성공까지 검증합니다. [매니페스트](../k8s/hpa-test/kustomization.yaml)는 [availability test](availability-test.md)의 추론 서버, 부하 발생기, 관측 구성을 재사용하며, `hpa-test` 네임스페이스와 별도 node-metrics RBAC를 사용합니다.

## 구성과 준비

| 구성 | 설정 |
| --- | --- |
| 추론 | engine worker 2개에 `llama-base-metric`, Pod당 CPU 2 / 메모리 2 GiB |
| HPA | `autoscaling/v2`, CPU request 대비 평균 사용률 50%, replica 1~4 |
| 스케일 정책 | 증가: 안정화 대기 없이 30초당 최대 1개, 감소: 120초 안정화 후 30초당 최대 1개 |
| 고부하 | AIPerf 동시성 8, 요청률 제한 없이 지속 요청 |
| 저부하 | AIPerf 동시성 1, 일정 간격으로 0.02 req/s(50초마다 1건) |
| 공통 요청 설정 | monitor worker, 스트리밍, 요청마다 새 연결, timeout 30초, 같은 토큰 분포, seed |
| 관측 | Metrics Server, kube-state-metrics, Prometheus, Grafana, AIPerf 결과 PVC |

CPU 사용률의 분모는 **노드 CPU나 limit이 아니라 Pod의 CPU request**입니다. 이 구성에서는 request=limit=2 CPU이므로 50%는 Pod당 평균 1 CPU입니다. HPA는 Metrics Server의 `metrics.k8s.io`를 사용하고, Prometheus는 관측에 사용합니다. [Kubernetes HPA 설명](https://kubernetes.io/docs/concepts/workloads/autoscaling/horizontal-pod-autoscale/)

모든 테스트 컨테이너는 CPU와 메모리 `requests=limits`를 사용합니다. 최대 추론 replica 4개에 총 8 CPU / 8 GiB, monitor 워크로드와 Metrics Server에 총 1.96 CPU / 2152 MiB, 추가로 Kubernetes 시스템 자원이 필요합니다. 각 engine 노드에 추론 Pod 2개를 배치할 여유를 확보합니다. kind 노드는 같은 Docker 호스트 자원을 공유하므로 노드별 allocatable 합계를 실제 호스트 용량으로 해석하지 않습니다. 다른 부하 실험과 동시에 실행하면 CPU 경쟁으로 결과가 달라질 수 있습니다.

Docker, 저장소의 kind/kubectl, Python 3.10 이상과 이미지 다운로드 연결이 필요합니다. 아래는 전용 클러스터를 만드는 절차입니다. 기존 멀티 노드 클러스터를 사용하면 `CLUSTER_NAME`을 해당 이름으로 지정합니다. `up`은 기존 클러스터의 토폴로지를 변경하지 않습니다.

```sh
export CLUSTER_NAME=hpa-test
export PATH="$PWD/.bin:$PATH"
./scripts/download-model.sh
./scripts/download-tokenizer.sh
KIND_CONFIG=config/cluster/kind-multi-node.yaml ./scripts/local-k8s.sh up
./scripts/build-inference-images.sh base-metric
./scripts/load-inference-images.sh base-metric
./scripts/build-benchmark-images.sh
./scripts/load-benchmark-images.sh

./scripts/local-k8s.sh kubectl apply -k k8s/metrics-server
./scripts/local-k8s.sh kubectl -n kube-system rollout status deployment/metrics-server --timeout=180s
./scripts/local-k8s.sh kubectl wait --for=condition=Available apiservice/v1beta1.metrics.k8s.io --timeout=180s
./scripts/local-k8s.sh kubectl apply -k k8s/hpa-test
for deployment in llama-base-metric prometheus kube-state-metrics grafana; do
  ./scripts/local-k8s.sh kubectl -n hpa-test rollout status "deployment/$deployment" --timeout=300s
done
./scripts/local-k8s.sh kubectl -n hpa-test wait --for=condition=Ready pod/aiperf-results --timeout=120s
./scripts/local-k8s.sh kubectl -n hpa-test top pods
./scripts/local-k8s.sh kubectl -n hpa-test get hpa,pods -o wide
```

[Metrics Server 구성](../k8s/metrics-server/kustomization.yaml)은 버전을 고정한 공식 매니페스트에 monitor 노드 배치, 자원 limit과 `--kubelet-insecure-tls`를 적용합니다. 이 TLS 옵션은 kind의 kubelet 인증서를 위한 로컬 실험 설정입니다. 일반 클러스터는 신뢰할 수 있는 kubelet 인증서를 사용합니다. Metrics Server가 이미 설치되어 있으면 기존 Metrics API를 사용하고 해당 설치 단계를 건너뜁니다. [Metrics Server 요구사항](https://github.com/kubernetes-sigs/metrics-server#requirements)

추론 Deployment에는 `spec.replicas`를 선언하지 않아 HPA가 replica 수를 관리합니다. AIPerf와 Grafana renderer는 replica 0으로 시작합니다. 준비 후 CPU 지표가 채워질 때까지 수십 초가 걸릴 수 있습니다.

## 자동 실행과 판정

저장소 루트에서 원하는 시나리오를 실행합니다. 두 스크립트는 같은 배포를 사용하며 순차 실행합니다.

| 시나리오 | 스크립트 | 같은 조건의 보고서 |
| --- | --- | --- |
| 스케일 아웃 전용: 1→4, 60초 유지 후 부하 중지 | [run-hpa-scale-out.py](../scripts/run-hpa-scale-out.py) | [증가 보고서](reports/hpa-20260920-073006-837104/summary.md) |
| 스케일 아웃→인: 1→4→1, 각 60초 유지 | [run-hpa-scale-out-in.py](../scripts/run-hpa-scale-out-in.py) | [증가와 축소 보고서](reports/hpa-20260920-081357-206946/summary.md) |

```sh
# 읽기 전용 배포, Metrics API 사전 검사
python3 scripts/run-hpa-scale-out.py --dry-run
python3 scripts/run-hpa-scale-out-in.py --dry-run

# 스케일 아웃 전용
python3 scripts/run-hpa-scale-out.py

# 스케일 아웃 → 요청량 감소 → 스케일 인
python3 scripts/run-hpa-scale-out-in.py
```

`--cluster`는 `CLUSTER_NAME`보다 우선하며 모든 요청은 `local-k8s.sh`의 격리 kubeconfig를 사용합니다. 같은 클러스터의 HPA runner 중복 실행은 공통 lock으로 막습니다. AIPerf와 renderer가 정지되어 있어야 시작하며, 실행 중 추론 replica를 수동 변경하지 않습니다. 공통 로직은 [hpa_test/runner.py](../scripts/hpa_test/runner.py)에 있으며 `run-hpa-test.py`도 스케일 아웃→인을 실행합니다.

두 스크립트의 공통 단계입니다.

1. HPA CPU 지표가 유효하고 무부하 상태에서 최소 replica, Ready Pod, ready endpoint 수가 30초 동안 일치합니다. 재실행 시 이전 부하의 자동 축소가 끝날 때까지 기다립니다.
2. AIPerf를 시작하고 5초마다 HPA 상태, Deployment, Pod, EndpointSlice, 이벤트를 저장합니다.
3. HPA desired/current, Deployment replica/available, Ready Pod와 일치하는 ready endpoint가 모두 목표 수 이상이고 기준 상태에 없던 새 Pod가 Service에 편입되는지 확인합니다.
4. 고부하를 계속 보내면서 목표 상태를 60초 유지합니다.

**스케일 아웃 전용**은 여기서 부하를 중지하고 AIPerf, Prometheus 데이터를 추출합니다. 고부하 성공 요청이 있어야 `status=complete`입니다. 이후 HPA의 자동 축소는 이 시나리오의 측정, 판정에 포함하지 않습니다.

**스케일 아웃→인**은 이어서 다음을 수행합니다.

1. 고부하 클라이언트 결과를 저장하고 동시성 1, 0.02 req/s의 저부하 클라이언트로 전환합니다. 이때 AIPerf Pod를 재생성하며 종료, 초기화에 따른 짧은 부하 공백과 각 단계 시각을 기록합니다.
2. 저부하 요청을 계속 보내면서 CPU가 목표 아래로 떨어지고 HPA desired/current, Deployment replica/available, 실제 Pod와 ready endpoint 수가 모두 최소 replica로 돌아오는지 확인합니다. 종료 중인 추론 Pod도 없어야 합니다.
3. 최소 replica 상태를 60초 유지한 뒤 부하를 중지하고 두 단계의 AIPerf, Prometheus 데이터를 추출합니다. 고부하, 저부하 각각 성공 요청이 있고, 축소 후 유지 구간 안에서 시작하고 완료된 저부하 성공 요청이 있어야 `status=complete`입니다.

축소 도달 시 CPU가 목표 아래인지 확인하며, 이후 유지 판정은 유효한 CPU 지표와 실제 replica, Pod, endpoint 수를 기준으로 합니다. 순간 CPU 변동만으로 유지 시간을 초기화하지 않고, HPA가 다시 확장하면 유지 시간을 다시 측정합니다.

단계별 제한 시간은 600초이며 시간 초과나 자료 수집 실패는 `status=failed`와 비정상 종료 코드로 표시합니다. 증가 목표는 기본적으로 HPA `maxReplicas`이며 `--target-replicas 2`로 증가 판정 기준을 2개 이상으로 낮출 수 있습니다. 이 옵션은 HPA 최대값을 바꾸지 않으므로 실제 replica는 더 늘어날 수 있습니다. `--timeout`과 각 유지 구간의 `--hold-seconds`는 초 단위입니다. 증가 목표는 최소 replica보다 크고 HPA 최대값 이하여야 합니다.

스케일 아웃→인에서만 `--low-request-rate`로 저부하 요청률을 조정할 수 있습니다. 양의 유한값이어야 하며, 너무 높으면 최소 replica로 축소되지 않아 실패합니다. 유지 시간은 저부하 요청 한 건 이상이 시작하고 완료될 만큼 길어야 합니다. 동시성만 1로 줄이면 응답 직후 새 요청을 보내 CPU가 계속 높을 수 있어, [AIPerf 요청률 옵션](https://github.com/ai-dynamo/aiperf/blob/v0.12.0/docs/cli-options.md)도 함께 제한합니다.

실패, Ctrl+C, SIGTERM에도 AIPerf 정지, 원래 고부하 인자 복원과 결과 수집을 시도합니다. 프로세스 SIGKILL이나 호스트 종료 시에는 아래 수동 중지 명령으로 정리합니다. 추론 replica는 전체 구간에서 HPA가 관리합니다. Pod 삭제로 서버 counter 합계가 감소할 수 있으므로 요청 성공 여부는 단계별 AIPerf 원본으로 판정합니다.

## 실행 중 관찰

자동 runner와 별도 터미널에서 관찰합니다. 고부하→저부하 전환 때 AIPerf Pod가 바뀌므로 로그 follow는 새 Pod에 다시 연결합니다.

```sh
./scripts/local-k8s.sh kubectl -n hpa-test get hpa llama-base-metric --watch
# 다른 터미널
./scripts/local-k8s.sh kubectl -n hpa-test get pods -l app=llama-base-metric -o wide --watch
# 클라이언트가 시작된 뒤 다른 터미널
./scripts/local-k8s.sh kubectl -n hpa-test logs -f deployment/aiperf --timestamps
```

```sh
./scripts/local-k8s.sh kubectl -n hpa-test top pods -l app=llama-base-metric
./scripts/local-k8s.sh kubectl -n hpa-test describe hpa llama-base-metric
./scripts/local-k8s.sh kubectl -n hpa-test get endpointslices -l kubernetes.io/service-name=llama-base-metric -o yaml
# 별도 터미널에서 유지
./scripts/local-k8s.sh kubectl -n hpa-test port-forward service/grafana 3000:3000
```

`http://localhost:3000`의 **CPU HPA scale-out and scale-in** 대시보드는 CPU 관측값, 목표값, HPA desired/current, 가용 Pod, ready endpoint, HPA conditions와 요청 처리량, 서버 TTFT를 보여 줍니다. HPA CPU 값은 controller가 마지막으로 평가한 평균이며 Prometheus scrape 시각의 순간 CPU와 같지 않습니다. KSM의 `status_target_metric`이 관측값이고 `spec_target_metric`이 설정한 목표값입니다.

CPU 상승, `SuccessfulRescale` 이벤트, Pod 생성, Ready 전환, EndpointSlice 편입을 순서대로 확인합니다. `desiredReplicas`만 늘고 Pod가 Pending이면 성공으로 판정하지 않습니다. HPA는 기존 노드 안의 Pod 수를 조절하며 노드를 추가하지 않습니다. 수집, 제어 주기, 초기 Pod의 readiness와 누락된 지표 때문에 CPU가 목표를 넘은 즉시 증가하지 않을 수 있습니다.

저부하 전환 후에는 CPU 하락, 축소 안정화 대기, desired 감소, Pod 종료와 endpoint 감소를 비교합니다. 설정한 120초 안정화 시간 외에도 마지막 CPU 표본, controller 주기, 30초당 1개 축소 정책, Pod 종료 시간이 반영되므로 정확히 120초 뒤에 최소 replica가 되는 것은 아닙니다.

CPU가 목표 아래라는 사실만으로 replica가 감소하지는 않습니다. 예를 들어 replica 2개, 평균 CPU 34%, 목표 50%의 기본 계산은 `ceil(2 × 34 / 50) = 2`입니다. 짧은 CPU 상승도 축소 권고와 안정화 대기에 영향을 주므로 실제 replica, endpoint 변화를 함께 확인합니다.

강제 종료로 runner의 정리가 실행되지 않은 경우 부하를 중지하고 결과를 복사한 뒤 기본 클라이언트 인자를 복원합니다.

```sh
./scripts/local-k8s.sh kubectl -n hpa-test scale deployment/aiperf --replicas=0
./scripts/local-k8s.sh kubectl -n hpa-test wait --for=delete pod -l app=aiperf --timeout=150s
mkdir -p reports/hpa-manual
./scripts/local-k8s.sh kubectl -n hpa-test cp aiperf-results:/results reports/hpa-manual/aiperf
./scripts/local-k8s.sh kubectl apply -k k8s/hpa-test
```

## 저장 데이터와 해석

[실행 보고서](reports/hpa-20260920-081357-206946/summary.md)에서 고부하→저부하 전환에 따른 replica 1→4→1과 실제 요청 결과, 같은 구간의 Grafana 패널을 확인할 수 있습니다.

각 자동 실행은 `reports/hpa-<UTC>/`에 저장합니다. `run.json`의 `scenario`로 `scale-out`과 `scale-out-in`을 구분합니다. 저부하, 축소 데이터는 스케일 아웃→인 실행에만 포함됩니다. 보고서와 Grafana PNG는 자동 생성하지 않습니다.

| 파일 | 내용 |
| --- | --- |
| `run.json` | 시나리오, 단계별 요청 인자, Pod, UTC 시각, 원래 클라이언트 인자, 요청 성공, 오류 수, 축소 후 성공 수, 완료, 실패 상태 |
| `observations.jsonl`, `observations.csv` | baseline, scale-out, high-hold, scale-in, low-hold별 CPU, replica, Pod, endpoint 표본 |
| `kubernetes-snapshots.jsonl.gz` | 각 표본의 HPA, Deployment, Pod, EndpointSlice, 이벤트 원본 |
| `aiperf-high.log`, `aiperf-low.log`, `aiperf/high/`, `aiperf/low/` | 단계별 부하 로그, 요청별 JSONL, AIPerf 집계 |
| `prometheus/` | 대시보드 각 쿼리의 5초 간격 시계열 |

스케일 변화와 요청 품질은 별도로 해석합니다. 초기 replica 1개에 동시성 8을 보내면 큐 대기와 30초 timeout이 발생할 수 있습니다. 사용자 관점의 실패율, TTFT, ITL은 단계별 AIPerf 결과로 확인합니다. 고부하는 고정 동시성의 closed-loop, 저부하는 일정 도착률과 동시성 상한 1을 사용하므로 두 단계 처리량 차이를 같은 요청량에서의 성능 차이로 해석하지 않습니다. 연결, 서버 지표의 의미는 [availability test의 지속 부하와 지표](availability-test.md#지속-부하와-지표)를 참고합니다.

| 증상 | 확인 사항 |
| --- | --- |
| CPU `<unknown>`, `FailedGetResourceMetric` | Metrics Server 로그, APIService Available, `top pods`, CPU request |
| desired 증가 후 Pending | 노드별 CPU와 메모리 예약량, engine 라벨, 이미지, 모델 마운트와 Pod 이벤트 |
| CPU가 목표보다 낮음 | AIPerf `PROFILING` 로그, 성공 요청 증가, 실제 CPU, 호스트 자원 경쟁 |
| `ScalingLimited=True` | 최대 replica 또는 증가 정책에 도달했는지 HPA reason/message 확인 |
| 재실행 baseline 시간 초과 | 다른 클라이언트 부하, AIPerf 종료, 축소 안정화 시간, CPU, readiness 확인 |
| scale-in 시간 초과 | 저부하 요청률, 다른 클라이언트, CPU 지표, 축소 정책과 종료 중인 Pod 확인 |
| 축소 후 성공 요청 없음 | 저부하 AIPerf 오류, 요청 간격, 유지 시간 확인; replica 감소만으로 통과하지 않음 |

## 검증과 정리

```sh
python3 -m unittest discover -s tests -p 'test_hpa_runner.py'
sh tests/test-hpa-manifests.sh
```

결과를 내보낸 뒤 테스트 워크로드와 PVC를 삭제합니다. Metrics Server는 클러스터 공용 리소스이므로 이 실험을 위해 설치했고 다른 사용자가 없을 때만 삭제합니다.

```sh
./scripts/local-k8s.sh kubectl delete -k k8s/hpa-test
# 이 실험 전용으로 설치한 경우
./scripts/local-k8s.sh kubectl delete -k k8s/metrics-server
# 전용 클러스터 자체를 정리할 경우
./scripts/local-k8s.sh down
```
