> Korean version: [한국어](prefill-decode-KR.md)

# Prefill and Decode Placement Comparison

Runs SmolLM2 on 2 MPS slots and compares aggregation with disaggregation. Both modes use the [same engine](../../src/transformer/pd/engine.py), model, FP16, greedy decoding, and batch 1 per Pod. Prefix cache and continuous batching are not used.

The [experiment index](../reports/gpu/pd/README.md) covers 2-way, 4-way, and scheduler results. The [2-way measured report](../reports/gpu/pd/benchmark-20260930/summary.md) is 1 completed workload comparison from an interrupted run.

To run 4 Aggregations with 1 Prefill and 3 Decodes separately from the existing 2-way setup, follow the [4-way PD guide](prefill-decode-4.md). Commands below default to the existing `MPS_REPLICAS=2`.

| Configuration | Aggregation | Disaggregation |
| --- | --- | --- |
| GPU Pods | 2 replicas of full inference | 1 Prefill, 1 Decode |
| GPU per Pod | `nvidia.com/gpu.shared: 1` | `nvidia.com/gpu.shared: 1` |
| Total GPU Pod resources | CPU request 2, limit 4, memory 4 GiB | Same |
| Request path | Router to one of the full inference Pods | Router to Prefill to Router to Decode |
| State transfer | In-Pod KV cache | safetensors over HTTP |

Both modes use the same single CPU router. Aggregation alternates requests across StatefulSet Pod addresses. Disaggregation can overlap the Decode of a previous request with the Prefill of the next request. Each GPU worker handles one request at a time and returns HTTP 429 past the router admission limit, including queued requests.

### Router memory limits

In the common [configuration](../../k8s/gpu-mps/pd/base/kustomization.yaml), `MAX_PENDING=8` is the request count admitted until response completion, and `MAX_STATE_TRANSFERS=2` is the request count concurrently building Prefill state and transferring it to Decode. Without a free transfer slot, a request waits before building KV. If it cannot obtain a slot within the default 120 seconds, it returns HTTP 504, and client disconnect cancels the wait. A slot returns when the Decode response header is received, so a non-streaming request can hold it until generation completes.

The per-state limit is `MAX_STATE_MIB=64`. Under default settings, source states in transfer total up to 128 MiB, and copies are also needed while converting receive buffers with `bytes`. The router uploads in 64 KiB chunks and releases body references on success, failure, and cancellation. This limit is not a whole-process RSS cap.

The [router Deployment](../../k8s/gpu-mps/pd/base/router.yaml) uses memory request 512 MiB and limit 1 GiB in both modes. After increasing state size or transfer slot count, revalidate the limit to account for transient copies, HTTP buffers, and Python memory. Rebuild and reload the inference image from changed sources, then deploy with `pd-deploy`.

## Running

Follow the [MPS guide](gpu-mps.md) to stop existing GPU workloads and free 2 MPS slots. If the `transformers-mps` example is deployed, first scale its replicas to 0. There is one physical GPU, so this is not a comparison of two independent GPUs.

```sh
make download-model
make up DEVICE=gpu GPU_SHARING=mps
make build-image load-image DEVICE=gpu GPU_SHARING=mps VARIANT=transformers-pd
make pd-deploy PD_MODE=aggregated
```

`pd-deploy` stops existing comparison workers and the router in the `pd-comparison` namespace, then deploys the selected configuration. It refuses to switch while a comparison Job is running. Result PVCs are kept. For a custom cluster, pass the same `CLUSTER_NAME` to all commands.

```sh
k() { GPU_SHARING=mps ./scripts/local-k8s-gpu.sh kubectl -n pd-comparison "$@"; }
k get pods -o wide
k port-forward service/pd-router 8000:8000
```

Check the API from another terminal. `stream: true` and `stream_options: {"include_usage": true}` are also supported.

```sh
curl -sS http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"HuggingFaceTB/SmolLM2-135M-Instruct","messages":[{"role":"user","content":"Explain what a GPU does."}],"max_tokens":32,"temperature":0,"ignore_eos":true}'
```

Switch to the disaggregated configuration. Rerun port-forward after the router restarts.

```sh
make pd-deploy PD_MODE=disaggregated
```

The default image tag is stated in the manifests. After changing `IMAGE_TAG`, also change the Kustomize `images` setting in each overlay.

## Automatic comparison over multiple workloads

The [workload configuration](../../config/benchmarks/pd.json) defines the full input and output length combinations, mixed load, concurrency, request count, and repetition count. Defaults are 9 combinations of inputs `64,256,704` with outputs `16,64,256` plus mixed load, at concurrencies `1,2,4,8` with 3 repetitions. Chat template tokens are added, so verify actual input length in the response `usage`.

Prepare the MPS cluster and inference image first. The runner needs Python PyYAML, and figure generation needs matplotlib.

```sh
make build-benchmark-image load-benchmark-image DEVICE=gpu GPU_SHARING=mps
make pd-benchmark
# Custom cluster or workload configuration
python3 scripts/benchmark-pd.py --cluster local-k8s-gpu-mps --config config/benchmarks/pd.json
```

The [runner](../../scripts/benchmark-pd.py) switches both modes sequentially and runs AIPerf sweeps. It alternates A-to-D and D-to-A order per repetition. It stops on inference Pod restarts, request errors, output length mismatch, or payload hash or actual input and output distribution mismatch between modes. Warmup is excluded from measurement statistics.

Saves summary JSON and CSV to `docs/reports/gpu/pd/pd-<timestamp>/`, and per-request AIPerf exports, deployment settings, GPU samples, and logs to `reports/pd/pd-<timestamp>/`. Raw sources are excluded from Git. After completion, generate tables and figures from the report directory printed by the runner.

```sh
python3 scripts/report-pd.py docs/reports/gpu/pd/pd-<timestamp>
```

To report only repetitions that finished all workloads in both modes from an interrupted run, add `--completed-only`. It keeps the original run failure state and aggregates only selected repetitions into `completed-summary.json` and `completed-summary.csv`. The report also shows the original repetition plan and actual completion count.

Throughput and mean latency are arithmetic means of per-repetition metrics, and standard deviation is the sample SD across repetitions. p95 is the nearest-rank over all repeated requests under the same condition. TTFT and ITL use streaming responses and include TextStreamer word-buffer effects. To compare small differences or tail latency precisely, increase request and repetition counts in the workload configuration.

For report generation, SLO-based goodput analysis, and Git retention files, see the [experiment results guide](experiment-results.md).

The runner uses the existing cluster and does not create clusters or stop external GPU workloads. After completion it keeps the last mode's inference Pods and cleans up created Jobs and result-reader Pods. Result PVCs are kept. The existing `make benchmark` and `make benchmark-suite` are for exclusive-GPU measurement.

### Manual measurement of a single distribution

Change `--sequence-distribution` in the [dedicated AIPerf Job](../../k8s/gpu-mps/pd/benchmark.yaml) to the wanted distribution, deploy the mode to compare, then run it. For example, `704,16:100` is long-input, short-output load.

```sh
k() { GPU_SHARING=mps ./scripts/local-k8s-gpu.sh kubectl -n pd-comparison "$@"; }
k delete job pd-benchmark --ignore-not-found
k apply -f k8s/gpu-mps/pd/benchmark.yaml
k wait --for=condition=complete job/pd-benchmark --timeout=14400s
k logs job/pd-benchmark
k apply -f k8s/gpu-mps/pd/results.yaml
k wait --for=condition=Ready pod/pd-results --timeout=120s
k cp pd-results:/results reports/pd-manual
```

## State transfer and metrics

Prefill transfers the full-prompt KV cache and last-position logits. Decode selects the first output token from the logits, then forwards one token at a time. It rejects transfers when the two workers' model file, tokenizer, dtype, or context setting fingerprints differ, or when state tensor shapes differ. The transfer format uses the [safetensors bytes API](https://huggingface.co/docs/safetensors/api/torch), and cache positions follow [Transformers cache rules](https://huggingface.co/docs/transformers/v4.57.1/cache_explanation).

JSON responses in `metrics`, SSE terminal chunks in `metrics`, and worker `pd_request` JSON logs contain the following values. Time units are ms.

| Metric | Scope |
| --- | --- |
| `prefill_queue_ms`, `decode_queue_ms` | Time waiting for each worker's single execution thread |
| `state_queue_ms` | Router state-transfer slot wait time, recorded in disaggregated mode |
| `prefill_ms` | Input tensor preparation and prefill forward plus CUDA completion wait |
| `decode_ms` | From first-token selection to generation end, including text conversion |
| `decode_first_token_ms` | From decode loop start to first-token selection |
| `export_ms`, `import_ms` | CPU copy and serialization of KV and logits, plus deserialization and GPU copy |
| `prefill_rpc_ms` | From Prefill request start at the router to state receive completion |
| `state_receive_ms` | Time Decode spent reading the HTTP request body |
| `kv_bytes`, `state_bytes` | Pure KV tensor size, and total transferred state size |

`prefill_rpc_ms` includes waiting, tokenization, compute, export, and HTTP transfer, so do not add it to `prefill_ms` and related metrics. `state_receive_ms` also does not represent whole-transfer-path latency. Judge actual transfer cost with client TTFT and end-to-end latency. Aggregation transfer metrics are 0, with no RPC or receive metrics.

This implementation measures HTTP KV transfer through CPU memory. Do not directly compare it with systems using NVLink, RDMA, or CUDA IPC. Currently only Llama-structured SmolLM2 is supported. Mamba and Jamba recurrent state and llama.cpp GGUF transfer are not included.

## Configuration and verification

- Common token and queue limits: [base/kustomization.yaml](../../k8s/gpu-mps/pd/base/kustomization.yaml)
- GPU resources, model mounts, and roles: [aggregation workers](../../k8s/gpu-mps/pd/aggregated/workers.yaml), [disaggregation workers](../../k8s/gpu-mps/pd/disaggregated/workers.yaml)
- Engine, internal API, and router: [src/transformer/pd](../../src/transformer/pd)

A small Llama model in a CPU environment can also verify state transfer and output equivalence.

```sh
python -m pip install torch==2.10.0 --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r src/transformer/requirements.txt -r src/transformer/pd/requirements.txt pyyaml
python -m unittest discover -s tests -p 'test_pd*.py' -v
kubectl kustomize k8s/gpu-mps/pd/aggregated
kubectl kustomize k8s/gpu-mps/pd/disaggregated
```

After copying results to the host, shut down. Deleting the namespace also deletes result PVCs.

```sh
k delete namespace pd-comparison
make down DEVICE=gpu GPU_SHARING=mps
```
