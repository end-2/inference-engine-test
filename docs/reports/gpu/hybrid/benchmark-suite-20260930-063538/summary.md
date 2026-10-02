> Korean version: [한국어](summary-KR.md)

# Jamba Base and Hybrid Benchmark

Status: `complete`. Model: `ai21labs/Jamba-tiny-dev`. GPU: `NVIDIA GeForce RTX 2060 SUPER`. dtype: `float16`, Mamba path: `pytorch`.

Compares serial processing with the base `generate()` of the same model against the hybrid engine. The base also uses dynamic KV and Mamba cache within a request.

Measured inputs [64, 256] tokens, 32 output tokens, concurrency [1, 2, 4, 8], 3 repetitions, 2 requests per repetition bundle. Each request bundle submits as many distinct inputs concurrently as the concurrency level.

- base: default generate() with a single worker, no cache between requests.
- batch: hybrid buffer and batch processing, all prefix caches disabled.
- cold: cache cleared just before the measurement bundle, includes checkpoint creation cost.
- gpu, ram, disk: checkpoint for that tier prepared before each bundle, measurement includes lookup and promotion cost.

| Input | Concurrency | Condition | Requests | Output tok/s | vs Base | Avg TTFT ms | Avg Latency ms | p95 Latency ms | GPU Allocated Peak MiB |
| ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 64 | 1 | base | 6 | 33.30 | 1.00x | 105.60 | 961.11 | 980.46 | 640.5 |
| 64 | 1 | batch | 6 | 31.93 | 0.96x | 141.20 | 1002.31 | 1027.56 | 650.3 |
| 64 | 1 | cold | 6 | 32.74 | 0.98x | 136.77 | 977.35 | 979.43 | 650.3 |
| 64 | 1 | gpu | 6 | 36.18 | 1.09x | 33.84 | 884.62 | 906.04 | 638.7 |
| 64 | 1 | ram | 6 | 35.98 | 1.08x | 34.90 | 889.57 | 920.30 | 638.7 |
| 64 | 1 | disk | 6 | 35.68 | 1.07x | 37.92 | 896.88 | 913.21 | 638.7 |
| 64 | 2 | base | 12 | 33.41 | 1.00x | 585.08 | 1438.06 | 1957.95 | 640.5 |
| 64 | 2 | batch | 12 | 62.17 | 1.86x | 145.83 | 1029.37 | 1044.38 | 664.3 |
| 64 | 2 | cold | 12 | 62.95 | 1.88x | 146.28 | 1016.49 | 1023.88 | 664.3 |
| 64 | 2 | gpu | 12 | 70.24 | 2.10x | 40.13 | 911.11 | 927.28 | 641.1 |
| 64 | 2 | ram | 12 | 69.32 | 2.08x | 37.00 | 923.34 | 941.49 | 641.1 |
| 64 | 2 | disk | 12 | 69.09 | 2.07x | 46.35 | 926.35 | 946.32 | 641.1 |
| 64 | 4 | base | 24 | 33.16 | 1.00x | 1553.48 | 2412.68 | 3908.73 | 640.5 |
| 64 | 4 | batch | 24 | 117.21 | 3.53x | 148.48 | 1091.86 | 1108.11 | 692.5 |
| 64 | 4 | cold | 24 | 119.51 | 3.60x | 146.93 | 1070.73 | 1072.22 | 692.5 |
| 64 | 4 | gpu | 24 | 133.02 | 4.01x | 38.38 | 961.97 | 970.50 | 646.0 |
| 64 | 4 | ram | 24 | 130.79 | 3.94x | 40.76 | 978.74 | 1010.70 | 646.0 |
| 64 | 4 | disk | 24 | 127.26 | 3.84x | 56.59 | 1005.93 | 1042.30 | 646.0 |
| 64 | 8 | base | 48 | 33.42 | 1.00x | 3455.95 | 4308.90 | 7682.59 | 640.5 |
| 64 | 8 | batch | 48 | 234.69 | 7.02x | 146.60 | 1090.56 | 1114.10 | 749.7 |
| 64 | 8 | cold | 48 | 234.55 | 7.02x | 150.36 | 1091.24 | 1128.53 | 749.7 |
| 64 | 8 | gpu | 48 | 261.53 | 7.83x | 33.41 | 978.45 | 984.92 | 655.7 |
| 64 | 8 | ram | 48 | 260.00 | 7.78x | 38.86 | 984.43 | 1008.66 | 655.7 |
| 64 | 8 | disk | 48 | 252.24 | 7.55x | 63.14 | 1014.44 | 1019.68 | 655.7 |
| 256 | 1 | base | 6 | 27.51 | 1.00x | 308.12 | 1163.43 | 1191.88 | 680.4 |
| 256 | 1 | batch | 6 | 26.66 | 0.97x | 342.58 | 1200.43 | 1228.14 | 690.1 |
| 256 | 1 | cold | 6 | 26.78 | 0.97x | 341.20 | 1195.07 | 1231.74 | 690.1 |
| 256 | 1 | gpu | 6 | 36.15 | 1.31x | 33.79 | 885.10 | 891.54 | 638.9 |
| 256 | 1 | ram | 6 | 35.87 | 1.30x | 37.04 | 892.43 | 924.36 | 638.9 |
| 256 | 1 | disk | 6 | 35.34 | 1.28x | 44.88 | 905.39 | 923.46 | 638.9 |
| 256 | 2 | base | 12 | 27.47 | 1.00x | 891.58 | 1748.67 | 2391.07 | 680.4 |
| 256 | 2 | batch | 12 | 51.42 | 1.87x | 362.48 | 1244.81 | 1269.72 | 744.0 |
| 256 | 2 | cold | 12 | 52.12 | 1.90x | 358.65 | 1227.69 | 1230.73 | 744.0 |
| 256 | 2 | gpu | 12 | 70.01 | 2.55x | 35.31 | 913.98 | 920.87 | 641.6 |
| 256 | 2 | ram | 12 | 69.22 | 2.52x | 42.58 | 924.94 | 957.01 | 641.6 |
| 256 | 2 | disk | 12 | 69.08 | 2.52x | 44.30 | 926.33 | 933.65 | 641.6 |
| 256 | 4 | base | 24 | 27.46 | 1.00x | 2058.10 | 2914.94 | 4766.54 | 680.4 |
| 256 | 4 | batch | 24 | 101.31 | 3.69x | 368.93 | 1263.45 | 1277.86 | 851.6 |
| 256 | 4 | cold | 24 | 102.04 | 3.72x | 368.30 | 1254.48 | 1283.55 | 851.6 |
| 256 | 4 | gpu | 24 | 137.06 | 4.99x | 37.09 | 933.75 | 947.49 | 648.6 |
| 256 | 4 | ram | 24 | 136.15 | 4.96x | 39.85 | 939.91 | 950.72 | 648.6 |
| 256 | 4 | disk | 24 | 133.73 | 4.87x | 57.18 | 957.06 | 981.31 | 648.6 |
| 256 | 8 | base | 48 | 27.51 | 1.00x | 4385.56 | 5241.00 | 9326.55 | 680.4 |
| 256 | 8 | batch | 48 | 201.22 | 7.31x | 371.55 | 1271.99 | 1293.39 | 1066.8 |
| 256 | 8 | cold | 48 | 200.55 | 7.29x | 376.71 | 1276.38 | 1299.77 | 1066.8 |
| 256 | 8 | gpu | 48 | 273.43 | 9.94x | 34.05 | 936.06 | 954.94 | 657.9 |
| 256 | 8 | ram | 48 | 270.53 | 9.83x | 39.86 | 946.03 | 957.72 | 657.9 |
| 256 | 8 | disk | 48 | 265.94 | 9.67x | 68.07 | 962.37 | 987.09 | 657.9 |

## Measurement Conditions

Excludes HTTP and tokenizer processing time, and includes engine queueing, batch waiting, generation, and streamer costs. TTFT is the time when the first generated token arrives at the CPU streamer, which differs from first text chunk time.

Excludes model loading, warmup, cache initialization, and warm checkpoint preparation from measurement. Fixes output length with greedy decoding and EOS suppression. Verifies token IDs and usage of every measured request against the base output of the same model. Measures time after GPU synchronization, and rotates condition order each repetition.

Average metrics are averages of per-bundle metrics. p95 is computed with nearest-rank over all repeated requests in the same condition; with small samples, do not interpret it as the p95 of service load. GPU memory is the PyTorch allocator peak allocated, not total GPU usage. Standard deviations and reserved memory are in summary.csv.

The disk condition reads files written just before, so it includes OS page cache effects. It is not a cold-read benchmark of physical disk. Jamba-tiny-dev is a development model and does not represent the throughput of a larger Jamba deployment.

[Run metadata and verification](run.json), [summary CSV](summary.csv), [per-bundle raw metrics](runs.csv). Per-request tokens and timings are kept in local requests.jsonl.
