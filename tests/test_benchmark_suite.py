"""Checks for repetition scheduling and statistics across independent sweeps."""

from collections import Counter
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("suite", Path(__file__).resolve().parents[1] / "scripts/run-benchmark-suite.py")
suite = importlib.util.module_from_spec(spec)
spec.loader.exec_module(suite)


class SuiteTests(unittest.TestCase):
    def test_transformers_runs_each_variant_three_times_with_independent_cache(self):
        cases = suite.plan(3)
        self.assertEqual(len(cases), 9)
        self.assertEqual(Counter(case["condition"] for case in cases),
                         {"base": 3, "enhanced-batch": 3, "enhanced-cache": 3})
        for repetition in range(1, 4):
            group = [case for case in cases if case["repetition"] == repetition]
            self.assertEqual(group[0]["condition"], suite.TRANSFORMERS_CONDITIONS[repetition - 1][0])
        for case in cases:
            schedule = [suite.benchmark.clears_cache(case["cache_policy"], i) for i in range(4)]
            self.assertEqual(schedule, [case["variant"] == "enhanced-cache", False, False, False])

    def test_transformers_command_selects_matching_backend_image_and_manifests(self):
        metadata = {"backend": "transformers", "image_tag": "test", "benchmark_image": "local/aiperf:test",
                    "inference_node": "worker2", "benchmark_node": "worker2"}
        for case in suite.plan(1, "transformers"):
            command = suite.case_command(case, metadata, Path("reports"))
            options = dict(zip(command[2::2], command[3::2], strict=True))
            self.assertEqual(options["--backend"], "transformers")
            self.assertEqual(options["--image"], f"local/transformers-{case['variant']}:test")
            self.assertEqual(options["--manifests"], str(suite.ROOT / f"k8s/transformers-{case['variant']}"))
            self.assertEqual(options["--deployment"], "transformers-base")
            self.assertEqual(options["--api-url"], "http://transformers-base:8000")
            self.assertEqual(options["--cache-policy"], case["cache_policy"])
            self.assertEqual(options["--build-context"], "")
            self.assertEqual(options["--benchmark-build-context"], "")

    def test_transformers_cache_is_included_in_aggregation(self):
        rows = [{"condition": "enhanced-cache", "concurrency": 8, "output_tokens_per_second": value}
                for value in (40, 50, 60)]
        result, = suite.aggregate(rows)
        self.assertEqual(result["condition"], "enhanced-cache")
        self.assertEqual(result["repetitions"], 3)
        self.assertEqual(result["output_tokens_per_second_mean"], 50)

    def test_each_condition_runs_three_times_in_rotated_order(self):
        cases = suite.plan(3, "llamacpp")
        self.assertEqual(len(cases), 12)
        self.assertEqual(Counter(case["condition"] for case in cases),
                         {label: 3 for label, _, _ in suite.CONDITIONS})
        for repetition in range(1, 4):
            group = [case for case in cases if case["repetition"] == repetition]
            self.assertEqual(len({case["condition"] for case in group}), 4)
            self.assertEqual(group[0]["condition"], suite.CONDITIONS[repetition - 1][0])

    def test_preserved_cache_is_reset_only_at_the_start_of_each_sweep(self):
        for case in suite.plan(3, "llamacpp"):
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

    def test_cli_defaults_need_no_node_arguments(self):
        with patch.dict(os.environ, {}, clear=True), patch("sys.argv", ["run-benchmark-suite.py"]):
            args = suite.parse_args()
        self.assertEqual(args.backend, "transformers")
        self.assertEqual(args.repetitions, 3)
        self.assertIsNone(args.inference_node)
        self.assertIsNone(args.benchmark_node)
        self.assertFalse(args.skip_build)
        self.assertEqual(args.reports_dir, suite.ROOT / "docs/reports/transformers")

    def test_llamacpp_cli_routes_reports_and_variant_artifacts(self):
        with patch.dict(os.environ, {}, clear=True), patch("sys.argv", ["run-benchmark-suite.py", "--backend", "llamacpp"]):
            args = suite.parse_args()
        self.assertEqual(args.reports_dir, suite.ROOT / "docs/reports/llamacpp")
        metadata = {"backend": args.backend, "image_tag": "test", "benchmark_image": "local/aiperf:test",
                    "inference_node": "cp", "benchmark_node": "cp", "images": {}}
        for case in suite.plan(1, args.backend):
            command = suite.case_command(case, metadata, Path("reports"))
            options = dict(zip(command[2::2], command[3::2], strict=True))
            self.assertEqual(options["--image"], f"local/{case['variant']}-llamacpp:test")
            self.assertEqual(options["--manifests"], str(suite.ROOT / f"k8s/{case['variant']}-llamacpp"))
            self.assertEqual(options["--deployment"], "base-llamacpp")
            self.assertEqual(options["--api-url"], "http://base-llamacpp:8000")

    def test_archived_llama_suite_preserves_measured_image_names(self):
        metadata = {"backend": "llama", "image_tag": "old", "images": {"local/llama-base:old": {"id": "old"}}}
        self.assertEqual(suite.backend_for(metadata), "llamacpp")
        self.assertEqual(suite.inference_image(metadata, "base"), "local/llama-base:old")

    def test_preparation_builds_each_image_once_with_matching_targets(self):
        for backend in ("transformers", "llamacpp"):
            metadata = {"backend": backend, "image_tag": "test", "benchmark_image": "local/aiperf:test", "images": {}}
            with self.subTest(backend=backend), patch.object(suite.benchmark, "ensure_image", return_value={"id": "same"}) as ensure:
                suite.prepare_images(metadata, build=True)
            self.assertEqual(len(ensure.call_args_list), 4)
            for call, variant in zip(ensure.call_args_list[:3], ["base", "enhanced-batch", "enhanced-cache"], strict=True):
                target = f"transformers-{variant}" if backend == "transformers" else f"{variant}-llamacpp"
                self.assertEqual(call.args, (f"local/{target}:test", suite.ROOT / "src", target))
            self.assertEqual(ensure.call_args_list[-1].args, ("local/aiperf:test", suite.ROOT / "src/aiperf", None))

    def test_resume_reuses_recorded_images_and_rejects_changed_ids(self):
        image = "local/transformers-base:test"
        metadata = {"backend": "transformers", "image_tag": "test", "benchmark_image": "local/aiperf:test",
                    "images": {image: {"id": "original", "build_context": "recorded"}}}
        with patch.object(suite.benchmark, "ensure_image", return_value={"id": "changed"}) as ensure:
            with self.assertRaisesRegex(RuntimeError, "Image changed"):
                suite.prepare_images(metadata, build=True)
        ensure.assert_called_once_with(image, None, None)
        self.assertEqual(metadata["images"][image]["build_context"], "recorded")

    def test_skip_build_reuses_all_images(self):
        metadata = {"backend": "transformers", "image_tag": "test", "benchmark_image": "local/aiperf:test", "images": {}}
        with patch.object(suite.benchmark, "ensure_image", return_value={"id": "original"}) as ensure:
            suite.prepare_images(metadata, build=False)
        self.assertEqual(len(ensure.call_args_list), 4)
        self.assertTrue(all(call.args[1:] == (None, None) for call in ensure.call_args_list))

    def test_prepare_only_records_plan_without_starting_measurements(self):
        nodes = {"items": [{"metadata": {"name": "cp", "labels": {"node-role.kubernetes.io/control-plane": ""}},
                            "status": {"conditions": [{"type": "Ready", "status": "True"}]}}]}
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"LOCAL_K8S_STATE_DIR": temp}, clear=True), patch(
            "sys.argv", ["run-benchmark-suite.py", "--prepare-only", "--reports-dir", temp]
        ), patch.object(suite.benchmark, "run"), patch.object(suite.benchmark, "kube_json", side_effect=[nodes, {"items": []}]), patch.object(
            suite, "prepare_images"
        ) as prepare, patch.object(suite.subprocess, "run") as child:
            self.assertEqual(suite.main(), 0)
            metadata = json.loads(next(Path(temp).glob("benchmark-suite-*/run.json")).read_text())
        self.assertEqual(metadata["status"], "prepared")
        self.assertEqual(metadata["inference_node"], "cp")
        self.assertEqual(metadata["benchmark_node"], "cp")
        self.assertEqual(len(metadata["cases"]), 9)
        self.assertTrue(all(case["status"] == "pending" for case in metadata["cases"]))
        prepare.assert_called_once()
        child.assert_not_called()


if __name__ == "__main__":
    unittest.main()
