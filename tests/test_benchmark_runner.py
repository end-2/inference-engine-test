"""Regression checks for benchmark image reuse, failure detection, and reports."""

import importlib.util
import csv
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("benchmark", Path(__file__).resolve().parents[1] / "scripts/run-benchmark.py")
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.context = Path(self.temp.name)
        (self.context / "Dockerfile").write_text("FROM scratch\n")

    def check_image(self, matching_source=True, matching_node=True, context=True):
        commands = []
        fingerprint = benchmark.source_hash(self.context)
        def execute(*args, **kwargs):
            nonlocal matching_node
            commands.append(args)
            if "load-image" in args:
                matching_node = True
            if args[:3] == ("docker", "image", "inspect"):
                output = [{"Id": "sha256:new", "Config": {"Labels": {
                    benchmark.SOURCE_LABEL: fingerprint if matching_source else "old"}}}]
            elif args[:2] == ("docker", "exec"):
                output = {"status": {"id": "sha256:new" if matching_node else "sha256:old"}}
            else:
                output = {}
            return subprocess.CompletedProcess(args, 0, json.dumps(output), "")
        with patch.object(benchmark, "run", side_effect=execute), patch.object(
            benchmark, "kube_json", return_value={"items": [{"metadata": {"name": "node"}}]}
        ):
            benchmark.ensure_image("local/test:1", self.context if context else None)
        return commands

    def test_identical_image_skips_build_and_load(self):
        commands = self.check_image()
        self.assertFalse(any(command[:2] == ("docker", "build") for command in commands))
        self.assertFalse(any("load-image" in command for command in commands))

    def test_changed_source_rebuilds(self):
        commands = self.check_image(matching_source=False)
        self.assertTrue(any(command[:2] == ("docker", "build") for command in commands))

    def test_same_tag_different_node_image_reloads(self):
        commands = self.check_image(matching_node=False)
        self.assertTrue(any("load-image" in command for command in commands))

    def test_prebuilt_image_does_not_require_source_label(self):
        commands = self.check_image(matching_source=False, context=False)
        self.assertFalse(any(command[:2] == ("docker", "build") for command in commands))

    def test_source_fingerprint_detects_content_changes(self):
        previous = benchmark.source_hash(self.context)
        (self.context / "Dockerfile").write_text("FROM busybox\n")
        self.assertNotEqual(previous, benchmark.source_hash(self.context))

    def test_render_handles_multiple_kubectl_json_documents(self):
        result = subprocess.CompletedProcess([], 0, '{"kind":"Deployment"}\n{"kind":"Service"}\n', "")
        with patch.object(benchmark, "kube", return_value=result):
            rendered = benchmark.render(self.context)
        self.assertEqual([item["kind"] for item in rendered["items"]], ["Deployment", "Service"])

    def test_containerd_manifest_id_is_compared_to_tag_target(self):
        inspected = {"status": {"id": "sha256:config", "repoTags": ["docker.io/local/test:1"]}}
        responses = [subprocess.CompletedProcess([], 0, json.dumps(inspected), ""),
                     subprocess.CompletedProcess([], 0, "docker.io/local/test:1 manifest sha256:manifest 123\n", "")]
        info = {"Id": "sha256:manifest", "Descriptor": {"digest": "sha256:manifest"}}
        with patch.object(benchmark, "run", side_effect=responses):
            self.assertTrue(benchmark.image_loaded("node", "local/test:1", info))

    def test_job_failure_is_not_waited_until_timeout(self):
        state = {"status": {"conditions": [{"type": "Failed", "status": "True", "reason": "DeadlineExceeded"}]}}
        with patch.object(benchmark, "kube_json", return_value=state), self.assertRaisesRegex(RuntimeError, "DeadlineExceeded"):
            benchmark.wait_job("job", 3600)

    def test_failed_requests_are_not_reported_as_success(self):
        path = self.context / "profile_export_aiperf.json"
        benchmark.write_json(path, {"request_count": {"avg": 3}, "error_request_count": {"avg": 1}})
        with self.assertRaises(RuntimeError):
            benchmark.collect_summary(path, 1)
        benchmark.write_json(path, {"request_count": {"avg": 4}, "time_to_first_token": {"avg": 5, "p95": 8}})
        result = benchmark.collect_summary(path, 2)
        self.assertEqual(result["requests"], 4)
        self.assertEqual(result["ttft_p95_ms"], 8)

    def test_early_eos_is_rejected(self):
        path = self.context / "profile_export.jsonl"
        record = {"metadata": {"benchmark_phase": "profiling"},
                  "metrics": {"osl_mismatch_diff_pct": {"value": -50}}}
        path.write_text(json.dumps(record) + "\n")
        with self.assertRaisesRegex(RuntimeError, "before the requested length"):
            benchmark.validate_output_lengths(path)
        record["metrics"]["osl_mismatch_diff_pct"]["value"] = 0
        path.write_text(json.dumps(record) + "\n")
        self.assertEqual(benchmark.validate_output_lengths(path)["checked_requests"], 1)

    def test_cpu_units_and_repeated_kubelet_timestamps(self):
        sampler = benchmark.ResourceSampler(self.context, ["node"], "server-id", "job")
        stats = {"cpu": {"time": "2026-09-19T08:00:00Z", "usageNanoCores": 2_500_000_000,
                         "usageCoreNanoSeconds": 10_000_000_000}}
        first = sampler.row("now", "node", "node", "node", stats)
        self.assertEqual(first["cpu_cores"], 2.5)
        self.assertEqual(first["cpu_percent_one_core"], 250)
        self.assertIsNone(sampler.row("later", "node", "node", "node", stats)["cpu_interval_cores"])
        stats["cpu"].update(time="2026-09-19T08:00:10Z", usageCoreNanoSeconds=30_000_000_000)
        self.assertEqual(sampler.row("later", "node", "node", "node", stats)["cpu_interval_cores"], 2)

    def test_raw_resources_preserve_counters_and_filter_unrelated_pods(self):
        sampler = benchmark.ResourceSampler(self.context, ["node"], "server-id", "job")
        cpu = {"time": "2026-09-19T08:00:00Z", "usageCoreNanoSeconds": 123,
               "usageNanoCores": 456, "psi": {"some": {"total": 7}}}
        pods = [{"podRef": {"uid": uid, "name": name, "namespace": "default"}, "cpu": cpu}
                for uid, name in [("server-id", "server"), ("client-id", "job-abc"),
                                  ("unrelated-id", "reader")]]
        response = subprocess.CompletedProcess([], 0, json.dumps({"node": {"cpu": cpu}, "pods": pods}), "")
        with patch.object(benchmark, "kube", return_value=response):
            sampler.sample()
        raw = json.loads((self.context / "resources.jsonl").read_text())
        self.assertEqual(raw["pods"], pods[:2])
        self.assertEqual(raw["node"]["cpu"], cpu)
        self.assertEqual(sampler.validate()["pod_cpu_samples"], {"inference": 1, "aiperf": 1})

    def test_resource_failures_are_recorded_and_fail_measurement(self):
        sampler = benchmark.ResourceSampler(self.context, ["node"], "server-id", "job")
        with patch.object(benchmark, "kube", side_effect=RuntimeError("Forbidden")):
            with self.assertRaisesRegex(RuntimeError, "Resource collection failed"):
                sampler.sample()
        self.assertIn("Forbidden", (self.context / "resources.jsonl").read_text())
        with self.assertRaisesRegex(RuntimeError, "Missing resource samples"):
            sampler.validate()

    def test_request_export_keeps_phases_timestamps_and_chunk_arrays(self):
        source = self.context / "profile_export.jsonl"
        records = [{"metadata": {"benchmark_phase": phase, "request_start_ns": 1234567890123456789},
                    "metrics": {"request_latency": {"value": 12.3, "unit": "ms"},
                                "inter_chunk_latency": {"value": [1.2, 3.4], "unit": "ms"}}}
                   for phase in ["warmup", "profiling"]]
        source.write_text("\n".join(json.dumps(record) for record in records))
        benchmark.export_requests(source, self.context / "requests.csv")
        with (self.context / "requests.csv").open() as result:
            rows = list(csv.DictReader(result))
        self.assertEqual([row["benchmark_phase"] for row in rows], ["warmup", "profiling"])
        self.assertEqual(rows[1]["request_start_ns"], "1234567890123456789")
        self.assertEqual(json.loads(rows[1]["inter_chunk_latency_ms"]), [1.2, 3.4])


if __name__ == "__main__":
    unittest.main()
