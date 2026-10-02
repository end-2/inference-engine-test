# TTFT와 TPOT 동시 SLO goodput

TTFT와 요청별 평균 TPOT의 상한을 모두 통과한 요청만 셉니다. 워밍업을 제외하고 반복별 goodput을 산술 평균합니다.

![두 지표를 동시에 제한한 goodput](goodput-slo.png)

[전체 비교 CSV](comparison.csv), [95% 충족 조건의 처리 용량](best-feasible.csv), [원본 검증과 집계 규칙](metadata.json).

[TTFT와 TPOT를 따로 제한한 결과](separate.md).
