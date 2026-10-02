"""Check joint SLO counting, token weighting, and repeated-run feasibility."""

import importlib.util
import math
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("pd_goodput", ROOT / "scripts/report-pd-goodput.py")
goodput = importlib.util.module_from_spec(spec)
spec.loader.exec_module(goodput)


class GoodputTests(unittest.TestCase):
    def test_joint_slo_is_inclusive_and_weights_actual_passing_tokens(self):
        records = [
            {"ttft_ms": 100, "tpot_ms": 30, "output_tokens": 16},
            {"ttft_ms": 101, "tpot_ms": 29, "output_tokens": 256},
            {"ttft_ms": 99, "tpot_ms": 31, "output_tokens": 256},
        ]
        result = goodput.evaluate(records, 2, 100, 30)
        self.assertEqual(result["good_requests"], 1)
        self.assertEqual(result["ttft_pass"], 2)
        self.assertEqual(result["tpot_pass"], 2)
        self.assertEqual(result["request_goodput"], 0.5)
        self.assertEqual(result["token_goodput"], 8)
        self.assertNotEqual(result["token_goodput"], result["token_throughput"] * result["attainment"])

    def test_observation_window_recovers_exported_throughput(self):
        records = [{"ttft_ms": 1, "tpot_ms": 1, "output_tokens": 16},
                   {"ttft_ms": 1, "tpot_ms": 1, "output_tokens": 256}]
        export = {"request_throughput": {"avg": 0.25},
                  "output_token_throughput": {"avg": 34}, "benchmark_duration": {"avg": 7.99}}
        duration = goodput.observation_duration(export, records)
        self.assertEqual(duration, 8)
        result = goodput.evaluate(records, duration, math.inf, math.inf)
        self.assertEqual(result["request_goodput"], export["request_throughput"]["avg"])
        self.assertEqual(result["token_goodput"], export["output_token_throughput"]["avg"])
        export["output_token_throughput"]["avg"] = 33
        with self.assertRaisesRegex(ValueError, "different observation windows"):
            goodput.observation_duration(export, records)

    def test_separate_criteria_ignore_the_other_limit_without_changing_duration(self):
        records = [
            {"ttft_ms": 100, "tpot_ms": 30, "output_tokens": 16},
            {"ttft_ms": 20000, "tpot_ms": 29, "output_tokens": 256},
            {"ttft_ms": 99, "tpot_ms": 50, "output_tokens": 64},
            {"ttft_ms": 101, "tpot_ms": 31, "output_tokens": 16},
        ]
        ttft = goodput.evaluate(records, 25, 100, None)
        tpot = goodput.evaluate(records, 25, None, 30)
        joint = goodput.evaluate(records, 25, 100, 30)
        self.assertEqual(ttft["good_requests"], 2)
        self.assertEqual(tpot["good_requests"], 2)
        self.assertEqual(joint["good_requests"], 1)
        self.assertEqual(ttft["token_goodput"], 80 / 25)
        self.assertEqual(tpot["token_goodput"], 272 / 25)
        for result in (ttft, tpot):
            self.assertEqual(result["request_goodput"], 2 / 25)
            self.assertEqual(result["duration_seconds"], 25)
        self.assertEqual(ttft["tpot_pass"], len(records))
        self.assertEqual(tpot["ttft_pass"], len(records))

    def test_separate_profiles_count_each_run_once_per_active_threshold(self):
        records = [{"ttft_ms": 100, "tpot_ms": 30, "output_tokens": 16}]
        samples = [({"workload": "mixed", "mode": mode, "concurrency": 1,
                     "repetition": 1, "duration_seconds": 2}, records, 2)
                   for mode in ("aggregated", "disaggregated")]
        ttft = goodput.profile_rows(samples, [50, 100], [None])
        tpot = goodput.profile_rows(samples, [None], [25, 30, 35])
        self.assertEqual(len(ttft), 4)
        self.assertEqual(len(tpot), 6)
        self.assertTrue(all(r["tpot_slo_ms"] is None for r in ttft))
        self.assertTrue(all(r["ttft_slo_ms"] is None for r in tpot))
        for rows, expected in ((ttft, 2), (tpot, 3)):
            summary = goodput.summarize(rows)
            self.assertTrue(all(r["requests"] == 1 for r in summary))
            self.assertEqual(len(goodput.comparisons(summary)), expected)
            self.assertEqual(len(goodput.best_feasible(summary, 0.95)), 2 * expected)

    def test_rates_average_runs_and_feasibility_requires_every_repetition(self):
        common = {"ttft_slo_ms": 100, "tpot_slo_ms": 30, "workload": "mixed", "mode": "aggregated"}
        records = [{"ttft_ms": 50, "tpot_ms": 20, "output_tokens": 16} for _ in range(32)]
        runs = [{**common, "concurrency": 2, **goodput.evaluate(records, 32, 100, 30)},
                {**common, "concurrency": 2, **goodput.evaluate(records, 16, 100, 30)}]
        for failures in (0, 2):
            changed = [{**r, "ttft_ms": 101 if i < failures else 50} for i, r in enumerate(records)]
            runs.append({**common, "concurrency": 4, **goodput.evaluate(changed, 8, 100, 30)})
        summary = goodput.summarize(runs)
        by_concurrency = {r["concurrency"]: r for r in summary}
        self.assertEqual(by_concurrency[2]["request_goodput"], 1.5)
        self.assertNotAlmostEqual(by_concurrency[2]["request_goodput"], 64 / 48)
        self.assertGreater(by_concurrency[4]["attainment"], 0.95)
        self.assertLess(by_concurrency[4]["min_repetition_attainment"], 0.95)
        self.assertEqual(goodput.best_feasible(summary, 0.95)[0]["concurrency"], 2)
        self.assertIsNone(goodput.best_feasible([by_concurrency[4]], 0.95)[0]["concurrency"])

    def test_zero_baseline_ratio_is_undefined(self):
        records = [{"ttft_ms": 101, "tpot_ms": 20, "output_tokens": 16}]
        common = {"ttft_slo_ms": 100, "tpot_slo_ms": 30, "workload": "mixed", "concurrency": 1}
        runs = [{**common, "mode": mode, **goodput.evaluate(records, 1, 100, 30)}
                for mode in ("aggregated", "disaggregated")]
        comparison = goodput.comparisons(goodput.summarize(runs))[0]
        self.assertIsNone(comparison["d_over_a_goodput"])
        self.assertEqual(comparison["d_minus_a_goodput"], 0)


if __name__ == "__main__":
    unittest.main()
