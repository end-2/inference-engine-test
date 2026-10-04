# GPU Transformers MMLU evaluation

Evaluated base, enhanced-batch, and enhanced-cache sequentially on SmolLM2-135M-Instruct FP16. The GPU is an RTX 2060 SUPER with 8 GiB memory and driver 580.126.09. Runtime is Transformers 4.57.6 with torch 2.10.0 and CUDA 12.8.

All variants answered the full test set of 57 subjects and 14,042 questions with 0-shot prompts, maximum 128 output tokens, temperature 0, concurrency 1, and `generated-choice-v1` scoring. Accuracy divides correct answers by all questions, so format errors and request errors stay in the denominator.

| Variant | Questions | Correct | Accuracy | Invalid | Errors | Elapsed (min) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| base | 14,042 | 2,105 | 14.99% | 5,018 | 4 | 34.6 |
| enhanced-batch | 14,042 | 2,105 | 14.99% | 5,018 | 4 | 35.2 |
| enhanced-cache | 14,042 | 2,102 | 14.97% | 5,017 | 4 | 45.4 |

The 4 errors in each variant are output truncations with `finish_reason='length'`. Requests ran sequentially, so this evaluation does not measure batch throughput.

Enhanced-batch produced byte-identical answers and scores to base across all 14,042 questions. Enhanced-cache differed from base in 204 responses: 22 changed from correct to not correct and 19 changed from not correct to correct, for a net of 3 fewer correct answers.

A posthoc choice-text comparison also accepts a leading `A.`, `B.`, `C.`, `D.` or closing parenthesis followed by whitespace, with an optional `Answer:` prefix. Under that rule, base and enhanced-batch reach 24.21% (3,400 of 14,042) and enhanced-cache reaches 24.19% (3,397 of 14,042). Error responses stay incorrect. Original `generated-choice-v1` reports are preserved in the local per-question files.

## Evidence

- [Aggregate JSON](summary.json), [aggregate CSV](summary.csv), [per-subject CSV](summary-subjects.csv), [conditions](conditions.json)
- [Suite runner](run-suite.py), [aggregation script](aggregate.py)
- Per-variant `differences.json` records pairwise answer changes against base
- Per-question `results.json` and `results.jsonl` plus server logs stay in the local result directory and are excluded from Git

The `pilot/` directory holds a preliminary run and is not part of the aggregate above.
