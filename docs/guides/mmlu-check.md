> Korean version: [한국어](mmlu-check-KR.md)

# MMLU accuracy check

`make mmlu-check` runs English MMLU evaluation in a Kubernetes Job against a running `/v1/chat/completions` server. The evaluator scores generated A, B, C, or D answers and supports the shared API used by Transformers, llama.cpp, and Mamba.

This check uses the server's chat template and generated answers. The [original MMLU evaluator](https://github.com/hendrycks/test/blob/master/evaluate.py) ranks choice log probabilities. Report these results as `generated-choice-v1`, with the shot count and selected subjects, rather than equating them with published MMLU scores.

## Run

Prepare the cluster and server using the [inference engine guide](inference-engine.md) or reuse the server left by a benchmark. Docker, Python 3.10 or later, and the repository's installed kubectl, kind and Helm are required. The Job uses cluster service DNS, so port forwarding is unnecessary.

From the repository root, download the [official dataset](https://github.com/hendrycks/test) and check ten questions in one subject:

```sh
make mmlu-check MMLU_ARGS='--download-data --subjects abstract_algebra --limit 10'
```

The [runner](../../scripts/run-mmlu.py) builds and loads the Python evaluator image, creates a PVC and transfer Pod, copies the selected dataset files to the PVC, then starts the [evaluation Job](../../k8s/mmlu/values.yaml). Evaluation requests and scoring run in that Job. After completion, the runner copies results and logs to the host and deletes the Job, transfer Pod and PVC. The inference server remains running.

`--download-data` downloads the official archive on the host only when the data directory is absent, retaining test and dev CSV files in `.datasets/mmlu/`. Existing data is reused across runs. Initial dataset and image downloads need internet access; the evaluation Pod needs only access to the inference service. For offline data, pass `--data-dir /path/to/data`, containing `test/<subject>_test.csv` and, for examples, `dev/<subject>_dev.csv`. CSV files have no header and six columns: question, four choices, and answer letter.

Run all test questions or select a server and quality threshold:

```sh
make mmlu-check
make mmlu-check VARIANT=base-llamacpp MMLU_ARGS='--subjects abstract_algebra --limit 10'
make mmlu-check DEVICE=gpu MMLU_ARGS='--subjects abstract_algebra --limit 10'
make mmlu-check MMLU_ARGS='--url http://my-server:8000 --model my-model --min-accuracy 0.3'
make mmlu-check MMLU_ARGS='--few-shot 5 --output docs/reports/transformers/mmlu-base.json'
```

`VARIANT` selects the backend's default service and model through [inference.json](../../benchmarks/inference.json). Deploy the requested implementation before evaluation. `DEVICE` selects the CPU or GPU cluster. For another service, set `--url` to an address reachable from the Pod and `--model` to its served model name. `127.0.0.1` refers to the evaluation Pod itself. Environment variables `API_SERVER_URL` and `SERVED_MODEL_NAME` also set these values.

## Evaluation conditions

| Option | Behavior |
| --- | --- |
| `--subjects NAME [NAME ...]` | Selected subjects; otherwise all available test CSV files |
| `--limit N` | Sample at most N questions per subject; otherwise all questions |
| `--seed N` | Sampling seed, default 0; a subject's selection stays stable when other subjects change |
| `--few-shot N` | First N dev examples from the same subject, from 0 to 5; default 0 |
| `--max-tokens N` | Output cap, default 16 |
| `--timeout SECONDS` | Per-request timeout, default 60 |
| `--min-accuracy FRACTION` | Optional minimum overall accuracy between 0 and 1 |
| `--namespace NAME` | Existing namespace for the Job and service, default `default` |
| `--node NAME` | Evaluation and transfer Pod node, default a control-plane node |
| `--job-timeout SECONDS` | Job deadline, default 14400; increase for large or slow evaluations |
| `--ready-timeout SECONDS` | Transfer Pod readiness timeout, default 300 |
| `--image NAME:TAG` | Evaluator image built and loaded by the runner, default `local/mmlu:0.1.0` |
| `--keep-resources` | Retain resources after collection for inspection |

Zero examples is the default to reduce input length on the repository's small-context profiles. Long questions and five-example prompts may still exceed server limits. Set the server's `--max-input-tokens` and `--n-ctx` to fit the prompt and output within the model's supported context, or reduce `--few-shot`. Context rejection is an error; the runner does not truncate questions or silently reduce examples.

Requests are sequential, with `temperature=0`, `top_p=1`, and `ignore_eos=false`. Each question starts a new conversation. Compare implementations using the same model, dataset hashes, sampling seed, shot count, and server context settings. A limited or filtered run is a subset result.

## Scoring and output

Leading and trailing whitespace, an optional `Answer:` prefix, and one trailing `.` or `)` are accepted around an uppercase answer letter. Explanations and multiple choices are `INVALID`. A matching answer is `CORRECT`; another choice is `INCORRECT`. HTTP failures, malformed or empty responses, and finish reasons other than `stop`, including output truncation, are `ERROR`.

Accuracy is correct answers divided by all attempted questions, including invalid answers and errors. Subject accuracy uses the same rule. Overall accuracy is weighted by question count, not an average of subject percentages.

Results default to `docs/reports/<backend>/mmlu-<UTC>/summary.json`, with GPU results under `docs/reports/gpu/<backend>/`. `--output` specifies another host JSON file and overwrites existing results at that path. Reports contain overall and subject scores, settings, dataset file SHA-256 hashes, sampled row indices, prompts, expected and predicted choices, raw API responses, and errors. A sibling `.jsonl` file is flushed on the PVC after each completed question and copied back during collection. `<output-stem>-run/` contains the rendered workloads, run metadata, Pod details and logs.

The runner also collects results when the Job fails an accuracy threshold or encounters API errors. If no complete JSON report can be collected, it retains the PVC and transfer Pod, collects any available JSONL, and prints the run label. Ctrl+C stops the Job and attempts partial result collection, then exits with code 130. A terminated Job may have only JSONL results. To remove retained resources, use the matching cluster script and namespace:

```sh
./scripts/local-k8s.sh kubectl -n default delete job,pod,pvc -l mmlu-run=<run-id>
```

Exit code 1 indicates a request error, setup failure, or accuracy below `--min-accuracy`. Otherwise it is 0. Without a threshold, incorrect and invalid answers affect the score but do not fail the command. Exit code 0 confirms a completed evaluation, not a minimum model quality.

## Verification

```sh
python3 -m unittest discover -s tests -p 'test_mmlu*.py'
```

Tests use local fixture data, an HTTP server and Helm rendering, without downloading a model or dataset.

## Direct host execution

For an externally accessible API, the standard-library evaluator can also run directly:

```sh
python3 scripts/check-mmlu.py --url http://127.0.0.1:8000 --subjects abstract_algebra --limit 10
```

This requires a reachable server or port forward. It defaults to `docs/reports/<backend>/mmlu-<UTC>.json` and saves a partial JSON report on Ctrl+C.
