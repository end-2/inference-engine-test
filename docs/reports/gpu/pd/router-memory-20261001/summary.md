# Router 메모리 제한 보강 검증

Router의 큰 KV 본문 수명을 정상 완료뿐 아니라 실패와 취소에서도 제한하고, 동시에 만드는 상태 수를 2개로 제한했습니다. Kubernetes의 1 GiB 메모리 상한에서 실제 HTTP 요청 768개가 모두 성공했습니다. Router의 cgroup 메모리 최고값은 **258.5 MiB**, OOM과 컨테이너 재시작은 **0회**였습니다.

## 적용한 한도

| 설정 | 값 | 적용 범위 |
| --- | --- | --- |
| `MAX_PENDING` | 8 | 스트리밍 완료까지 수용하는 전체 요청 수 |
| `MAX_STATE_TRANSFERS` | 2 | Prefill 요청 전부터 Decode 응답 헤더 수신까지 |
| `MAX_STATE_MIB` | 64 | 요청 하나의 상태 크기 상한 |
| 업로드 청크 | 64 KiB | HTTP 전송 버퍼에 한 번에 넘기는 크기 |
| Router 메모리 요청 / 상한 | 512 MiB / 1 GiB | 두 mode 공통 manifest |

슬롯을 기다리는 요청은 아직 Prefill을 수행하지 않아 KV 상태를 보유하지 않습니다. 원본 상태의 동시 크기는 최대 128 MiB이지만 수신 중 복사본, HTTP 버퍼와 Python 메모리가 추가됩니다. 전송이 시작되기 전 실패하거나 첫 청크 이후 취소되어도 본문 참조와 슬롯을 반환합니다. 슬롯 대기는 120초가 지나면 HTTP 504를 반환하며, 수용 한도 초과는 HTTP 429입니다.

새 `state_queue_ms` 지표는 Router 전송 슬롯 대기를 기록합니다. 대기 시간을 Prefill 계산이나 Decode 대기로 오해하지 않도록 분리했습니다. 비스트리밍 요청은 Decode 완료 후 응답 헤더가 오므로 슬롯을 더 오래 점유할 수 있습니다.

## 실제 HTTP 스트레스 검사

기존 kind GPU worker 노드의 별도 namespace에서 CPU Router와 mock Prefill, Decode를 실행했습니다. Mock은 요청한 크기의 상태를 보내고 수신 바이트를 검사하며, Decode는 작은 지연을 두고 본문을 읽습니다. GPU 모델 추론은 실행하지 않았습니다.

| 상태 크기 | 동시성 | 성공 요청 | 오류 | 소요 시간 s |
| --- | ---: | ---: | ---: | ---: |
| 17,120,000 bytes, 약 16.33 MiB | 8 | 512 | 0 | 44.75 |
| 67,108,864 bytes, 64 MiB | 8 | 256 | 0 | 79.82 |

두 부하를 Router 재시작 없이 연속 실행했습니다. 메모리 최고값은 주기적 RSS 표본이 아니라 해당 컨테이너의 `/sys/fs/cgroup/memory.peak`인 271,007,744 bytes입니다. `memory.events`의 `max`, `oom`, `oom_kill`은 모두 0이고 메모리 상한은 1,073,741,824 bytes였습니다. 이 결과는 위 설정과 부하에서의 검증이며, 상태 한도나 동시 전송 수를 늘린 환경까지 보장하지 않습니다.

첫 검사는 기존 런타임 이미지에 수정한 Router 소스를 ConfigMap으로 mount했습니다. 이후 수정한 추론 이미지를 빌드해 kind worker에 로드하고, 소스 mount가 없는 별도 Pod에서 64 MiB 요청의 정상 전달을 확인했습니다. 이미지 내부 Router와 worker 소스의 SHA-256이 작업 디렉터리와 일치하는지도 검사했습니다.

## 회귀 검사와 적용 상태

PD 관련 테스트 26개가 통과했습니다. 정상 응답의 본문 해제, 전송 시작 전 실패, 부분 업로드 실패, 취소, 슬롯 대기 중 취소, 시간 초과, 상태 크기 초과, HTTP 429와 슬롯 재사용을 검사했습니다. 기존 작은 Llama 모델의 출력 동등성과 Prefill/Decode 겹침 검사도 통과했습니다.

Aggregated와 Disaggregated manifest는 렌더링 후 검사 namespace로 바꾸어 Kubernetes server dry-run을 통과했습니다. `local/transformers-pd-gpu:0.1.0` 이미지는 `local-k8s-gpu-worker`에 로드했습니다. 검사 namespace와 임시 builder는 정리했고 기존 GPU 서비스는 유지했습니다. 실제 PD 추론 구성을 배포하는 방법과 한도 조정은 [비교 가이드](../../../../guides/prefill-decode.md)를 따릅니다.

수정된 코드로 GPU 전체 성능 matrix를 다시 실행하지는 않았습니다. 이전 [성능 원인 분석](../benchmark-20260930/analysis.md)과 [기존 본문 수명 수정 후 GPU 검사](../memory-fix-20260930/summary.md)는 각 측정 당시 코드의 결과로 유지합니다.

[검증 JSON](validation.json)에 소스 해시, 이미지 식별자, cgroup 지표와 Pod 상태가 있습니다. 검사 manifest, mock과 부하 스크립트, 로그는 저장소의 `reports/pd/router-memory-20261001/`에 보관합니다. 원본 경로는 Git에서 제외됩니다.
