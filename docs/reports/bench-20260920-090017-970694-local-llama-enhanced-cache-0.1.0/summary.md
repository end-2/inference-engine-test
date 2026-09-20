# AIPerf CPU benchmark

- Image: `local/llama-enhanced-cache:0.1.0`
- Image ID: `sha256:0bf4b86be3de5000cb50eb88d18752978a95525f7291a2f46a9c7370e2a55f3f`
- Started (UTC): 2026-09-20T09:00:17.970694+00:00
- Status: complete
- PVC cache policy: `clear-per-concurrency` (before each condition's warmup).
- Each condition starts after a fresh inference Pod becomes ready, followed by the configured warmup.

| Concurrency | Requests | Output tok/s | TTFT avg (ms) | TTFT p95 (ms) | ITL avg (ms) | ITL p95 (ms) | Decode avg (ms) | Decode p95 (ms) | Prefill tok/s/user | Latency avg (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 100.00 | 94.50 | 106.83 | 443.73 | 8.22 | 10.67 | 335.71 | 579.02 | 13251.99 | 442.54 |
| 2 | 100.00 | 95.50 | 548.55 | 1855.91 | 7.89 | 9.53 | 325.96 | 583.93 | 449.14 | 874.50 |
| 4 | 100.00 | 96.44 | 1400.32 | 3388.12 | 7.83 | 9.40 | 323.22 | 543.32 | 140.38 | 1723.54 |
| 8 | 100.00 | 97.35 | 3039.13 | 6970.53 | 7.87 | 9.41 | 319.83 | 535.43 | 60.79 | 3358.96 |

Raw AIPerf exports, request CSV, resource JSONL/CSV, and logs are under each `c<concurrency>/` directory.
`run.json` and the saved manifests record image IDs, Pod UIDs, and workload settings.

## 실행 조건

```sh
make benchmark VARIANT=enhanced-cache CACHE_POLICY=clear-per-concurrency INFERENCE_CONTEXT=
```

`INFERENCE_CONTEXT=`로 기존 추론 이미지를 재사용했습니다. Concurrency 1·2·4·8마다 워밍업 2회와 본 측정 100회를 실행했으며, 본 측정 400회 모두 성공했고 출력 길이 부족·초과는 없었습니다. 추론 Pod 4개의 UID는 모두 다르고 QoS는 Guaranteed입니다.

입출력 분포, 데이터셋 16개, seed 42, warmup, 요청 수와 CPU·메모리 설정은 이전 실행과 같습니다. 추론 Pod는 12 CPU·16 GiB, AIPerf는 1 CPU·1 GiB이며 requests와 limits가 같습니다.

## PVC cache 초기화 검증

각 조건의 워밍업 전에 추론 Pod 종료와 cache flush를 기다린 뒤 `/cache` 내용을 삭제했습니다. PVC는 유지했습니다. 삭제 기록은 각 `c*/cache-clear.json`과 `run.json`에 있습니다.

| Concurrency | 삭제 파일 수 | 삭제 크기 (MiB) | 삭제 후 항목 수 |
| --- | ---: | ---: | ---: |
| 1 | 1 | 0.00 | 0 |
| 2 | 19 | 32.85 | 0 |
| 4 | 19 | 32.85 | 0 |
| 8 | 19 | 32.85 | 0 |

첫 조건은 새 PVC의 빈 lock 파일만 삭제했습니다. 이후 조건에서는 직전 단계에서 저장한 cache를 삭제했습니다. 워밍업과 본 측정 안에서 cache는 다시 채워져 재사용되므로 모든 요청을 cache miss로 만드는 실험은 아닙니다.

## 이전 cache 보존 실행과 비교

[이전 결과](../bench-20260919-172027-036026-local-llama-enhanced-cache-0.1.0/summary.md)와 비교한 값입니다. 변화율은 `(이번 / 이전 - 1) × 100`입니다.

| Concurrency | 보존 Output tok/s | 초기화 Output tok/s | 처리량 변화 | 보존 TTFT avg (ms) | 초기화 TTFT avg (ms) |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 103.21 | 94.50 | -8.4% | 106.21 | 106.83 |
| 2 | 138.85 | 95.50 | -31.2% | 311.44 | 548.55 |
| 4 | 144.59 | 96.44 | -33.3% | 865.25 | 1400.32 |
| 8 | 142.90 | 97.35 | -31.9% | 1985.35 | 3039.13 |

이 실행에서는 concurrency 2·4·8의 처리량이 이전보다 약 31~33% 낮고 TTFT 평균이 높았습니다. 단, 이전은 1노드이고 이번은 4노드이며 기존 availability/HPA 워크로드가 함께 배포된 상태입니다. 이번 추론 Pod는 `local-k8s-worker`, AIPerf는 `local-k8s-worker2`에 배치됐습니다. 같은 Docker VM의 15 CPU·약 24 GiB를 공유하며 노드가 늘었다고 물리 자원이 늘어난 것은 아닙니다.

추론 이미지 ID는 이전과 동일합니다. AIPerf는 같은 0.12.0 버전과 같은 Dockerfile 소스 해시로 재빌드되어 이미지 ID가 다릅니다. 각 실행은 1회이므로 위 차이를 PVC cache 초기화만의 효과로 단정할 수 없습니다.

- 이전 AIPerf 이미지 ID: `sha256:903ad977cf6f8ca82d18fc978436414fd1d7434a26ec87f2bab7dbcdf18c36fc`
- 이번 AIPerf 이미지 ID: `sha256:e916ca4e164739cd9a0d334faf73ea02dbb5f98aa77000ead84ab50ac7df8371`
