> Korean version: [한국어](experiment-results-KR.md)

# Organizing PD experiment results

Keep reviewable results in `docs/reports/gpu/pd/<run-name>/` and per-request originals in `reports/pd/<run-name>/`. Keep different settings, sources, or re-measurements after failure as separate runs. Link the experiment list in the [summary report](../reports/gpu/pd/README.md).

## Files to keep

| Location and file | Contents |
| --- | --- |
| `summary.json`, `summary.csv` | Run status, measurement conditions, source hashes, and per-condition aggregates |
| `workload.json` | Input, output, concurrency, request count, and repetition settings needed to reproduce the report |
| `summary.md`, `comparison.csv`, `figures/` | Tables, figures, aggregate ranges, and A/D comparison |
| `analysis.md` | Key results, evidence files, conditional interpretations, and limits |
| `validation.md`, `*validation.json` | Output equivalence, payload and length match, image, MPS settings, errors, restart and memory validation |
| `phase-diagnostics.json`, `scheduler-diagnostics.json` | Worker log aggregates and scheduler budget checks, including whether warmup is included |
| `goodput/` | Per-SLO aggregates, per-repeat attainment, observation time definition, and original SHA-256 |
| `reports/pd/<run-name>/` | `runs.json`, per-request AIPerf exports, payloads, Pod and GPU samples, and logs. Excluded from Git |

Record unvalidated items as unvalidated. Do not copy another experiment's image or validation results as evidence for a new run. `goodput/*run-results.csv` holds per-SLO and per-repeat aggregates, not per-request originals.

## Aggregation and report generation

The Python environment uses the dependencies in the [PD run guide](prefill-decode.md). Set the variable below to the report path produced by the runner.

```sh
PD_REPORT='docs/reports/gpu/pd/pd4-<run-time>'
python3 scripts/report-pd.py "$PD_REPORT"
python3 scripts/report-pd-goodput.py "$PD_REPORT" \
  --ttft-ms 100,250,500,1000,2000,5000,10000,20000 \
  --tpot-ms 25,30,35,40,50,75 --min-attainment 0.95
```

Both commands need the original path recorded in `metadata.raw_dir` of `summary.json`. `report-pd.py` rewrites `summary.md`, the comparison CSV, and figures. Put hand-written interpretation in `analysis.md`. The goodput script generates CSV, JSON, and figures, so write the descriptions and representative tables in `goodput/summary.md` and `goodput/separate.md` against the generated numbers.

For a failed run, keep the original `summary.json` status and aggregate only fully paired repeats separately.

```sh
python3 scripts/report-pd.py "$PD_REPORT" --completed-only
```

Show the completed repeat count from `completed-summary.json` and `completed-summary.csv` together with the planned repeat count, and explain the abort cause and exclusion scope. The goodput script accepts only runs where all repeats completed. Do not convert a failed run to success for analysis.

## What to write in reports

1. State the comparison targets, changed settings, and common resource budget. Record model, dtype, GPU, MPS slots, worker roles, scheduler, image, and source identifiers in evidence files.
2. Record input and output lengths, actual token distribution, concurrency, request count, warmup, planned and completed repeat counts, and mode order.
3. Present throughput, TTFT, TPOT, and SLO attainment for representative conditions with units. Link the full-condition CSV and do not generalize from favorable conditions only.
4. State aggregation rules for means, p95, and repeat variation. Specify whether phase logs include warmup and differences from client statistics.
5. Record errors, Pod restarts, OOMs, memory measurement methods, and sample counts. Distinguish GPU performance, output equivalence, and HTTP mock check scopes.
6. Distinguish same-budget comparison from budget selection that meets SLOs. State post-hoc thresholds, conditional gains, and insufficient repeat counts.

## Checks before commit

Check that local files referenced from reports exist and are not covered by Git exclusion rules. Retention rules are in [docs/reports/.gitignore](../reports/.gitignore). Store originals separately and commit summaries and validation materials.

```sh
git status --short --untracked-files=all -- docs/reports/gpu/pd
git check-ignore -v "$PD_REPORT/summary.json" "$PD_REPORT/comparison.csv"
git diff --check
```

Match aggregate request and error counts to JSON and CSV, and check that figures and text point to the same run and settings. Link new results in the summary report without overwriting existing run numbers. Record code change history and validation commands in the commit message.
