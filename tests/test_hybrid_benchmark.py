"""Check benchmark token timing and base-relative aggregation."""

import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location("hybrid_benchmark", Path(__file__).resolve().parents[1] / "scripts/benchmark-hybrid.py")
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


class BenchmarkTests(unittest.TestCase):
    def test_pooled_tail_and_same_workload_base_ratio(self):
        rows = []
        for condition, rate, latencies in (("base", 10, [10, 30]), ("base", 20, [20, 100]),
                                           ("gpu", 60, [5, 15]), ("gpu", 60, [10, 20])):
            rows.append(dict(condition=condition, prompt_tokens=64, concurrency=2, requests=2,
                             output_tokens_per_second=rate, latency_ms=sum(latencies) / 2,
                             ttft_ms=5, latencies_ms=latencies, ttfts_ms=[4, 6],
                             peak_allocated_mib=100, peak_reserved_mib=120, cache_delta={}))
        base, gpu = benchmark.summarize(rows)
        self.assertEqual(base["latency_p95_ms"], 100)
        self.assertEqual(base["output_tokens_per_second_mean"], 15)
        self.assertEqual(gpu["throughput_vs_base"], 4)
        self.assertEqual(gpu["requests"], 4)

    def test_summary_without_baseline_does_not_invent_speedup(self):
        row = dict(condition="cold", prompt_tokens=64, concurrency=1, requests=1,
                   output_tokens_per_second=10, latency_ms=20, ttft_ms=5,
                   latencies_ms=[20], ttfts_ms=[5], peak_allocated_mib=100,
                   peak_reserved_mib=120, cache_delta={})
        self.assertIsNone(benchmark.summarize([row])[0]["throughput_vs_base"])


if __name__ == "__main__":
    unittest.main()
