# Kubernetes 매니페스트 관리

`k8s/`의 각 배포 디렉터리는 완성된 Kubernetes 매니페스트를 포함합니다. 디렉터리의 YAML을 직접 수정하고 `kubectl apply -f`로 적용합니다. 모델과 실험별 공통 설정을 변경할 때는 관련 디렉터리에도 반영합니다.

## 적용

```sh
./scripts/local-k8s.sh kubectl apply -f k8s/transformers-base/
```

availability와 HPA 테스트는 namespace를 먼저 생성합니다.

```sh
./scripts/local-k8s.sh kubectl apply -f k8s/hpa-test-transformers/namespace.yaml
./scripts/local-k8s.sh kubectl apply -f k8s/hpa-test-transformers/
```

`scenarios/`의 파일은 실험 중 사용하는 패치이므로 디렉터리를 재귀 적용하는 `-R` 옵션은 사용하지 않습니다.

배포 리소스를 삭제할 때는 동일한 배포 디렉터리에 `kubectl delete -f`를 사용합니다. 테스트 디렉터리를 대상으로 실행하면 namespace와 PVC도 삭제됩니다.

## 설정 변경

Prometheus 설정과 규칙, Grafana 대시보드와 provisioning 설정, AIPerf 실행 스크립트는 각 디렉터리의 `*-configmap.yaml`에 정의합니다. ConfigMap 이름은 고정되어 있으며, 설정을 적용해도 Deployment의 Pod가 자동으로 재시작되지는 않습니다.

실험을 중지한 상태에서 ConfigMap을 적용하고 해당 설정을 사용하는 Deployment를 재시작합니다. HPA 테스트의 Prometheus 설정을 변경한 경우에는 다음 명령을 실행합니다.

```sh
./scripts/local-k8s.sh kubectl apply -f k8s/hpa-test-transformers/prometheus-config-configmap.yaml
./scripts/local-k8s.sh kubectl -n hpa-test-transformers rollout restart deployment/prometheus
./scripts/local-k8s.sh kubectl -n hpa-test-transformers rollout status deployment/prometheus
```

Grafana 설정은 `deployment/grafana`, AIPerf 실행 스크립트는 `deployment/aiperf`에 반영합니다. replicas가 0인 AIPerf는 다음 실행에서 새 설정을 읽습니다.

HPA 결과 수집기는 클러스터의 `grafana-dashboard` ConfigMap에서 조회식을 읽습니다.

## 검증

저장소 루트에서 실행합니다. 마지막 검사는 로컬 kubeconfig와 kubectl을 사용합니다.

```sh
sh tests/test-aiperf-manifests.sh
sh tests/test-hpa-manifests-llamacpp.sh
sh tests/test-hpa-manifests-transformers.sh
sh tests/test-transformers-manifests.sh
```
