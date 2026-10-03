"""Verify workload matching, export validation, and repeated-run aggregation."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from manifest_support import render

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("pd_benchmark", ROOT / "scripts/benchmark-pd.py")
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)
report_spec = importlib.util.spec_from_file_location("pd_report", ROOT / "scripts/report-pd.py")
report = importlib.util.module_from_spec(report_spec)
report_spec.loader.exec_module(report)


class BenchmarkTests(unittest.TestCase):
    def test_scheduler_trace_checks_role_budget_and_completed_token_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp)
            path = raw / "r1/aggregated/workers.log"
            path.parent.mkdir(parents=True)
            records = [
                ("aggregate", "pd_scheduler", {"prefill_tokens": 3, "decode_tokens": 1, "scheduled_tokens": 4,
                    "token_budget": 4, "requests": 2, "step_ms": 1}),
                ("aggregate", "pd_request", {"role": "aggregated", "prompt_tokens": 3, "completion_tokens": 2}),
                ("prefill", "pd_scheduler", {"prefill_tokens": 3, "decode_tokens": 0, "scheduled_tokens": 3,
                    "token_budget": 4, "requests": 1, "step_ms": 1}),
                ("decode", "pd_scheduler", {"prefill_tokens": 0, "decode_tokens": 2, "scheduled_tokens": 2,
                    "token_budget": 4, "requests": 2, "step_ms": 1}),
                ("decode", "pd_request", {"role": "decode", "prompt_tokens": 3, "completion_tokens": 2}),
            ]
            def write():
                path.write_text("\n".join(f"[pod/pd-{role}-0/worker] INFO: {kind} " + json.dumps(data)
                                          for role, kind, data in records))
            write()
            metadata = {"scheduler_config": {"token_budget": 4, "max_num_seqs": 2}}
            result = report.scheduler_diagnostics(raw, metadata)
            self.assertEqual(result["roles"]["aggregate"]["mixed_steps"], 1)
            self.assertTrue(result["computed_token_totals_match_requests"])
            records[-1][2]["completion_tokens"] = 3
            write()
            with self.assertRaisesRegex(ValueError, "counts differ"):
                report.scheduler_diagnostics(raw, metadata)
            records[0][2]["token_budget"] = 2
            write()
            with self.assertRaisesRegex(ValueError, "budget violation"):
                report.scheduler_diagnostics(raw, metadata)

    def test_scheduled_profile_has_separate_namespace_and_larger_admission_limit(self):
        config = json.loads((ROOT / "config/benchmarks/pd-scheduled.json").read_text())
        benchmark.validate_config(config, "token-budget")
        with self.assertRaises(ValueError):
            benchmark.validate_config(config)
        with self.assertRaises(ValueError):
            benchmark.profile(2, "token-budget")
        profile = benchmark.profile(4, "token-budget")
        self.assertEqual(profile["namespace"], "pd-comparison-4-scheduled")
        self.assertTrue(all(path.is_file() for path in profile["values"].values()))

    def setUp(self):
        self.config = json.loads((ROOT / "config/benchmarks/pd.json").read_text())
        self.template = next(d for d in render(ROOT / "k8s/aiperf/profiles/pd.yaml") if d["kind"] == "Job")

    def test_grid_and_mixed_use_same_budget_seed_and_endpoint(self):
        jobs = [benchmark.job_manifest(self.template, self.config, group, "test", "/results/test")
                for group in ("grid", "mixed")]
        for job in jobs:
            client = job["spec"]["template"]["spec"]["containers"][0]
            args = client["args"]
            self.assertEqual(args[args.index("--request-count") + 1], "32")
            self.assertEqual(args[args.index("--random-seed") + 1], "42")
            self.assertIn("--parameter-sweep-same-seed", args)
            self.assertEqual(client["resources"], self.template["spec"]["template"]["spec"]["containers"][0]["resources"])
        grid = jobs[0]["spec"]["template"]["spec"]["containers"][0]["args"]
        self.assertNotIn("--sequence-distribution", grid)
        self.assertEqual(grid[grid.index("--isl") + 1], "64,256,704")
        self.assertEqual(grid[grid.index("--osl") + 1], "16,64,256")

    def test_unsupported_limits_and_invalid_probabilities_fail(self):
        benchmark.validate_config(self.config)
        for changed in ({"concurrencies": [16]}, {"output_tokens": [512]}, {"input_tokens": [768]},
                        {"requests": 1}, {"repetitions": 0}, {"seed": -1},
                        {"mixed_distribution": "64,64:30;704,16:30"}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                benchmark.validate_config({**self.config, **changed})

    def test_profiles_and_slot_validation_keep_topologies_separate(self):
        for slots in (2, 4):
            p = benchmark.profile(slots)
            self.assertEqual(p['workers'], {'aggregated':slots, 'prefill':1, 'decode':slots-1})
            self.assertEqual(p['namespace'], 'pd-comparison-4' if slots == 4 else 'pd-comparison')
            self.assertTrue(all(path.is_file() for path in p['values'].values()))
            job = benchmark.job_manifest(self.template, self.config, 'grid', 'test', '/results/test', p['namespace'])
            self.assertEqual(job['metadata']['namespace'], p['namespace'])
            node = {'metadata':{'labels':{'nvidia.com/mps.capable':'true'}},
                    'status':{'allocatable':{'nvidia.com/gpu.shared':str(slots)}}}
            benchmark.check_slots({'items':[node]}, slots)
            for nodes in ([], [node, node]):
                with self.assertRaises(RuntimeError):
                    benchmark.check_slots({'items':nodes}, slots)
            with self.assertRaises(RuntimeError):
                benchmark.check_slots({'items':[node]}, 6-slots)
        self.assertEqual(self.template['metadata']['namespace'], 'pd-comparison')

    def test_unmatched_payloads_or_actual_lengths_fail(self):
        a = {"repetition": 1, "workload": "mixed", "concurrency": 8, "mode": "aggregated",
             "dataset_sha256": "a", "length_counts": {"94/256": 16, "734/16": 16}, "requests": 32}
        b = {**a, "mode": "disaggregated"}
        benchmark.check_pairs([a, b])
        for changed in ({"dataset_sha256": "b"}, {"length_counts": {"94/256": 15, "734/16": 17}}, {"requests": 31}):
            with self.assertRaises(RuntimeError):
                benchmark.check_pairs([a, {**b, **changed}])
        with self.assertRaises(RuntimeError):
            benchmark.check_pairs([a, a])

    def test_p95_pools_requests_and_throughput_averages_repetitions(self):
        a = {"workload": "i64-o16", "concurrency": 1, "mode": "aggregated", "requests": 2, "errors": 0,
             "latencies_ms": [10, 20], "ttfts_ms": [1, 2], **{m: 10 for m in benchmark.METRICS}}
        b = {**a, "latencies_ms": [30, 100], "ttfts_ms": [3, 10], "output_tokens_per_second": 20}
        row = benchmark.summarize([a, b])[0]
        self.assertEqual(row["requests"], 4)
        self.assertEqual(row["output_tokens_per_second"], 15)
        self.assertEqual(row["latency_p95_ms"], 100)
        self.assertEqual(row["ttft_p95_ms"], 10)

    def test_worker_restart_invalidates_measurement_even_after_recovery(self):
        pod = {"metadata": {"name": "pd-router"}, "status": {"containerStatuses": [
            {"name": "router", "ready": True, "restartCount": 0}]}}
        benchmark.check_workers({"items": [pod]})
        pod["status"]["containerStatuses"][0].update(
            restartCount=1, lastState={"terminated": {"reason": "OOMKilled"}})
        with self.assertRaisesRegex(RuntimeError, "pd-router/router: OOMKilled"):
            benchmark.check_workers({"items": [pod]})

    def test_partial_report_keeps_only_full_paired_repetitions(self):
        config = {**self.config, "input_tokens": [64], "output_tokens": [16], "concurrencies": [1, 2],
                  "mixed_distribution": ""}
        rows = [{"repetition": 1, "mode": mode, "workload": "i64-o16", "concurrency": c,
                 "dataset_sha256": "same", "length_counts": {"94/16": 32}, "requests": 32}
                for c in (1, 2) for mode in benchmark.MODES]
        incomplete = [{**r, "repetition": 2} for r in rows[:-1]]
        self.assertEqual(benchmark.completed_repetitions(rows + incomplete, config), rows)
        with self.assertRaisesRegex(ValueError, "No complete paired"):
            benchmark.completed_repetitions(incomplete, config)

    def test_bad_exports_are_not_reported_as_successful_measurements(self):
        config = {**self.config, "input_tokens": [64], "output_tokens": [16], "concurrencies": [1], "requests": 1}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = {"input_config": {"phases": [{"name": "profiling", "concurrency": 1}],
                                     "datasets": [{"prompts": {"isl": {"mean": 64}, "osl": {"mean": 16}}}]},
                    "request_count": {"avg": 1}, **{m: {"avg": 1} for m in benchmark.METRICS.values()}}
            record = {"metadata": {"benchmark_phase": "profiling"}, "metrics": {
                "osl_mismatch_diff_pct": {"value": 0}, "input_sequence_length": {"value": 94},
                "output_sequence_length": {"value": 16}, "request_latency": {"value": 10}, "time_to_first_token": {"value": 2}}}
            (root / "profile_export_aiperf.json").write_text(json.dumps(data))
            (root / "profile_export.jsonl").write_text(json.dumps(record) + "\n")
            (root / "inputs.json").write_text(json.dumps({"data": [{"payloads": [{"messages": ["hello"]}]}]}))
            rows = benchmark.collect_exports(root, config, 1, "aggregated", "grid")
            self.assertEqual(rows[0]["length_counts"], {"94/16": 1})
            record["metrics"]["osl_mismatch_diff_pct"]["value"] = -1
            (root / "profile_export.jsonl").write_text(json.dumps(record) + "\n")
            with self.assertRaisesRegex(RuntimeError, "Output token"):
                benchmark.collect_exports(root, config, 1, "aggregated", "grid")
            data["error_summary"] = ["timeout"]
            (root / "profile_export_aiperf.json").write_text(json.dumps(data))
            with self.assertRaisesRegex(RuntimeError, "Failed AIPerf"):
                benchmark.collect_exports(root, config, 1, "aggregated", "grid")


if __name__ == "__main__":
    unittest.main()
