# MPS 4분할 구성 검증

2026-10-01 UTC, RTX 2060 SUPER 8 GiB에서 Aggregation worker 4개와 Prefill 1개, Decode 3개의 실제 배포와 요청 분산을 확인했습니다. 전체 성능 비교에 앞선 축소 workload 검사이며 장시간 부하나 전체 입력, 출력 조합에 대한 결론은 포함하지 않습니다.

## 확인한 동작

- MPS 공유 리소스 4개, client별 active thread 한도 25%, GPU 메모리 한도 2 GiB.
- CUDA client 4개가 같은 MPS 서버에 동시에 연결되어 메모리 쓰기와 읽기 검사 통과.
- 두 mode 모두 worker 4개가 Ready이며 GPU 슬롯, CPU와 호스트 메모리 예산 일치.
- Aggregation 4개의 Pod 주소와 Decode 3개의 Pod 주소로 요청 분산.
- 두 mode의 요청 payload 해시와 실제 입력, 출력 토큰 분포 일치.
- 측정 요청 64개 모두 성공, worker와 Router 재시작 0회.

합성 입력 64, 704토큰, 출력 16토큰, 동시성 4와 8에서 조건별 8개 요청을 1회 측정했습니다. 실제 입력은 94, 734토큰입니다. 조건별 워밍업 2개는 측정 통계에서 제외했습니다. [측정 표와 그림](summary.md), [재현 workload](workload.json)에 조건을 기록했습니다.

Worker 로그에서 워밍업을 포함해 확인한 요청 수는 다음과 같습니다. Prefill 내부 호출은 생성 완료 로그에 따로 중복 집계하지 않습니다.

| Mode | Pod | 완료 요청 수 |
| --- | --- | ---: |
| Aggregation | `pd-aggregate-0` | 10 |
| Aggregation | `pd-aggregate-1` | 10 |
| Aggregation | `pd-aggregate-2` | 10 |
| Aggregation | `pd-aggregate-3` | 10 |
| Disaggregation | `pd-decode-0` | 14 |
| Disaggregation | `pd-decode-1` | 13 |
| Disaggregation | `pd-decode-2` | 13 |

Disaggregation Router의 cgroup `memory.peak`는 81,686,528 bytes (77.9 MiB)였습니다. `memory.events`의 `oom`과 `oom_kill`은 0입니다. 동시 상태 전송 슬롯 2개와 메모리 상한 1 GiB를 유지했습니다.

## 기존 구성 보존

`config/cluster/mps.yaml`, `config/cluster/mps-smoke.yaml`과 기존 `k8s/gpu-mps/`의 모든 YAML은 작업 전후 SHA-256이 일치합니다. 4분할은 새 설정과 overlay로 추가하고 기본값은 2분할로 유지합니다. 단위 테스트에서 다른 분할 수로 기존 클러스터를 재설정하거나 삭제하는 요청을 거부하는지, 4분할 배포가 자기 namespace만 사용하는지 확인했습니다.

실제 GPU 검사는 기존 `local-k8s-gpu` 클러스터를 일시적으로 4분할로 설정해 `pd-comparison-4`에서 수행했습니다. 별도 기본 클러스터 `local-k8s-gpu-mps4`를 계속 실행해 두지는 않았습니다. 검증 후 임시 namespace를 제거하고 기존 Deployment 명세, Helm 값과 GPU `Default` compute mode를 복구했습니다. `base-llamacpp` 1개가 Ready입니다.

PD 테스트 30개, GPU 클러스터 테스트 13개와 GPU 벤치마크 설정 테스트 11개가 통과했습니다. 두 overlay의 Kubernetes server dry-run과 shellcheck도 통과했습니다. 새 추론 이미지를 빌드해 검사 노드에 로드했습니다.

[환경 검증 JSON](environment-validation.json)에 MPS client 목록, 이미지, 메모리, 요청 분산과 보존 검사를 기록합니다. 원본 로그와 배포 명세는 `reports/pd/four-slot-check-20261001/`에 보관합니다. 실제 사용은 [4분할 실행 가이드](../../../../guides/prefill-decode-4.md)를 따릅니다.
