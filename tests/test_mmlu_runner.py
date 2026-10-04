"""Verify Pod evaluation staging, result collection, and Helm resource contracts."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from manifest_support import render


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("mmlu_runner", ROOT / "scripts/run-mmlu.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class MMLURunnerTests(unittest.TestCase):
    def test_defaults_use_cluster_service_and_forward_scoring_options(self):
        with patch.dict(os.environ, {}, clear=True):
            args = runner.parse_args(["--backend", "llamacpp", "--few-shot", "5",
                                      "--limit", "7", "--min-accuracy", "0", "--subjects", "algebra"])
        self.assertEqual(args.url, "http://base-llamacpp:8000")
        command = runner.evaluator_args(args)
        self.assertIn("/work/data", command)
        self.assertIn("/work/results/summary.json", command)
        self.assertEqual(command[command.index("--min-accuracy") + 1], "0.0")
        self.assertEqual(command[command.index("--few-shot") + 1], "5")
        self.assertEqual(command[-2:], ["--subjects", "algebra"])
        self.assertNotIn("--download-data", command)

    def test_chart_staging_and_job_share_storage_and_node(self):
        objects = render(ROOT / "k8s/mmlu", "--set", "name=mmlu-test,node=worker")
        pvc, reader, job = (next(obj for obj in objects if obj["kind"] == kind)
                            for kind in ("PersistentVolumeClaim", "Pod", "Job"))
        self.assertEqual(job["spec"]["backoffLimit"], 0)
        for pod in (reader["spec"], job["spec"]["template"]["spec"]):
            self.assertEqual(pod["nodeSelector"]["kubernetes.io/hostname"], "worker")
            self.assertFalse(pod["automountServiceAccountToken"])
            self.assertTrue(pod["securityContext"]["runAsNonRoot"])
            self.assertEqual(pod["volumes"][0]["persistentVolumeClaim"]["claimName"], pvc["metadata"]["name"])
            self.assertEqual(pod["containers"][0]["imagePullPolicy"], "Never")
        staging = render(ROOT / "k8s/mmlu", "--set", "job.enabled=false")
        self.assertEqual({obj["kind"] for obj in staging}, {"PersistentVolumeClaim", "Pod"})

    def test_image_loader_uses_supported_cluster_commands(self):
        for device, expected_nodes in (("cpu", None), ("gpu", ["node"])):
            with self.subTest(device=device), patch.object(runner.benchmark, "ensure_image") as ensure:
                runner.prepare_image("local/mmlu:test", "node", device)
                self.assertEqual(ensure.call_args.kwargs["load_nodes"], expected_nodes)

    def run_fixture(self, passed=True, report_available=True, keep=False):
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "data/test"
            data.mkdir(parents=True)
            (data / "algebra_test.csv").write_text("Question,a,b,c,d,A\n")
            output = root / "summary.json"
            report = {"complete": True, "passed": passed, "summary": {"accuracy": 1 if passed else 0}}

            def kube(*command, **kwargs):
                calls.append(command)
                self.assertEqual(command[:2], ("--namespace", "eval"))
                if command[2] == "cp" and str(command[3]).endswith(":/work/results/."):
                    target = Path(command[4])
                    (target / "summary.jsonl").write_text('{"status":"CORRECT"}\n')
                    if report_available:
                        (target / "summary.json").write_text(json.dumps(report))
                if command[2] == "cp" and str(command[4]).endswith(":/work/data"):
                    self.assertTrue((Path(command[3]) / "test/algebra_test.csv").exists())
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            nodes = {"items": [{"metadata": {"name": "node", "labels": {
                "kubernetes.io/hostname": "node", "node-role.kubernetes.io/control-plane": ""}}}]}
            with patch.dict(os.environ), patch.object(runner, "prepare_image", return_value={}), \
                 patch.object(runner.benchmark, "kube_json", return_value=nodes), \
                 patch.object(runner.benchmark, "kube", side_effect=kube), \
                 patch.object(runner.benchmark, "wait_job", side_effect=None if passed else RuntimeError("Job failed")):
                code = runner.main(["--data-dir", str(root / "data"), "--output", str(output),
                                    "--namespace", "eval"] + (["--keep-resources"] if keep else []))
            metadata = json.loads((root / "summary-run/run.json").read_text())
            self.assertTrue(output.with_suffix(".jsonl").is_file())
            self.assertEqual(output.exists(), report_available)
        return code, metadata, calls

    def test_success_collects_before_cleanup(self):
        code, metadata, calls = self.run_fixture()
        self.assertEqual(code, 0)
        self.assertTrue(metadata["collected"])
        copies = [index for index, call in enumerate(calls) if call[2] == "cp"]
        deletion = next(index for index, call in enumerate(calls) if call[2:4] == ("delete", "job,pod,pvc"))
        self.assertGreater(deletion, max(copies))

    def test_failed_evaluation_still_collects_and_returns_failure(self):
        code, metadata, calls = self.run_fixture(passed=False)
        self.assertEqual(code, 1)
        self.assertTrue(metadata["collected"])
        self.assertTrue(any(call[2:4] == ("delete", "job,pod,pvc") for call in calls))

    def test_missing_report_preserves_storage_and_partial_journal(self):
        code, metadata, calls = self.run_fixture(passed=False, report_available=False)
        self.assertEqual(code, 1)
        self.assertFalse(metadata["collected"])
        self.assertFalse(any(call[2:4] == ("delete", "job,pod,pvc") for call in calls))

    def test_keep_resources_preserves_successful_job(self):
        code, _, calls = self.run_fixture(keep=True)
        self.assertEqual(code, 0)
        self.assertFalse(any(call[2] == "delete" for call in calls))

    def test_benchmark_wait_uses_requested_namespace(self):
        with patch.object(runner.benchmark, "kube_json", return_value={"status": {
                "conditions": [{"type": "Complete", "status": "True"}]}}) as query:
            runner.benchmark.wait_job("test", 1, namespace="eval")
        query.assert_called_once_with("get", "job", "test", "--namespace", "eval")


if __name__ == "__main__":
    unittest.main()
