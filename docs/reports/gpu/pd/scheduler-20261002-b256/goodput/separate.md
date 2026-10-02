> Korean version: [한국어](separate-KR.md)

# TTFT and TPOT Goodput Separately

Applies only one metric's threshold and does not constrain the other. Goodput is passing requests divided by total measured observation time. Averages per-repetition goodput arithmetically and excludes warmup. TPOT is a per-request average, not a per-token ITL cap.

![Goodput by metric](goodput-separated.png)

Below is concurrency-16 mixed load. Attainment sums 48 requests across two repetitions. High goodput at low attainment does not mean most requests satisfy the SLO.

| Criterion | Cap ms | A req/s | D req/s | A Attainment | D Attainment |
| --- | ---: | ---: | ---: | ---: | ---: |
| TTFT | 100 | 0.268 | 0.000 | 8.3% | 0.0% |
| TTFT | 250 | 1.925 | 0.679 | 60.4% | 25.0% |
| TTFT | 500 | 3.120 | 1.304 | 97.9% | 47.9% |
| TTFT | 1000 | 3.185 | 2.088 | 100.0% | 77.1% |
| TTFT | 2000 | 3.185 | 2.707 | 100.0% | 100.0% |
| TTFT | 5000 | 3.185 | 2.707 | 100.0% | 100.0% |
| TTFT | 10000 | 3.185 | 2.707 | 100.0% | 100.0% |
| TTFT | 20000 | 3.185 | 2.707 | 100.0% | 100.0% |
| TPOT | 25 | 0.000 | 0.000 | 0.0% | 0.0% |
| TPOT | 30 | 0.000 | 0.000 | 0.0% | 0.0% |
| TPOT | 35 | 0.067 | 0.058 | 2.1% | 2.1% |
| TPOT | 40 | 1.266 | 0.338 | 39.6% | 12.5% |
| TPOT | 50 | 3.185 | 2.707 | 100.0% | 100.0% |
| TPOT | 75 | 3.185 | 2.707 | 100.0% | 100.0% |

[Full TTFT comparison](ttft-comparison.csv), [full TPOT comparison](tpot-comparison.csv), [aggregation rules and raw-data verification](metadata.json).

`best-feasible` CSVs select the highest-goodput concurrency among those attaining 95%+ in every repetition. Blank where no such condition exists.

[Both SLOs applied together](summary.md), [performance comparison](../summary.md).
