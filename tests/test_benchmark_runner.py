"""Regression checks for benchmark image reuse, failure detection, and reports."""

import importlib.util
import csv
import json
import os
from pathlib import Path
import subprocess
import sys
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

    def check_image(self, matching_source=True, matching_node=True, context=True, target=None):
        commands = []
        fingerprint = benchmark.source_hash(self.context, target)
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
            benchmark.ensure_image("local/test:1", self.context if context else None, target)
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

    def test_build_selects_requested_inference_target(self):
        commands = self.check_image(matching_source=False, target="enhanced-cache")
        build = next(command for command in commands if command[:2] == ("docker", "build"))
        self.assertEqual(build[build.index("--target") + 1], "enhanced-cache")
        self.assertEqual(build[-1], self.context)

    def test_shared_source_fingerprint_includes_target_and_base_code(self):
        base = self.context / "base"
        base.mkdir()
        source = base / "server.py"
        source.write_text("version = 1\n")
        targets = ("base", "enhanced-batch", "enhanced-cache")
        previous = {target: benchmark.source_hash(self.context, target) for target in targets}
        self.assertEqual(len(set(previous.values())), len(targets))
        source.write_text("version = 2\n")
        for target in targets:
            self.assertNotEqual(previous[target], benchmark.source_hash(self.context, target))

    def test_matching_target_reuses_image(self):
        commands = self.check_image(target="enhanced-batch")
        self.assertFalse(any(command[:2] == ("docker", "build") for command in commands))

    def test_default_and_custom_build_contexts_select_targets(self):
        for options, context, target in [
            ([], benchmark.ROOT / "src", "base"),
            (["--build-target", "enhanced-cache"], benchmark.ROOT / "src", "enhanced-cache"),
            (["--build-context", str(self.context)], self.context, None),
            (["--build-context", ""], None, None),
        ]:
            with self.subTest(options=options), patch.dict(os.environ, {}, clear=True), patch(
                "sys.argv", ["run-benchmark.py", *options]
            ):
                args = benchmark.parse_args()
                self.assertEqual(args.build_context, context.resolve() if context else None)
                self.assertEqual(args.build_target, target)

    def test_render_handles_multiple_kubectl_json_documents(self):
        result = subprocess.CompletedProcess([], 0, '{"kind":"Deployment"}\n{"kind":"Service"}\n', "")
        with patch.object(benchmark, "kube", return_value=result):
            rendered = benchmark.render(self.context)
        self.assertEqual([item["kind"] for item in rendered["items"]], ["Deployment", "Service"])

    def cache_deployment(self):
        container = {"name": "api", "image": "local/cache:1", "args": ["--cache-dir", "/cache"],
                     "volumeMounts": [{"name": "cache", "mountPath": "/cache"}]}
        deployment = {"metadata": {"name": "inference"}, "spec": {"template": {"spec": {
            "containers": [container], "volumes": [
                {"name": "cache", "persistentVolumeClaim": {"claimName": "cache-pvc"}}]}}}}
        return deployment, container

    def test_cache_policy_defaults_and_overrides(self):
        for environment, options, expected in [
            ({}, [], "preserve"),
            ({}, ["--cache-policy", "clear-before-sweep"], "clear-before-sweep"),
            ({"BENCHMARK_CACHE_POLICY": "clear-per-concurrency"}, [], "clear-per-concurrency"),
            ({"BENCHMARK_CACHE_POLICY": "clear-per-concurrency"}, ["--cache-policy", "preserve"], "preserve"),
        ]:
            with self.subTest(options=options, environment=environment), patch.dict(
                os.environ, environment, clear=True
            ), patch("sys.argv", ["run-benchmark.py", *options]):
                self.assertEqual(benchmark.parse_args().cache_policy, expected)

    def test_cache_clear_schedule_separates_sweeps_and_concurrency_steps(self):
        for policy, expected in [("preserve", [False] * 4),
                                 ("clear-before-sweep", [True, False, False, False]),
                                 ("clear-per-concurrency", [True] * 4)]:
            with self.subTest(policy=policy):
                self.assertEqual([benchmark.clears_cache(policy, i) for i in range(4)], expected)

    def test_cache_clearing_requires_explicit_dedicated_pvc_mount(self):
        deployment, container = self.cache_deployment()
        self.assertEqual(benchmark.cache_volume(deployment, container)["pvc"], "cache-pvc")
        for arguments in ([], ["--cache-dir", "/"], ["--cache-dir", "/cache/subdirectory"],
                          ["--cache-dir", "/cache/../model"]):
            with self.subTest(arguments=arguments), patch.dict(container, args=arguments):
                with self.assertRaises(RuntimeError):
                    benchmark.cache_volume(deployment, container)
        for setting in ({"readOnly": True}, {"subPath": "cache"}, {"subPathExpr": "$(CACHE)"}):
            with self.subTest(setting=setting), patch.dict(container["volumeMounts"][0], setting):
                with self.assertRaises(RuntimeError):
                    benchmark.cache_volume(deployment, container)
        deployment["spec"]["template"]["spec"]["volumes"][0] = {
            "name": "cache", "hostPath": {"path": "/cache"}}
        with self.assertRaisesRegex(RuntimeError, "PVC"):
            benchmark.cache_volume(deployment, container)

    def test_cache_script_removes_hidden_files_without_following_symlinks(self):
        cache = self.context / "cache"
        namespace = cache / "namespace"
        namespace.mkdir(parents=True)
        (namespace / ".lock").write_text("")
        (namespace / "state.bin").write_bytes(b"cached KV")
        outside = self.context / "outside"
        outside.mkdir()
        (outside / "model.gguf").write_bytes(b"keep model")
        (cache / "external").symlink_to(outside, target_is_directory=True)
        script = "from pathlib import Path\nPath.is_mount = lambda self: True\n" + benchmark.CLEAR_CACHE_SCRIPT
        result = subprocess.run([sys.executable, "-c", script, str(cache)],
                                text=True, capture_output=True, check=True)
        record = json.loads(result.stdout)
        self.assertEqual(record["remaining_entries"], 0)
        self.assertEqual(record["removed_files"], 2)
        self.assertEqual(record["removed_bytes"], 9)
        self.assertEqual(list(cache.iterdir()), [])
        self.assertEqual((outside / "model.gguf").read_bytes(), b"keep model")

    def test_cache_script_rejects_an_unmounted_directory(self):
        result = subprocess.run([sys.executable, "-c", benchmark.CLEAR_CACHE_SCRIPT, str(self.context)],
                                text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.context / "Dockerfile").exists())

    def run_cache_cleanup(self, *, wait_error=None, consumers=()):
        deployment, container = self.cache_deployment()
        cache = benchmark.cache_volume(deployment, container)
        events = []
        responses = iter([[{"metadata": {"name": "terminating"}}], []])
        def pods(_):
            response = next(responses)
            events.append(("pods", len(response)))
            return response
        def kube(*args, **kwargs):
            events.append(args)
            return subprocess.CompletedProcess(args, 0, json.dumps({
                "remaining_entries": 0, "directory": "/cache", "removed_files": 5}), "")
        with patch.object(benchmark, "kube", side_effect=kube), patch.object(
            benchmark, "deployment_pods", side_effect=pods
        ), patch.object(benchmark, "kube_json", return_value={"items": list(consumers)}), patch.object(
            benchmark, "wait_job", side_effect=wait_error
        ), patch.object(benchmark.time, "sleep"):
            try:
                result = benchmark.clear_pvc_cache(deployment, container, cache, "clean", self.context, 60)
            except RuntimeError as exc:
                result = exc
        return events, result

    def test_cache_clearing_waits_for_shutdown_and_removes_cleaner_before_restart(self):
        events, result = self.run_cache_cleanup()
        create = next(event for event in events if event[0] == "create")
        delete = next(event for event in events if event[0] == "delete")
        self.assertEqual(events[0], ("scale", "deployment/inference", "--replicas=0"))
        self.assertLess(events.index(("pods", 0)), events.index(create))
        self.assertLess(events.index(delete), events.index(("scale", "deployment/inference", "--replicas=1")))
        self.assertIn("--cascade=foreground", delete)
        self.assertEqual(result["pvc"], "cache-pvc")
        self.assertEqual(json.loads((self.context / "cache-clear.json").read_text())["remaining_entries"], 0)
        spec = json.loads((self.context / "cache-clear-job.json").read_text())["spec"]["template"]["spec"]
        self.assertEqual(len(spec["volumes"]), 1)
        resources = spec["containers"][0]["resources"]
        self.assertEqual(resources["requests"], resources["limits"])

    def test_cache_cleanup_failure_stops_job_before_restoring_inference(self):
        events, result = self.run_cache_cleanup(wait_error=RuntimeError("cleanup failed"))
        self.assertIsInstance(result, RuntimeError)
        self.assertEqual(events[-2][0], "delete")
        self.assertEqual(events[-1], ("scale", "deployment/inference", "--replicas=1"))
        self.assertFalse((self.context / "cache-clear.json").exists())

    def test_cache_cleanup_refuses_a_pvc_used_by_another_pod(self):
        consumer = {"metadata": {"name": "other"}, "status": {"phase": "Running"},
                    "spec": {"volumes": [{"persistentVolumeClaim": {"claimName": "cache-pvc"}}]}}
        events, result = self.run_cache_cleanup(consumers=[consumer])
        self.assertRegex(str(result), "still used by Pods: other")
        self.assertFalse(any(event[0] == "create" for event in events))
        self.assertEqual(events[-1], ("scale", "deployment/inference", "--replicas=1"))

    def test_containerd_manifest_id_is_compared_to_tag_target(self):
        inspected = {"status": {"id": "sha256:config", "repoTags": ["docker.io/local/test:1"]}}
        responses = [subprocess.CompletedProcess([], 0, json.dumps(inspected), ""),
                     subprocess.CompletedProcess([], 0, "docker.io/local/test:1 manifest sha256:manifest 123\n", "")]
        info = {"Id": "sha256:manifest", "Descriptor": {"digest": "sha256:manifest"}}
        with patch.object(benchmark, "run", side_effect=responses):
            self.assertTrue(benchmark.image_loaded("node", "local/test:1", info))

    def test_existing_tag_with_stale_manifest_is_not_reused(self):
        inspected = {"status": {"id": "sha256:old-config", "repoTags": ["docker.io/local/test:1"]}}
        responses = [subprocess.CompletedProcess([], 0, json.dumps(inspected), ""),
                     subprocess.CompletedProcess([], 0, "docker.io/local/test:1 manifest sha256:old 123\n", "")]
        info = {"Id": "sha256:new", "Descriptor": {"digest": "sha256:new"}}
        with patch.object(benchmark, "run", side_effect=responses):
            self.assertFalse(benchmark.image_loaded("node", "local/test:1", info))

    def test_image_index_resolves_to_platform_manifest(self):
        inspected = {"status": {"id": "sha256:config", "repoTags": ["docker.io/local/test:1"]}}
        selected = {"Id": "sha256:manifest", "Descriptor": {"digest": "sha256:manifest"}}
        responses = [subprocess.CompletedProcess([], 0, json.dumps(inspected), ""),
                     subprocess.CompletedProcess([], 0, json.dumps([selected]), ""),
                     subprocess.CompletedProcess([], 0, "docker.io/local/test:1 manifest sha256:manifest 123\n", "")]
        info = {"Id": "sha256:index", "Os": "linux", "Architecture": "arm64",
                "Descriptor": {"digest": "sha256:index", "mediaType": "application/vnd.oci.image.index.v1+json"}}
        with patch.object(benchmark, "run", side_effect=responses) as execute:
            self.assertTrue(benchmark.image_loaded("node", "local/test:1", info))
        self.assertEqual(execute.call_args_list[1].args,
                         ("docker", "image", "inspect", "--platform", "linux/arm64", "local/test:1"))

    def test_invalid_node_image_metadata_is_not_reused(self):
        with patch.object(benchmark, "run", return_value=subprocess.CompletedProcess([], 0, "invalid", "")):
            self.assertFalse(benchmark.image_loaded("node", "local/test:1", {"Id": "sha256:new"}))

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
