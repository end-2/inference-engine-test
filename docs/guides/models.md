> Korean version: [한국어](models-KR.md)

# Local Model Management

Downloads SmolLM2-135M-Instruct and Qwen2.5-0.5B-Instruct and verifies SHA-256 checksums. Models are stored on the host and mounted read-only into kind nodes and Pods.

Downloads need `curl`, internet access, and `sha256sum` or `shasum`. For disk and runtime resources, see [requirements](requirements.md#cpu-memory-and-disk).

## Models and configuration

The default `VARIANT` for `make` is `transformers-base`. Model IDs and revisions are pinned in each configuration file.

| Model | Execution engine or purpose | Download configuration and checksums |
| --- | --- | --- |
| `HuggingFaceTB/SmolLM2-135M-Instruct` | Transformers | [Configuration](../../config/models/smollm2-135m-transformers.env), [per-file SHA-256](../../config/models/smollm2-135m-transformers.sha256) |
| `Qwen/Qwen2.5-0.5B-Instruct-GGUF`, Q4_K_M | llama.cpp | [Configuration and GGUF SHA-256](../../config/models/qwen2.5-0.5b-gguf-llamacpp.env) |
| `Qwen/Qwen2.5-0.5B-Instruct` | AIPerf tokenizer | [Configuration](../../config/models/qwen2.5-0.5b-tokenizer-llamacpp.env), [per-file SHA-256](../../config/models/qwen2.5-0.5b-tokenizer-llamacpp.sha256) |

## Download

Run the command for the model to use from the repository root. `make benchmark` and `make benchmark-suite` automatically download and verify the selected backend.

### SmolLM2-135M-Instruct

The default model, run with Transformers.

```sh
make download-model
# Direct script: ./scripts/download-transformers-model.sh
```

Downloads weights, configuration, and tokenizer together. `make download-tokenizer` runs the same script, so skip it if the model is already prepared.

### Qwen2.5-0.5B-Instruct

The Q4_K_M GGUF model, run with llama.cpp.

```sh
make download-model VARIANT=base-llamacpp
make download-tokenizer VARIANT=base-llamacpp
# Direct scripts:
# ./scripts/download-model-llamacpp.sh
# ./scripts/download-tokenizer-llamacpp.sh
```

The inference server uses the GGUF file. AIPerf benchmarks need a separate tokenizer. `enhanced-batch-llamacpp` and `enhanced-cache-llamacpp` use the same model.

### Verification and retries

All download scripts verify SHA-256 checksums of new and existing files. If interrupted, rerun the same command.

- Qwen GGUF and SmolLM2 downloads resume partial files.
- SmolLM2 model and Qwen tokenizer downloads reuse verified files in a temporary directory, then move them to the final directory after full-file verification. Incomplete tokenizer files are downloaded again.
- A failed verification of an existing file does not overwrite it automatically. Move the GGUF file or model and tokenizer directories shown in the error aside, then rerun.

## Cluster and volume connections

After preparing models, create the cluster. For cluster tool installation and configuration, see the [cluster guide](local-k8s.md).

```sh
make up
```

`up` bind-mounts the host model root (default: `.models/` in the repository) read-only to `/models` when creating nodes. Pod `hostPath` entries point to paths inside kind nodes.

| Purpose | Host directory | kind node directory | Pod mount path |
| --- | --- | --- | --- |
| SmolLM2 inference | `.models/smollm2-135m/` | `/models/smollm2-135m/` | `/model/` |
| SmolLM2 AIPerf tokenizer | `.models/smollm2-135m/` | `/models/smollm2-135m/` | `/tokenizer/` |
| Qwen2.5 inference | `.models/qwen2.5-0.5b/` | `/models/qwen2.5-0.5b/` | `/model/` |
| Qwen2.5 AIPerf tokenizer | `.models/qwen2.5-0.5b/tokenizer/` | `/models/qwen2.5-0.5b/tokenizer/` | `/tokenizer/` |

The Transformers server uses `--model /model`, and the llama.cpp server uses `--model /model/qwen2.5-0.5b-instruct-q4_k_m.gguf`.

For the actual volume configuration, see the [Transformers Deployment](../../k8s/transformers-base/deployment.yaml), [llama.cpp Deployment](../../k8s/base-llamacpp/deployment.yaml), and [AIPerf guide](aiperf.md). For how to run servers, see the [inference engine guide](inference-engine.md).

### Changing the storage location

To use another disk, pass the same `LOCAL_K8S_MODELS_DIR` to downloads and cluster creation. Use the same value for later `up` and benchmark runs. Relative paths resolve against the command working directory, and colons are not allowed in the path.

```sh
export LOCAL_K8S_MODELS_DIR=/path/to/models
make download-model
make up
```

For Qwen2.5, pass `VARIANT=base-llamacpp` to download commands and prepare the tokenizer under the same model root.

If the existing cluster has no mount or a different path, `up` reports an error. Back up needed data such as node-internal PVCs, then recreate. The host model directory is not deleted.

```sh
make down
make up
```

## Qwen2.5 GGUF mount verification

The [check Job](../../config/models/qwen2.5-0.5b-check-llamacpp.yaml) verifies Qwen GGUF file presence and read-only mounts as a non-root user. It runs without inference libraries and is deleted 5 minutes after completion. If the image is missing, it is downloaded on first run. This Job does not verify the SmolLM2 model or inference behavior.

```sh
job=$(./scripts/local-k8s.sh kubectl create -f config/models/qwen2.5-0.5b-check-llamacpp.yaml -o name)
./scripts/local-k8s.sh kubectl wait --for=condition=Complete "$job" --timeout=180s
./scripts/local-k8s.sh kubectl logs "$job"
```

## Troubleshooting

- `hostPath type check failed`: check that the selected model download finished and that `/models` is mounted. It uses `Directory`, so it does not create a wrong path as an empty directory.
- `Permission denied`: model directories need search permission, and files need read permission. Download scripts create new files and directories with `umask 022`.
- `Checksum mismatch` or `Missing file or checksum mismatch`: move the existing file or directory shown in the error aside, then run the same download command.
