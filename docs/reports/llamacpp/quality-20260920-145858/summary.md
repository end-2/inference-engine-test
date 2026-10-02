> Korean version: [한국어](summary-KR.md)

# Basic response quality by inference image

Sent the same 7 questions once each, sequentially, to three images using Qwen2.5-0.5B-Instruct Q4_K_M. Per-question responses were identical across the three images, and all 5 automatically checkable items passed on answer-content criteria. There were no API errors or truncated outputs.

## Measurement conditions

- Run time: 2026-09-20 14:59–15:00 UTC (2026-09-20 23:59–2026-09-21 00:00 Korea time). Exact request times are recorded in each image's source files.
- Images: `local/llama-base:0.1.0`, `local/llama-enhanced-batch:0.1.0`, `local/llama-enhanced-cache:0.1.0`.
- 1 inference Pod with 12 CPU and 16 GiB. Each image ran on a fresh Pod.
- `temperature=0`, `top_p=1`, `max_completion_tokens=128`, `ignore_eos=false`, non-streaming. Request timeout 60s.
- The cache image started from a separate empty cache path. Each question was requested once; repeated- or concurrent-request quality was not evaluated.
- [Check script](../../../../scripts/check-quality.py), [run record and image IDs](run.json).

## Automatic check results

Judgments apply the `content-v1` criteria to the stored responses. Response content was evaluated without additional inference requests, and output formatting such as explanations, equations, and code blocks was not penalized.

| Image | Pass | Fail | Review | Error | Source responses |
| --- | ---: | ---: | ---: | ---: | --- |
| base | 5/5 | 0 | 2 | 0 | [JSON](base/results.json) |
| enhanced-batch | 5/5 | 0 | 2 | 0 | [JSON](enhanced-batch/results.json) |
| enhanced-cache | 5/5 | 0 | 2 | 0 | [JSON](enhanced-cache/results.json) |

The instructed word, computed value, order number, JSON field values, and cat name all matched in all three images.

| Item | Expected output | Actual output | Verdict |
| --- | --- | --- | --- |
| Instruction following | `PASS` | `PASS` | PASS |
| Calculation | Result `42` | `17 + 25 = 42` | PASS |
| Information extraction | Order number `ZX-2048` | `ZX-2048입니다. 배송일은 금요일입니다.` | PASS |
| JSON | `name=Mina`, `count=3` | Both fields and values returned correctly in a JSON code block | PASS |
| Conversation context | Cat name `모카` | `고양이 이름은 모카입니다.` | PASS |

## Summary and translation response review

The script's original verdicts remain `REVIEW`. The evaluation below is a Codex review of the stored responses against the criteria, and is not included in human evaluation or automatic scoring.

| Item | Actual output | Review result |
| --- | --- | --- |
| Summary | 도서관은 주말에 문을 닫습니다. 월요일 오전 9시에 다시 문을 열게 됩니다. | Criteria not met. Changed Monday closure to weekend, Tuesday reopening to Monday, and dropped the facility-inspection reason. |
| Translation | 중noon에 열리는 회의가 있습니다. | Criteria not met. Did not preserve the 3 PM time or the "starts" meaning. |

These 7 sequential questions showed no response difference between implementations. Basic answer-accuracy items passed, but limits in Korean summary and translation content accuracy were confirmed. This result alone cannot judge overall model quality or quality equivalence under concurrent batching and cache reuse.
