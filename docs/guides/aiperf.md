> Korean version: [한국어](aiperf-KR.md)

# AIPerf measurement

Send concurrent load to a CPU or GPU inference server and measure throughput, TTFT, ITL, and response latency.

For automated runs, cache policy, repeated measurements, and result interpretation, see the [benchmark guide](benchmark.md).

## Default benchmark settings

The default target is the SmolLM2 Transformers server. The values below are the settings stated in this repository's Jobs.

| Setting | Source |
| --- | --- |
| Concurrency, request count, input and output lengths, seed | [AIPerf Job](../../k8s/aiperf/values.yaml) |
| Model and tokenizer revision | [Model settings](../../config/models/smollm2-135m-transformers.env) |
| Inference resources, threads, and token limits | [Deployment](../../k8s/inference/values.yaml) |
| Cluster and tool versions | [kind settings](../../config/cluster/kind.yaml), [versions.env](../../config/versions.env) |

The load generator uses the [AIPerf image](../../benchmarks/aiperf/Dockerfile) on CPU even when the inference server uses GPU. Measurement Pods keep CPU and memory `requests=limits`.

### AIPerf options and values

| Option or environment variable | Value | Description |
| --- | --- | --- |
| `--model` / `MODEL_ID` | `HuggingFaceTB/SmolLM2-135M-Instruct` | Server model name passed in requests. |
| `--url` / `API_URL` | `http://transformers-base:8000` | In-cluster inference Service address. |
| `--tokenizer` | `/tokenizer` | Local tokenizer path used for input generation and token counting. |
| `--endpoint-type`, `--streaming` | `chat`, enabled | Send chat requests with streaming to measure TTFT and ITL. |
| `--use-server-token-count` | Enabled | Use token counts returned by the server. |
| `--concurrency` / `CONCURRENCIES` | `1,2,4,8` | Measure with each value as the number of concurrently processed requests. The automated script creates a separate Job per concurrency. |
| `--sequence-distribution` | `64,32:50;256,64:50` | Generate 64 input tokens with 32 output tokens and 256 input tokens with 64 output tokens, each at 50% weight. Chat template tokens are added to inputs. |
| `--num-dataset-entries` / `DATASET_ENTRIES` | `16` | Number of synthetic dataset entries. Smaller than the request count, so entries are reused. |
| `--dataset-sampling-strategy` | `sequential` | Select dataset entries in order. |
| `--random-seed`, `--parameter-sweep-same-seed` | `42`, enabled | Fix the random seed and use the same seed for each sweep condition. |
| `--extra-inputs` | `ignore_eos:true` | Request no early stop on EOS to match the specified output length. |
| `--workers-max` | `1` | Upper bound on AIPerf load-generator workers. Concurrent requests are set with `--concurrency`. |
| `--warmup-request-count`, `--warmup-concurrency` | `2`, `1` | Before the main measurement for each concurrency condition, run 2 warmup requests at concurrency 1. |
| `--request-count` | `100` | Main measurement request count per concurrency condition; warmup requests are separate. |
| `--request-timeout-seconds` | `3600` | Per-request timeout is 3,600 seconds. |
| `--no-server-metrics` | Enabled | Disable AIPerf server metric collection. Kubernetes resource sampling by the run script is separate. |
| `--ui` | `none` | Run without an interactive UI. |
| `--artifact-dir` | `/results/$(POD_NAME)` | Job result storage path. The automated script changes it to `/results/<run-id>/c<concurrency>`. |

The AIPerf container sets CPU `1` and memory `1Gi` equally in requests and limits.

The Job limit is `activeDeadlineSeconds: 14400` and is separate from the per-request timeout. The automated script overrides the Job limit with the `--job-timeout` value, default 3,600 seconds.

The [llama.cpp profile](../../k8s/aiperf/profiles/qwen2.5.yaml) changes the model to `Qwen/Qwen2.5-0.5B-Instruct`, the address to `http://base-llamacpp:8000`, and the host tokenizer path to `/models/qwen2.5-0.5b/tokenizer`. Common load options are the same, and the automated script sets the model and address for the selected server.

## Preparing the tokenizer

Automated measurement prepares the tokenizer together. To prepare it manually, use the command for your backend.

```sh
make download-tokenizer
make download-tokenizer VARIANT=base-llamacpp
```

The server and AIPerf use tokenizers from the same model revision. Mount the tokenizer read-only at `/tokenizer` in the AIPerf Pod, and pass the same `LOCAL_K8S_MODELS_DIR` to downloads and cluster creation.

## Manifest validation

```sh
sh tests/test-aiperf-manifests.sh
```

For run error diagnosis, see [benchmark troubleshooting](benchmark.md#validation-and-troubleshooting).
