"""Checks for repetition scheduling and statistics across independent sweeps."""

from collections import Counter
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("suite", Path(__file__).resolve().parents[1] / "scripts/run-benchmark-suite.py")
suite = importlib.util.module_from_spec(spec)
spec.loader.exec_module(suite)


class SuiteTests(unittest.TestCase):
    def test_each_condition_runs_three_times_in_rotated_order(self):
        cases = suite.plan(3)
        self.assertEqual(len(cases), 12)
        self.assertEqual(Counter(case["condition"] for case in cases),
                         {label: 3 for label, _, _ in suite.CONDITIONS})
        for repetition in range(1, 4):
            group = [case for case in cases if case["repetition"] == repetition]
            self.assertEqual(len({case["condition"] for case in group}), 4)
            self.assertEqual(group[0]["condition"], suite.CONDITIONS[repetition - 1][0])

    def test_preserved_cache_is_reset_only_at_the_start_of_each_sweep(self):
        for case in suite.plan(3):
            schedule = [suite.benchmark.clears_cache(case["cache_policy"], i) for i in range(4)]
            if case["condition"] == "enhanced-cache-preserve":
                self.assertEqual(schedule, [True, False, False, False])
            elif case["condition"] == "enhanced-cache-clear":
                self.assertEqual(schedule, [True] * 4)
            else:
                self.assertEqual(schedule, [False] * 4)

    def test_mean_sample_deviation_and_range_do_not_mix_conditions(self):
        rows = [{"condition": "base", "concurrency": 2, "repetition": i, "report": "report",
                 "output_tokens_per_second": value, "ttft_p95_ms": value * 10}
                for i, value in enumerate((10, 20, 30), 1)]
        rows.append({**rows[0], "condition": "enhanced-batch", "output_tokens_per_second": 100})
        base, batch = suite.aggregate(rows)
        self.assertEqual(base["repetitions"], 3)
        self.assertEqual(base["output_tokens_per_second_mean"], 20)
        self.assertEqual(base["output_tokens_per_second_std"], 10)
        self.assertEqual(base["output_tokens_per_second_min"], 10)
        self.assertEqual(base["output_tokens_per_second_max"], 30)
        self.assertEqual(base["ttft_p95_ms_mean"], 200)
        self.assertEqual(batch["output_tokens_per_second_mean"], 100)
        self.assertIsNone(batch["output_tokens_per_second_std"])

    def test_missing_metric_is_not_silently_excluded(self):
        with self.assertRaisesRegex(RuntimeError, "Incomplete metric"):
            suite.aggregate([{"condition": "base", "concurrency": 1, "ttft_avg_ms": None}])


if __name__ == "__main__":
    unittest.main()
