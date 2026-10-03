# Helm으로 Kubernetes 매니페스트 관리

`k8s/`의 하위 디렉터리는 모두 Helm 차트입니다. 각 차트의 `values.yaml`에 공통 기본값을 두며, 여러 워크로드를 지원하는 차트는 `profiles/*.yaml`에 차이를 지정합니다. `make install`은 [versions.env](../../config/versions.env)의 고정 버전 Helm을 설치합니다. 외부 차트 의존성은 없습니다.

```text
k8s/
  inference/
  aiperf/
  experiment/
  inference-distributed/
  metrics-server/
```

각 차트는 `Chart.yaml`, `values.yaml`, `templates/`를 포함합니다. 실험 설정 파일과 패치도 `experiment/files/`, `experiment/scenarios/`에서 함께 관리합니다.

| 차트 | 프로필 | 공통 기본값 |
| --- | --- | --- |
| Inference | CPU, GPU, Mamba, MPS 서버 | [inference/values.yaml](../../k8s/inference/values.yaml) |
| AIPerf | 모델별, 데이터셋별, PD 벤치마크 | [aiperf/values.yaml](../../k8s/aiperf/values.yaml) |
| Experiment | 두 엔진의 availability와 HPA | [experiment/values.yaml](../../k8s/experiment/values.yaml) |
| inference-distributed | MPS 2분할과 4분할, serial과 token-budget 스케줄링 | [inference-distributed/values.yaml](../../k8s/inference-distributed/values.yaml) |
| Metrics Server | 로컬 kind 메트릭 | [components.yaml](../../k8s/metrics-server/templates/components.yaml) |

## 렌더링과 적용

저장소 루트에서 실행합니다. 렌더링에는 클러스터가 필요하지 않습니다. 스크립트는 차트 디렉터리 또는 차트 안의 values 파일을 받습니다. 적용 스크립트는 렌더링에 성공한 뒤 격리된 로컬 kubeconfig로 kubectl을 실행하며, Helm 릴리스는 생성하지 않습니다.

```sh
./scripts/render-k8s.sh k8s/inference/profiles/transformers-base-cpu.yaml
./scripts/k8s.sh apply k8s/inference/profiles/transformers-base-cpu.yaml
./scripts/k8s.sh apply k8s/experiment/profiles/hpa-transformers.yaml

# 기존 클러스터 스크립트로 GPU 클러스터 선택
LOCAL_K8S_SCRIPT=./scripts/local-k8s-gpu.sh ./scripts/k8s.sh apply k8s/inference/profiles/transformers-base-gpu.yaml
```

`experiment`와 `inference-distributed` 차트는 namespace를 포함합니다. `experiment/scenarios/`는 실험용 kubectl 패치이며 렌더링에 포함하지 않습니다. PD 토폴로지 전환에는 `make pd-deploy PD_MODE=aggregated` 또는 `PD_MODE=disaggregated`를 사용합니다. 기존 Pod의 GPU 슬롯을 반환한 뒤 선택한 프로필을 적용합니다.

`make render`와 `make deploy`는 이미지 빌드 명령과 같은 `VARIANT`, `DEVICE`, `IMAGE_TAG`를 사용합니다. 벤치마크의 `--manifests`에는 차트 안의 values 파일이나 차트 디렉터리를 지정합니다. 사용자 정의 일반 매니페스트 파일과 디렉터리도 지원합니다.

```sh
make render VARIANT=transformers-enhanced-cache DEVICE=gpu
make deploy VARIANT=transformers-base IMAGE_TAG=0.1.0
./scripts/k8s.sh delete k8s/experiment/profiles/hpa-transformers.yaml
```

실험 프로필을 삭제하면 namespace와 PVC도 삭제합니다. 정리 전에 결과를 내보냅니다.

## 설정 변경

공통 설정은 차트의 기본값에서, 워크로드별 차이는 프로필에서 변경합니다. 프로필 인자 뒤에 `-f` 파일과 `--set` 옵션을 추가할 수 있습니다. `container.args`, `pod.volumes`와 같은 목록은 전체를 교체합니다.

```sh
./scripts/render-k8s.sh k8s/inference/profiles/transformers-base-cpu.yaml --set-string container.image=local/transformers-base:test
./scripts/render-k8s.sh k8s/inference-distributed/profiles/mps-4-disaggregated.yaml

# 같은 결과를 만드는 Helm 직접 실행
./.bin/helm template inference-test k8s/inference -f k8s/inference/profiles/transformers-base-cpu.yaml
```

Prometheus 규칙, Grafana 대시보드, provisioning과 AIPerf 스크립트는 [experiment/files](../../k8s/experiment/files/)에서 관리합니다. 실험 ConfigMap 이름은 고정되어 있습니다. 실험을 멈춘 뒤 설정을 적용하고 사용하는 Deployment를 재시작합니다. replicas가 0인 AIPerf는 다음 실행에서 새 설정을 읽습니다.

```sh
./scripts/k8s.sh apply k8s/experiment/profiles/hpa-transformers.yaml --show-only templates/prometheus-config-configmap.yaml
./scripts/local-k8s.sh kubectl -n hpa-test-transformers rollout restart deployment/prometheus
./scripts/local-k8s.sh kubectl -n hpa-test-transformers rollout status deployment/prometheus
```

PD 설정의 ConfigMap 이름에는 내용 해시가 들어가므로 설정 변경 시 워커의 참조도 바뀝니다. HPA 결과 수집기는 배포된 `grafana-dashboard` ConfigMap의 조회식을 사용합니다.

## 검증

```sh
./.bin/helm lint k8s/*
python3 -m unittest discover -s tests -p 'test_helm_manifests.py'
sh tests/test-aiperf-manifests.sh
sh tests/test-hpa-manifests-llamacpp.sh
sh tests/test-hpa-manifests-transformers.sh
```

매니페스트 테스트는 기존 테스트 의존성인 PyYAML을 사용합니다. `sh tests/test-transformers-manifests.sh`는 로컬 kubeconfig와 kubectl을 통한 검증도 수행합니다.
