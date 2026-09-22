# CPU HPA 테스트

Manifest 적용과 ConfigMap 변경 방법은 [manifest 관리](manifests.md)를 참고합니다.

기본 절차는 Transformers CPU를 사용합니다. llama.cpp는 [엔진별 변경 사항](#llamacpp)을 적용하며 관찰과 판정 기준은 동일합니다. 추론 구현과 API는 [추론 엔진 가이드](inference-engine.md)를 참고하세요.

SmolLM2 Transformers CPU base 서버에 AIPerf 부하를 보내 CPU HPA의 1→4 확장과 4→1 축소를 검증합니다. 실제 Ready Pod, Service endpoint와 성공 요청을 함께 확인합니다.

## 준비와 배포

control-plane 1개, monitor worker 1개, engine worker 2개와 `transformers-base-metric` 이미지를 사용합니다. 자원과 스레드는 [배포 매니페스트](../../k8s/hpa-test-transformers/)에서 설정하며 `requests=limits`를 유지합니다. Pod별 자원 요청량과 최대 replica 수를 기준으로 추론 용량을 확보하고, monitor와 Kubernetes 시스템 자원을 추가합니다.

Docker, POSIX 셸, Python 3.10 이상이 필요합니다. 저장소 루트에서 모델, 클러스터와 이미지를 준비합니다.

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

`up`은 기존 클러스터의 토폴로지를 변경하지 않습니다. 같은 이름의 단일 노드 클러스터가 있으면 새 이름을 지정합니다. 모든 명령은 같은 `CLUSTER_NAME`으로 실행합니다.

availability 테스트가 배포되어 있으면 결과를 내보낸 뒤 `./scripts/local-k8s.sh kubectl delete -f k8s/availability-test-transformers`로 정리합니다. 이 명령은 해당 테스트 PVC도 삭제합니다. 다른 부하 실험과 동시에 실행하지 않습니다.

```sh
export CLUSTER_NAME=transformers-tests
./scripts/local-k8s.sh kubectl apply -f k8s/metrics-server
./scripts/local-k8s.sh kubectl -n kube-system rollout status deployment/metrics-server --timeout=180s
./scripts/local-k8s.sh kubectl wait --for=condition=Available apiservice/v1beta1.metrics.k8s.io --timeout=180s
./scripts/local-k8s.sh kubectl apply -f k8s/hpa-test-transformers/namespace.yaml
./scripts/local-k8s.sh kubectl apply -f k8s/hpa-test-transformers
for deployment in transformers-base-metric prometheus kube-state-metrics grafana; do
  ./scripts/local-k8s.sh kubectl -n hpa-test-transformers rollout status "deployment/$deployment" --timeout=300s
done
./scripts/local-k8s.sh kubectl -n hpa-test-transformers wait --for=condition=Ready pod/aiperf-results --timeout=120s
./scripts/local-k8s.sh kubectl -n hpa-test-transformers wait \
  --for=jsonpath='{.status.currentMetrics[0].resource.current.averageUtilization}' \
  hpa/transformers-base-metric --timeout=180s
./scripts/local-k8s.sh kubectl -n hpa-test-transformers top pods
```

새 Pod는 Ready가 된 뒤에도 첫 메트릭 수집까지 시간이 필요합니다. HPA의 CPU 측정값을 기다린 뒤 `top`을 실행합니다.

기존 Metrics Server가 있으면 해당 Metrics API를 사용합니다. 저장소 설정의 `--kubelet-insecure-tls`는 kind 실험용입니다. Metrics Server는 HPA 제어에 사용하고 Prometheus는 관측에 사용합니다.

| 항목 | 기본값 |
| --- | --- |
| HPA | `autoscaling/v2`, min 1, max 4, CPU request 대비 평균 50% |
| 확장 정책 | 안정화 0초, 30초당 Pod 1개 |
| 축소 정책 | 안정화 120초, 30초당 Pod 1개 |
| 고부하 | AIPerf concurrency 8, worker 1, timeout 30초 |
| 저부하 | concurrency 1, constant 0.02 req/s |
| 판정 | 단계별 제한 600초, 확장과 축소 도달 후 각각 60초 유지 |

CPU 목표는 Pod의 CPU request 대비 사용률입니다. 모델은 고정된 SmolLM2-135M-Instruct FP32 snapshot이며 서버와 AIPerf가 해당 snapshot의 tokenizer를 사용합니다. 입력과 출력 길이 분포는 `64,32:50;256,64:50`, 입력 16개, seed 42, sequential, `ignore_eos:true`입니다. [HPA manifest](../../k8s/hpa-test-transformers/)는 namespace, RBAC, 대시보드와 부하를 독립적으로 정의합니다. 추론 Deployment의 replicas는 HPA가 관리하고 AIPerf와 renderer는 0개로 시작합니다.

## 실행

```sh
python3 scripts/run-hpa-test-transformers.py --scenario scale-out-in --dry-run
python3 scripts/run-hpa-test-transformers.py --scenario scale-out-in
# 확장만 검증하려면 별도로 실행
python3 scripts/run-hpa-test-transformers.py --scenario scale-out
```

`run-hpa-test-transformers.py`의 기본 시나리오는 `scale-out-in`입니다. `--cluster`는 `CLUSTER_NAME` 또는 `transformers-tests`가 기본값입니다. 두 engine worker와 한 monitor worker를 확인하며, availability와 공통 lock으로 중복 실행을 막습니다.

runner는 무부하 최소 replica 상태를 30초 확인한 뒤 고부하를 시작합니다. HPA current/desired, Deployment replicas/available, Ready Pod와 일치하는 ready endpoint가 모두 목표 수에 도달하고 새 Pod가 편입되어야 확장을 인정합니다. Pending Pod나 desired 증가만으로 통과하지 않습니다.

scale-out-in은 고부하를 중지한 뒤 AIPerf Pod를 저부하 조건으로 다시 시작합니다. CPU가 목표 아래이며 실제 Pod와 endpoint가 모두 1개, 종료 중 Pod가 0개가 되어야 축소를 인정합니다. 이후 60초 유지 구간 안에서 시작하고 완료된 성공 요청이 하나 이상 있어야 통과합니다. 두 부하 단계 사이의 클라이언트 종료와 초기화 시간도 기록합니다.

`--target-replicas`는 HPA 최대값을 변경하지 않는 확장 판정 목표, `--timeout`은 단계 제한, `--hold-seconds`는 유지 시간을 조정합니다. scale-out-in의 `--low-request-rate`는 저부하 도착률을 조정합니다. 동시성 1만으로는 CPU가 충분히 낮아지지 않을 수 있습니다. 실패와 Ctrl+C에도 부하 중지, 원래 클라이언트 인자 복원과 자료 수집을 시도합니다.

AIPerf와 renderer가 중지된 상태에서 시작하고 측정 중 추론 replica를 수동 변경하지 않습니다. 시간 초과나 수집 실패는 `status=failed`로 기록합니다.

## 관찰과 결과

```sh
./scripts/local-k8s.sh kubectl -n hpa-test-transformers get hpa,pods -o wide
./scripts/local-k8s.sh kubectl -n hpa-test-transformers top pods
./scripts/local-k8s.sh kubectl -n hpa-test-transformers port-forward service/grafana 3000:3000
```

Grafana `hpa-test-transformers` 대시보드에서 CPU, HPA replica, endpoint, `transformers_*` 요청 지표를 확인합니다. CPU가 `<unknown>`이면 Metrics API와 CPU request를 확인하고, Pod가 Pending이면 engine worker의 예약 자원과 이미지, 모델 마운트를 확인합니다.

원본은 `reports/transformers/hpa-<UTC>/`에 저장합니다. `run.json`의 scenario, 단계 시각과 요청 수, `observations.csv`의 5초 표본, Kubernetes 원본, `aiperf/high/`, `aiperf/low/`, Prometheus 시계열을 포함합니다. high/low 요청 성공 여부로 절차를 판정하며, 오류율과 지연은 별도로 해석합니다. [Transformers 결과 목록](../reports/transformers/README.md)에 요약을 보관합니다.

## 검증과 정리

```sh
python3 -m unittest discover -s tests -p 'test_hpa_runner_transformers.py'
sh tests/test-hpa-manifests-transformers.sh
# 결과 수집 후 워크로드와 PVC 삭제
./scripts/local-k8s.sh kubectl delete -f k8s/hpa-test-transformers
# 이 실험만 사용하는 Metrics Server일 때
./scripts/local-k8s.sh kubectl delete -f k8s/metrics-server
```

## llama.cpp

위 절차에서 다음 값을 바꿉니다. 모든 터미널에서 선택한 `CLUSTER_NAME`을 동일하게 사용합니다.

| 항목 | Transformers 기본값 | llama.cpp |
| --- | --- | --- |
| 클러스터 예시 | `transformers-tests` | `hpa-test-llamacpp` |
| 모델 준비 | `./scripts/download-transformers-model.sh` | `./scripts/download-model-llamacpp.sh`와 `./scripts/download-tokenizer-llamacpp.sh` |
| 추론 이미지와 Deployment | `transformers-base-metric` | `base-metric-llamacpp` |
| 매니페스트 | `k8s/hpa-test-transformers` | `k8s/hpa-test-llamacpp` |
| namespace와 대시보드 | `hpa-test-transformers` | `hpa-test-llamacpp` |
| runner | `scripts/run-hpa-test-transformers.py` | `scripts/run-hpa-test-llamacpp.py` |
| 결과 루트 | `reports/transformers/` | `reports/llamacpp/` |

모델은 [Qwen GGUF 설정](../../config/models/qwen2.5-0.5b-gguf-llamacpp.env)을 사용하며 서버와 AIPerf의 모델 및 토크나이저를 맞춥니다. 자원과 부하 설정은 [llama.cpp 매니페스트](../../k8s/hpa-test-llamacpp/)를 기준으로 합니다. 같은 클러스터의 다른 테스트를 정리할 때도 해당 엔진의 namespace와 매니페스트를 선택합니다.

```sh
export CLUSTER_NAME=hpa-test-llamacpp
python3 scripts/run-hpa-test-llamacpp.py --scenario scale-out-in --dry-run
python3 scripts/run-hpa-test-llamacpp.py --scenario scale-out-in
# 확장만 검증할 때
python3 scripts/run-hpa-test-llamacpp.py --scenario scale-out
```

강제 종료로 정리가 실행되지 않았다면 부하를 중지하고 결과를 복사한 뒤 기본 설정을 복원합니다. Transformers도 해당 namespace와 결과 루트로 바꾸어 복구합니다.

```sh
./scripts/local-k8s.sh kubectl -n hpa-test-llamacpp scale deployment/aiperf --replicas=0
./scripts/local-k8s.sh kubectl -n hpa-test-llamacpp wait --for=delete pod -l app=aiperf --timeout=150s
mkdir -p reports/llamacpp/hpa-manual
./scripts/local-k8s.sh kubectl -n hpa-test-llamacpp cp aiperf-results:/results reports/llamacpp/hpa-manual/aiperf
./scripts/local-k8s.sh kubectl apply -f k8s/hpa-test-llamacpp/namespace.yaml
./scripts/local-k8s.sh kubectl apply -f k8s/hpa-test-llamacpp
```

llama.cpp runner와 매니페스트 검증은 다음 명령을 사용합니다.

```sh
python3 -m unittest discover -s tests -p 'test_hpa_runner_llamacpp.py'
sh tests/test-hpa-manifests-llamacpp.sh
```

보고서와 Grafana PNG는 자동 생성하지 않습니다. 축소가 지연되면 저부하 요청률, 축소 안정화 시간과 종료 중인 Pod를 확인합니다.
