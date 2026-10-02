# 실행 환경과 안정성 검증

2026-10-01 12:11:27~18:12:59 UTC에 전체 workload를 3회 반복했습니다. Aggregation worker 4개와 Prefill 1개, Decode 3개를 같은 GPU의 MPS share 4개에서 비교했습니다. 240개 조건 실행의 측정 요청 7,680개가 모두 성공했으며, 워밍업 960개는 성능 통계에서 제외했습니다.

- 두 mode의 요청 payload 해시와 실제 입력, 출력 길이별 요청 수가 모든 조건과 반복에서 일치했습니다. 출력 길이는 요청값과 일치했습니다.
- 각 배포는 GPU worker 4개와 router 1개로 구성됐습니다. 고정 길이 및 혼합 부하 종료 시 모두 Ready였으며 Pod 재시작은 0건이었습니다.
- 각 반복에서 워밍업을 포함해 A worker마다 360개, D worker마다 480개의 완료 요청을 확인했습니다.
- MPS active thread 한도는 client별 25%, GPU 메모리 한도는 2 GiB였으며, 종료 직전 CUDA client 4개를 확인했습니다.
- 모든 배포의 inference 이미지 ID가 같았고 실행 이미지의 PD 소스 해시가 저장소와 일치했습니다.

Router 컨테이너의 cgroup 메모리 기록은 다음과 같습니다. 각 mode를 배포할 때 Pod를 새로 생성했습니다. 최대값은 해당 Pod 생애의 `memory.peak`이며 메모리 상한은 모두 1 GiB입니다.

| 반복 | A 최대 MiB | D 최대 MiB | OOM | Pod 재시작 |
| --- | ---: | ---: | ---: | ---: |
| 1 | 51.82 | 82.53 | 0 | 0 |
| 2 | 54.21 | 83.71 | 0 | 0 |
| 3 | 47.71 | 82.43 | 0 | 0 |

측정에는 기존 `local-k8s-gpu` 클러스터를 임시로 4분할하여 사용했습니다. 종료 후 기존 Deployment 명세와 NVIDIA device plugin Helm values가 실행 전과 일치하는지 확인했습니다. GPU compute mode는 `Default`, 노드 할당 자원은 GPU 1개와 공유 GPU 0개로 복구했으며 기존 `base-llamacpp`는 1/1 Ready입니다.

기존 2분할 설정인 `config/cluster/mps.yaml`, `config/cluster/mps-smoke.yaml`과 `k8s/gpu-mps`의 YAML 파일은 실행 전후 SHA-256이 일치합니다. 4분할 overlay의 Prefill 1개와 Decode 3개 설정도 유지했습니다.

현재 클러스터는 원래 설정으로 복구된 상태입니다. 재측정하려면 먼저 [4분할 가이드](../../../../guides/prefill-decode-4.md)로 MPS 4개 슬롯을 준비하고, benchmark의 `--cluster`에 준비한 클러스터 이름을 지정합니다. 보고서의 실행 명령에는 측정 당시 클러스터 이름이 기록되어 있습니다.

[환경 검증 JSON](environment-validation.json)에 이미지, MPS 설정, 각 배포의 Pod 상태, 메모리 이벤트와 보존 검사가 있습니다. 원본 Pod snapshot, cgroup 기록과 worker 로그는 `reports/pd/benchmark-four-20261001/r*/<mode>/`에 보관합니다.
