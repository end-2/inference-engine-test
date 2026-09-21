"""Check fault target isolation and recovery when an experiment fails."""

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "availability_runner", ROOT / "scripts/run-availability-test-transformers.py"
)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class AvailabilityRunnerTests(unittest.TestCase):
    def test_single_node_cluster_is_rejected_before_fault_target_selection(self):
        e = self.experiment(Path("/unused"))
        e.get = Mock(return_value={"items": [{
            "metadata": {"name": "test-control-plane", "labels": {}},
            "status": {"conditions": [{"type": "Ready", "status": "True"}]},
        }]})
        with self.assertRaisesRegex(RuntimeError, "two engine workers"):
            e.preflight()
        e.scale.assert_not_called()

    def setUp(self):
        self.node = {"metadata": {"labels": {"workload": "engine"}}}
        self.container = {
            "Config": {
                "Labels": {
                    "io.x-k8s.kind.cluster": "test",
                    "io.x-k8s.kind.role": "worker",
                }
            },
            "State": {"Running": True, "Paused": False},
        }

    def test_only_selected_kind_engine_worker_can_be_targeted(self):
        runner.validate_target(self.node, self.container, "test")
        wrong_cluster = copy.deepcopy(self.container)
        wrong_cluster["Config"]["Labels"]["io.x-k8s.kind.cluster"] = "other"
        control_plane = copy.deepcopy(self.node)
        control_plane["metadata"]["labels"][
            "node-role.kubernetes.io/control-plane"
        ] = ""
        monitor = {"metadata": {"labels": {"workload": "monitor"}}}
        for node, container in [
            (self.node, wrong_cluster),
            (control_plane, self.container),
            (monitor, self.container),
        ]:
            with self.subTest(node=node, container=container), self.assertRaises(
                RuntimeError
            ):
                runner.validate_target(node, container, "test")

    def experiment(self, root, mode="sigkill"):
        e = runner.Experiment.__new__(runner.Experiment)
        e.args = SimpleNamespace(scenario=mode + "-60s", cluster="test")
        e.k = ["kubectl", "--context", "kind-test"]
        e.ns = ["-n", "availability-test-transformers"]
        e.victim, e.survivor, e.monitor = "test-worker2", "test-worker3", "test-worker"
        e.mode, e.seconds = mode, 60
        e.children, e.observer = [], None
        e.fault_active, e.policy, e.s = False, None, None
        e.forward = Mock(return_value="http://127.0.0.1:12345")
        e.scale, e.kubectl, e.collect, e.reset_inference, e.snapshot = (
            Mock() for _ in range(5)
        )
        return e

    def test_exception_after_kill_recovers_node_and_restart_policy(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            runner, "ROOT", Path(directory)
        ):
            e = self.experiment(Path(directory))

            def fail():
                e.fault_active = True
                e.policy = {"Name": "on-failure", "MaximumRetryCount": 1}
                raise RuntimeError("observer stopped after fault")

            e.measure = fail
            inspected = json.dumps([{"State": {"Running": False, "Paused": False}}])
            with patch.object(runner, "output", return_value=inspected), patch.object(
                runner, "run"
            ) as command:
                with self.assertRaisesRegex(RuntimeError, "observer stopped"):
                    e.execute()
            command.assert_any_call(["docker", "start", "test-worker2"])
            command.assert_any_call(
                ["docker", "update", "--restart=on-failure:1", "test-worker2"]
            )
            self.assertFalse(e.fault_active)
            self.assertIsNone(e.policy)
            self.assertEqual(
                json.loads((e.raw / "run.json").read_text())["status"], "failed"
            )
            e.scale.assert_any_call("aiperf", 0)
            e.collect.assert_not_called()

    def test_interrupt_after_pause_unpauses_without_starting_running_node(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            runner, "ROOT", Path(directory)
        ):
            e = self.experiment(Path(directory), "pause")

            def interrupted():
                e.fault_active = True
                raise KeyboardInterrupt()

            e.measure = interrupted
            inspected = json.dumps([{"State": {"Running": True, "Paused": True}}])
            with patch.object(runner, "output", return_value=inspected), patch.object(
                runner, "run"
            ) as command:
                with self.assertRaises(KeyboardInterrupt):
                    e.execute()
            command.assert_called_once_with(["docker", "unpause", "test-worker2"])
            self.assertEqual(
                json.loads((e.raw / "run.json").read_text())["status"], "failed"
            )

    def test_completed_run_exports_data_without_creating_reports(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            runner, "ROOT", Path(directory)
        ):
            e = self.experiment(Path(directory))
            e.measure = Mock()
            e.execute()
            e.collect.assert_called_once()
            e.reset_inference.assert_called_once()
            e.forward.assert_called_once_with("prometheus", 9090)
            metadata = json.loads((e.raw / "run.json").read_text())
            self.assertEqual(metadata["status"], "complete")
            self.assertNotIn("report", metadata)
            self.assertFalse((Path(directory) / "docs").exists())
            self.assertFalse(list(e.raw.rglob("*.md")))

    def test_recovery_is_idempotent_if_start_already_succeeded(self):
        e = self.experiment(Path("/unused"))
        e.fault_active = True
        e.mark = Mock()
        inspected = json.dumps([{"State": {"Running": True, "Paused": False}}])
        with patch.object(runner, "output", return_value=inspected), patch.object(
            runner, "run"
        ) as command:
            e.recover()
            e.recover()
        command.assert_not_called()
        self.assertFalse(e.fault_active)


if __name__ == "__main__":
    unittest.main()
