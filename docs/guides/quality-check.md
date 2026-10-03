> Korean version: [한국어](quality-check-KR.md)

# Quick Response Quality Check

Checks inference server response quality with 7 representative questions. The [quality check script](../../scripts/check-quality.py) sends questions sequentially and saves responses, check criteria, and verdicts as JSON.

SmolLM2 uses English questions, and Qwen uses Korean questions. Do not compare English and Korean pass counts as the same quality score.

## Running

The target is a running server that serves `/v1/chat/completions`. The script uses only the Python 3 standard library and runs against the shared API of base, enhanced-batch, and enhanced-cache.

The Docker and kind example below prepares a SmolLM2 base server and connects it to local port 8000. Run from the repository root.

```sh
./scripts/local-k8s.sh install
make download-model VARIANT=transformers-base
make up
make build-image load-image VARIANT=transformers-base
./scripts/k8s.sh apply k8s/inference/profiles/transformers-base-cpu.yaml
./scripts/local-k8s.sh kubectl rollout status deployment/transformers-base --timeout=300s
```

```sh
./scripts/local-k8s.sh kubectl port-forward service/transformers-base 8000:8000
```

From another terminal, run relative to the repository root.

```sh
python3 scripts/check-quality.py --output reports/transformers/quality-base.json
```

Use `--url` and `--model` to select the server and model. Defaults are `http://127.0.0.1:8000` and SmolLM2, and `API_SERVER_URL` and `SERVED_MODEL_NAME` also change them. To pin the language, use `--language en` or `--language ko`.

For a llama.cpp server, connect a port to that service, then run `python3 scripts/check-quality.py --backend llamacpp`. The default model is Qwen2.5.

The default output cap is 128 tokens, and the per-request timeout is 60 seconds. Change them with `--max-tokens` and `--timeout`, keeping the output cap within the server limit.

Without `--output`, it saves to `reports/<backend>/quality-<UTC timestamp>.json`. Specifying an existing path overwrites it.

## Check items and verdicts

| Item | Verification |
| --- | --- |
| Instruction following | Automatically checks whether the answer contains `PASS` |
| Simple calculation | Automatically checks whether `17 + 25` is answered as `42` |
| Information extraction | Automatically checks whether the given order number is answered exactly |
| JSON content | Automatically checks whether `name` is `Mina` and `count` is 3 |
| Conversation context | Automatically checks whether it answers the earlier cat name |
| Summary | Human checks whether key facts are preserved in the selected language |
| English rephrasing or Korean translation | English checks plain-English rephrasing, and Korean checks meaning preservation in translation, by human review |

The question set and decision criteria are recorded in the result's `language`, `criterion`, and `answer`. Automatic checks verify answer content, and ambiguous summary, translation, and judgment responses remain `REVIEW`. For `REVIEW`, a human compares the response against the criterion.

Output distinguishes `PASS`, `FAIL`, `REVIEW`, and `ERROR`. Failed automatic checks are `FAIL`, while HTTP errors, malformed API responses, empty responses, and output-cap truncation are `ERROR`.

It still runs the remaining questions after one item fails, then saves results. The exit code is 1 with any `FAIL` or `ERROR`, and 0 otherwise. Even with exit code 0, manually review `REVIEW` items.

Requests use `temperature=0`, `top_p=1`, and `ignore_eos=false`. Since normal termination is allowed, conditions differ from fixed-output-length performance measurement.

This check confirms basic responses and does not guarantee an overall quality score or quality equivalence across implementations.

## Script verification

Without a model, a local test server checks handling of normal responses, wrong answers, API errors, and output truncation.

```sh
python3 -m unittest discover -s tests -p 'test_quality_check.py'
```
