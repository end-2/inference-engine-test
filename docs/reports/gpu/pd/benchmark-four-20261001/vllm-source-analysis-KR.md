# vLLM에서 Prefill/Decode 분리가 TTFT에 미치는 영향

vLLM에서는 Prefill/Decode 분리가 TTFT와 TTFT goodput을 개선할 수 있습니다. Decode가 사용하는 토큰 예산과 실행 요청 용량으로 인해 prefill이 대기한다면, prefill 전용 인스턴스가 그 대기를 줄일 수 있습니다. 다만 클라이언트 TTFT 개선은 KV 전송과 decode 진입 비용을 포함해 판단해야 합니다. 기존 Transformers 기반 결과만으로 vLLM의 우열을 예측할 수 없습니다.

분석 기준은 2026-10-02에 확인한 [vLLM v0.30.0 릴리스](https://github.com/vllm-project/vllm/releases/tag/v0.30.0), commit `ced6857afa0ea7b2e3f0846a62e1394e90f15607`입니다. V1의 기본 scheduler와 NIXL 예제 proxy를 읽었습니다. vLLM을 배포하거나 GPU 성능 측정을 실행한 결과가 아닙니다.

## 소스에서 확인한 스케줄링 순서

[Scheduler.schedule](https://github.com/vllm-project/vllm/blob/ced6857afa0ea7b2e3f0846a62e1394e90f15607/vllm/v1/core/sched/scheduler.py#L561-L665)는 각 step의 token budget을 설정하고 `self.running`을 먼저 순회합니다. 요청마다 아직 계산하지 않은 토큰 수를 구하고 남은 예산으로 제한합니다. [예산 차감 후 WAITING 처리](https://github.com/vllm-project/vllm/blob/ced6857afa0ea7b2e3f0846a62e1394e90f15607/vllm/v1/core/sched/scheduler.py#L801-L865)로 넘어가며, [새 요청의 prefill도 남은 예산으로 제한](https://github.com/vllm-project/vllm/blob/ced6857afa0ea7b2e3f0846a62e1394e90f15607/vllm/v1/core/sched/scheduler.py#L1035-L1080)합니다.

따라서 진행 중인 decode를 유지하면서 새 prefill을 남은 예산에 배치한다는 이해는 맞습니다. 다만 V1은 prefill과 decode를 별도 phase queue로 분리하지 않습니다. 진행 중인 chunked prefill도 RUNNING에 들어갑니다. 모든 decode가 모든 부분 prefill보다 항상 먼저 실행된다는 보장은 아닙니다. [상위 프로젝트 테스트](https://github.com/vllm-project/vllm/blob/ced6857afa0ea7b2e3f0846a62e1394e90f15607/tests/v1/core/test_scheduler.py#L537-L588)에서도 partial prefill과 decode가 함께 RUNNING에 남는 것을 확인할 수 있습니다. 테스트 소스를 검토했으며 이 테스트를 실행하지는 않았습니다.

[AsyncScheduler](https://github.com/vllm-project/vllm/blob/ced6857afa0ea7b2e3f0846a62e1394e90f15607/vllm/v1/core/sched/async_scheduler.py#L12-L31)도 이 Scheduler를 상속하며 `schedule()`의 기본 순서를 대체하지 않습니다. Speculative decoding, pipeline parallelism과 prefill throttling 같은 추가 조건은 단순한 decode 1토큰 모델을 바꿀 수 있습니다.

## 구분해야 하는 세 가지 제한

| 제한 | 소스의 의미 | Prefill 대기에 미치는 영향 |
| --- | --- | --- |
| 토큰 예산 | `max_num_batched_tokens`, `max_num_scheduled_tokens` | 실행 중인 요청을 처리하고 남은 토큰 수만큼 prefill chunk를 넣음 |
| 실행 요청 수 | `max_num_seqs` | RUNNING 용량이 차면 토큰 예산이 남아도 새 요청을 받지 못함 |
| KV cache 공간 | `allocate_slots()` | 필요한 KV block이 부족하면 새 요청이 들어가지 못함 |

[설정 정의](https://github.com/vllm-project/vllm/blob/ced6857afa0ea7b2e3f0846a62e1394e90f15607/vllm/config/scheduler.py#L49-L72), [요청 수 제한](https://github.com/vllm-project/vllm/blob/ced6857afa0ea7b2e3f0846a62e1394e90f15607/vllm/v1/core/sched/scheduler.py#L858-L865), [KV 할당의 전체 입력 길이 검사](https://github.com/vllm-project/vllm/blob/ced6857afa0ea7b2e3f0846a62e1394e90f15607/vllm/v1/core/kv_cache_manager.py#L508-L524)에 근거합니다. 여기서 slot은 물리 GPU 개수나 GPU 실행 시간 단위와 동일하지 않습니다.

예를 들어 speculative decoding과 진행 중인 partial prefill이 없고, 토큰 예산 512, decode 요청 128개, 충분한 실행 요청 용량과 KV 공간을 가정하면 decode가 각 1토큰을 사용한 뒤 새 prefill에 최대 384토큰을 배정할 수 있습니다. Prefill 전용 인스턴스는 그 128토큰 차감을 피할 수 있습니다. 이는 배정 토큰 수를 설명하는 예시이며 실제 TTFT 개선율이 아닙니다. Prefill과 decode의 토큰당 연산 비용은 다릅니다.

## 분리할 때 TTFT가 좋아질 수 있는 조건

다음은 소스 동작으로부터의 추론입니다.

- Aggregation에서 decode 부하가 지속되어 새 요청의 admission이나 prefill chunk 진행이 지연됩니다.
- ITL을 지키기 위해 aggregation의 token budget을 작게 유지해야 합니다. 분리 후 P에는 큰 prefill batch를 허용하고 D에는 decode에 맞춘 설정을 사용할 수 있습니다.
- P의 처리 용량이 새 요청의 입력 토큰 유입량을 감당하고, D에도 KV를 받아 첫 출력을 시작할 여유가 있습니다.
- 줄어든 대기와 prefill 시간이 KV 전달 및 추가 proxy 처리 비용보다 큽니다.

[vLLM 튜닝 문서](https://github.com/vllm-project/vllm/blob/ced6857afa0ea7b2e3f0846a62e1394e90f15607/docs/configuration/optimization.md#L49-L67)도 작은 token budget은 ITL에, 큰 token budget은 TTFT에 유리한 방향을 설명합니다. [분리 기능 문서](https://github.com/vllm-project/vllm/blob/ced6857afa0ea7b2e3f0846a62e1394e90f15607/docs/features/disagg_prefill.md#L8-L16)는 TTFT와 ITL을 각각 조정할 수 있는 점을 목적에 포함합니다. 따라서 비교 기준은 한쪽의 특정 설정 하나보다 같은 자원과 부하에서 각 mode가 달성하는 TTFT/ITL 조합이어야 합니다.

## Prefill 완료 시간과 클라이언트 TTFT

[NIXL 테스트 proxy](https://github.com/vllm-project/vllm/blob/ced6857afa0ea7b2e3f0846a62e1394e90f15607/tests/v1/kv_connector/nixl_integration/toy_proxy_server.py#L155-L197)는 P에 `max_tokens=1`, `stream=False`로 요청합니다. [후속 처리](https://github.com/vllm-project/vllm/blob/ced6857afa0ea7b2e3f0846a62e1394e90f15607/tests/v1/kv_connector/nixl_integration/toy_proxy_server.py#L219-L251)는 P 응답의 KV 전달 정보를 D에 넘기고, D에서 받은 응답을 클라이언트에 stream합니다. P가 생성한 토큰을 즉시 클라이언트에 전달하는 구조가 아닙니다.

이 proxy 경로를 단순화한 시간 구성은 다음과 같습니다. 겹쳐 실행된 구간은 중복해서 더하지 않습니다.

```text
Aggregation TTFT ≈ A 대기 + 혼합 배치에서의 prefill 경과 시간 + 응답 전달
Disaggregation TTFT ≈ P 대기와 prefill + KV 전달 경로의 노출 지연
                      + D 진입과 첫 출력 생성 + proxy/응답 전달
```

[KV connector 실행 경로](https://github.com/vllm-project/vllm/blob/ced6857afa0ea7b2e3f0846a62e1394e90f15607/vllm/v1/worker/kv_connector_model_runner_mixin.py#L76-L103)는 비동기 KV 수신 완료를 scheduler에 알립니다. D의 해당 요청은 그 전까지 `WAITING_FOR_REMOTE_KVS` 상태로 계산을 기다립니다. [수신 완료 처리](https://github.com/vllm-project/vllm/blob/ced6857afa0ea7b2e3f0846a62e1394e90f15607/vllm/v1/core/sched/scheduler.py#L2951-L2977)는 요청을 다시 WAITING으로 돌리며, 전체 prompt KV가 맞아도 다음 토큰 sampling을 위해 마지막 prompt 토큰을 재계산하는 경로가 있습니다. KV가 도착한 것만으로 첫 출력이 클라이언트에 도착하지는 않습니다.

다른 proxy가 P의 첫 토큰을 먼저 전달한다면 TTFT의 경계도 달라집니다. 이 경우 KV handoff 지연이 첫 토큰과 두 번째 토큰 사이에 나타날 수 있으므로 실제 토큰 간격도 함께 측정해야 합니다.

## 기존 벤치마크와 달라지는 점

현재 [서버](../../../../../src/huggingface/llama/inference_distributed/server.py)는 `ThreadPoolExecutor(max_workers=1)`로 GPU 작업을 실행하고, [decode loop](../../../../../src/huggingface/llama/inference_distributed/engine.py)는 한 요청의 생성이 끝날 때까지 계속 실행합니다. 요청별 batch 1이며 vLLM처럼 여러 요청을 매 step에 섞지 않습니다. 따라서 기존 TTFT 차이는 요청 단위 직렬 대기, worker 수와 HTTP 상태 전달 경로의 영향을 포함하며, vLLM의 chunked prefill token budget 경쟁을 측정한 결과가 아닙니다.

vLLM으로 바꾸면 A와 D 양쪽 모두 요청을 연속 배치할 수 있으므로 기존 수치를 그대로 적용할 수 없습니다. 특히 decode 요청이 있다는 이유만으로 새 prefill이 그 요청의 전체 출력 완료까지 기다리는 것은 아닙니다.

현재 부하는 동시성 최대 8, 실제 입력 최대 734토큰입니다. 예를 들어 budget 2,048에서 decode가 최대 8개라면 순수 decode가 소비하는 예산은 step당 약 8토큰이므로, decode 우선 정책에 의한 토큰 예산 감소만으로 큰 TTFT 차이가 생긴다고 보기는 어렵습니다. 여러 prefill의 동시 진입, 실행 요청 수 제한, KV 부족이나 실제 mixed-batch 실행 시간이 지배할 가능성은 별도로 확인해야 합니다. v0.30.0의 일반 GPU API server 기본값 경로는 [EngineArgs](https://github.com/vllm-project/vllm/blob/ced6857afa0ea7b2e3f0846a62e1394e90f15607/vllm/engine/arg_utils.py#L2750-L2759)에 있지만 실제 실험에서는 값을 명시하고 실행 설정을 기록해야 합니다.

또한 현재 MPS 25% active-thread 제한은 전용 GPU 4개와 같지 않습니다. [NVIDIA MPS 설명](https://docs.nvidia.com/deploy/mps/when-to-use-mps.html#dynamic-execution-resource-provisioning)에 따르면 이 제한은 각 client의 사용량 상한이며 전용 자원을 예약하지 않습니다. P/D를 다른 프로세스로 나눠도 물리 GPU 자원 간섭이 완전히 사라지는 조건은 아닙니다. P 1개에 입력 부하가 집중되는 손해와 D 3개의 처리 용량도 함께 평가해야 합니다.

## vLLM 비교 실험에서 확인할 항목

기존 A4와 P1D3의 자원 예산을 유지하면서 다음을 함께 비교하면 가설을 구분할 수 있습니다.

1. A의 token budget을 여러 값으로 바꾸고, D는 P와 D의 budget을 따로 조정합니다. 예시 탐색값은 256, 512, 1,024, 2,048이며 실행 가능한 메모리 범위에 한합니다. 한쪽에 불리한 설정 하나로 결론 내리지 않습니다.
2. `max_num_seqs`, 실제 KV cache 크기, prefix-cache hit 비율, speculative decoding 설정을 기록합니다. 서로 같은 SLO와 총 자원 예산에서 비교합니다.
3. 현재 부하와 함께 decode가 지속되는 중에 긴 입력이 도착하는 부하를 측정합니다. 고정 동시성과 별도로 동일 도착률에서 요청 수를 충분히 늘려 대기열 영향을 봅니다.
4. 클라이언트 TTFT, 요청별 평균 TPOT, 개별 토큰 간격, P 완료, KV 수신 완료, D 첫 출력 시간을 분리해 수집합니다.
5. TTFT-only, TPOT-only와 두 기준의 교집합 goodput을 계산하고 충족률을 함께 보고합니다. 개선 여부는 클라이언트 기준 goodput으로 판단합니다.

vLLM 자체의 [metrics 계산](https://github.com/vllm-project/vllm/blob/ced6857afa0ea7b2e3f0846a62e1394e90f15607/vllm/v1/metrics/stats.py#L460-L504)은 첫 출력 지연과 후속 출력 간격을 별도로 기록합니다. [prefill_time](https://github.com/vllm-project/vllm/blob/ced6857afa0ea7b2e3f0846a62e1394e90f15607/vllm/v1/metrics/stats.py#L540-L560)은 최초 SCHEDULED부터 첫 토큰까지의 경과 시간으로, 순수 GPU prefill 연산 시간과 다릅니다. D 인스턴스의 TTFT도 D에 들어온 시점부터 계산되므로 P와 proxy를 포함하는 클라이언트 TTFT의 대용으로 사용하지 않습니다.
