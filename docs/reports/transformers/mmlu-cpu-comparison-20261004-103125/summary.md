# CPU Transformers MMLU 측정

Base, batch, cache를 순차 평가했습니다. 모델은 SmolLM2-135M-Instruct FP32입니다. Pod CPU requests와 limits는 8개, 메모리는 16Gi이며 PyTorch 스레드는 4개입니다.

전체 test 57과목, 14,042문항, 0-shot, 최대 출력 16토큰, temperature=0 조건입니다. 정확도는 정답 수를 전체 문항 수로 나눕니다. 형식 오류와 응답 또는 요청 오류도 분모에 포함합니다.

| 구현 | 문항 | 정답 | 정확도 | 형식 오류 | 응답 또는 요청 오류 | 평균 요청 시간(s) | p95(s) | 평가 시간(분) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| base | 14,042 | 2,071 | 14.75% | 4,470 | 680 | 0.192 | 0.500 | 45.02 |
| batch | 14,042 | 2,071 | 14.75% | 4,470 | 680 | 0.197 | 0.501 | 46.13 |
| cache | 14,042 | 2,071 | 14.75% | 4,470 | 680 | 0.179 | 0.472 | 41.98 |

서버 context는 1,024토큰, 최대 입력은 768토큰입니다. Cache는 평가 전에 비우고 문항 사이에서 유지했습니다. 요청은 동시성 1로 전송하므로 batch 처리량 향상은 이 평가에서 측정하지 않습니다.

채점 방식은 `generated-choice-v1`입니다. 설명이 붙은 답안은 형식 오류이며, 출력이 잘리거나 입력 제한을 넘는 요청은 오류입니다. 공개 MMLU 로그 확률 평가와 조건이 다릅니다.

각 구현의 오류 680개는 출력 잘림 670개와 입력 제한 초과 10개입니다. 이 오류로 세 `make mmlu-check` 명령의 종료 코드는 2였으며, 14,042문항 결과는 모두 수집됐습니다. 평균과 p95 요청 시간은 형식 오류와 요청 오류를 포함한 모든 문항을 기준으로 계산했습니다. 각 구현을 한 번씩 측정했습니다.

세 구현의 14,042문항 답안과 채점 상태는 모두 일치했습니다.

측정 후 기존 batch Deployment 구성을 복원하고 Ready 상태를 확인했습니다. 모델과 데이터 파일 해시, 생성 설정, 실행 중 Pod 재시작이 없었음을 확인했습니다.

상세 조건과 검증 결과는 [비교 JSON](summary.json), [환경](environment.json), [문항별 비교](pairwise-comparison.json)에 있습니다.

## 원본 결과

- [base](base/summary.json), [평가 로그](base/summary-run/mmlu.log)
- [batch](batch/summary.json), [평가 로그](batch/summary-run/mmlu.log)
- [cache](cache/summary.json), [평가 로그](cache/summary-run/mmlu.log)

## 실행 명령

각 구현을 배포하고 Ready 상태를 확인한 뒤 아래 명령을 실행했습니다.

```sh
make mmlu-check DEVICE=cpu VARIANT=transformers-base MMLU_ARGS='--output docs/reports/transformers/mmlu-cpu-comparison-20261004-103125/base/summary.json'
make mmlu-check DEVICE=cpu VARIANT=transformers-enhanced-batch MMLU_ARGS='--output docs/reports/transformers/mmlu-cpu-comparison-20261004-103125/batch/summary.json'
make mmlu-check DEVICE=cpu VARIANT=transformers-enhanced-cache MMLU_ARGS='--output docs/reports/transformers/mmlu-cpu-comparison-20261004-103125/cache/summary.json'
```
