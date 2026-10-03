# PD 실험 결과 정리

PD 실험은 `docs/reports/gpu/pd/<실행명>/`에 검토할 결과를, `reports/pd/<실행명>/`에 요청별 원본을 보관합니다. 서로 다른 설정, 소스 또는 실패 후 재측정은 별도 실행으로 남깁니다. 실험 목록은 [종합 보고서](../reports/gpu/pd/README-KR.md)에 연결합니다.

## 보존할 파일

| 위치와 파일 | 내용 |
| --- | --- |
| `summary.json`, `summary.csv` | 실행 상태, 측정 조건, 소스 해시와 조건별 집계 |
| `workload.json` | 해당 보고서를 재현할 입력, 출력, 동시성, 요청 수와 반복 설정 |
| `summary.md`, `comparison.csv`, `figures/` | 표, 그림, 집계 범위와 A/D 비교 |
| `analysis.md` | 주요 결과, 근거 파일, 조건부 해석과 한계 |
| `validation.md`, `*validation.json` | 출력 동등성, payload와 길이 일치, 이미지, MPS 설정, 오류, 재시작과 메모리 검증 |
| `phase-diagnostics.json`, `scheduler-diagnostics.json` | worker 로그 집계와 스케줄러 예산 검사, 워밍업 포함 여부 |
| `goodput/` | SLO별 집계, 반복별 충족률, 관찰 시간 정의와 원본 SHA-256 |
| `reports/pd/<실행명>/` | `runs.json`, 요청별 AIPerf exports, payload, Pod 및 GPU 표본과 로그. Git 제외 |

검증하지 않은 항목은 미검증으로 기록합니다. 기존 실험의 이미지나 검증 결과를 새 실행의 근거로 복사하지 않습니다. `goodput/*run-results.csv`는 SLO와 반복별 집계이며 요청별 원본은 아닙니다.

## 집계와 보고서 생성

Python 환경은 [PD 실행 가이드](prefill-decode-KR.md)의 의존성을 사용합니다. 아래 변수에는 실행기가 출력한 보고서 경로를 지정합니다.

```sh
PD_REPORT='docs/reports/gpu/pd/pd4-<실행시각>'
python3 scripts/report-pd.py "$PD_REPORT"
python3 scripts/report-pd-goodput.py "$PD_REPORT" \
  --ttft-ms 100,250,500,1000,2000,5000,10000,20000 \
  --tpot-ms 25,30,35,40,50,75 --min-attainment 0.95
```

두 명령은 `summary.json`의 `metadata.raw_dir`에 기록된 원본 경로가 필요합니다. `report-pd.py`는 `summary.md`, 비교 CSV와 그림을 다시 씁니다. 직접 작성한 해석은 `analysis.md`에 둡니다. Goodput 스크립트는 CSV, JSON과 그림을 생성하므로 `goodput/summary.md`와 `goodput/separate.md`의 설명 및 대표 표는 생성된 수치와 대조하여 작성합니다.

실패한 실행에서는 원래 `summary.json`의 상태를 유지하고 완전히 짝지어진 반복만 별도로 집계합니다.

```sh
python3 scripts/report-pd.py "$PD_REPORT" --completed-only
```

`completed-summary.json`과 `completed-summary.csv`의 완료 반복 수를 계획 반복 수와 함께 표시하고, 중단 원인과 제외 범위를 설명합니다. Goodput 스크립트는 전체 반복이 완료된 실행만 받습니다. 실패 실행을 성공 상태로 바꾸어 분석하지 않습니다.

## 보고서에 적을 내용

1. 비교 대상, 바꾼 설정과 공통 자원 예산을 명시합니다. 모델, dtype, GPU, MPS 슬롯, worker 역할, 스케줄러와 이미지 및 소스 식별자를 근거 파일에 남깁니다.
2. 입력과 출력 길이, 실제 토큰 분포, 동시성, 요청 수, 워밍업, 계획 및 완료 반복 수와 mode 순서를 기록합니다.
3. 대표 조건의 처리량, TTFT, TPOT 및 SLO 충족률을 단위와 함께 제시합니다. 전체 조건 CSV를 연결하고 유리한 조건만으로 전체 결론을 쓰지 않습니다.
4. 평균, p95와 반복 변동의 집계 규칙을 밝힙니다. 단계별 로그의 워밍업 포함 여부와 클라이언트 통계와의 차이를 명시합니다.
5. 오류, Pod 재시작, OOM, 메모리 측정 방식과 표본 수를 기록합니다. GPU 성능, 출력 동등성, HTTP mock 검사의 범위를 구분합니다.
6. 같은 예산 비교와 SLO를 만족하는 예산 선택을 구분합니다. 사후 탐색한 임계값과 조건부 이득, 부족한 반복 수를 명시합니다.

## 커밋 전 확인

보고서에서 참조한 로컬 파일이 존재하며 Git 제외 규칙에 걸리지 않는지 확인합니다. 보존 규칙은 [docs/reports/.gitignore](../reports/.gitignore)에 있습니다. 원본은 별도 보관하고 요약과 검증 자료를 커밋합니다.

```sh
git status --short --untracked-files=all -- docs/reports/gpu/pd
git check-ignore -v "$PD_REPORT/summary.json" "$PD_REPORT/comparison.csv"
git diff --check
```

집계 요청 수와 오류 수는 JSON 및 CSV와 맞추고, 그림과 본문이 같은 실행과 설정을 가리키는지 확인합니다. 새 결과는 종합 보고서에 연결하되 기존 실행 수치를 덮어쓰지 않습니다. 코드 변경 이력과 검증 명령은 커밋 메시지에 기록합니다.
