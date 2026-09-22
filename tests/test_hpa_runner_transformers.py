"""Check scaling evidence, low-load traffic, and cleanup without a cluster."""

import copy
from contextlib import redirect_stderr
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("hpa_runner", ROOT / "scripts/hpa_test_transformers/runner.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def objects():
    return [
        {"kind": "HorizontalPodAutoscaler", "status": {
            "desiredReplicas": 2, "currentReplicas": 2,
            "conditions": [{"type": "ScalingActive", "status": "True"}],
            "currentMetrics": [{"type": "Resource", "resource": {
                "name": "cpu", "current": {"averageUtilization": 80},
            }}],
        }},
        {"kind": "Deployment", "metadata": {"name": runner.ENGINE},
         "spec": {"replicas": 2}, "status": {"availableReplicas": 2}},
        *[{"kind": "Pod", "metadata": {"uid": uid, "labels": {"app": runner.ENGINE}},
           "status": {"conditions": [{"type": "Ready", "status": "True"}]}}
          for uid in ("original", "new")],
        {"kind": "EndpointSlice", "metadata": {"labels": {
            "kubernetes.io/service-name": runner.ENGINE,
        }}, "endpoints": [
            {"conditions": {"ready": True}, "targetRef": {"uid": uid}}
            for uid in ("original", "new")
        ]},
    ]


class ScaleOutTests(unittest.TestCase):
    def test_ready_pods_and_routable_endpoints_prove_scale_out(self):
        sample = runner.summarize(objects())
        self.assertTrue(runner.scaled_out(sample, ["original"], 2))
        self.assertEqual(sample["cpu_percent"], 80)

    def test_desired_replicas_alone_are_not_success(self):
        sample = runner.summarize(objects())
        for key in ("available", "current", "deployment_replicas", "ready_endpoints"):
            with self.subTest(key=key):
                changed = dict(sample, **{key: 1})
                self.assertFalse(runner.scaled_out(changed, ["original"], 2))

    def test_unhealthy_hpa_or_missing_cpu_is_not_success(self):
        for status in ({"currentMetrics": []}, {"conditions": []}):
            data = objects()
            data[0]["status"].update(status)
            self.assertFalse(runner.scaled_out(runner.summarize(data), ["original"], 2))

    def test_new_pod_is_required(self):
        self.assertFalse(runner.scaled_out(runner.summarize(objects()), ["original", "new"], 2))

    def test_endpoints_deduplicate_and_ignore_unready_terminating_or_other_service(self):
        data = objects()
        data.append(copy.deepcopy(data[-1]))
        self.assertEqual(runner.summarize(data)["ready_endpoints"], 2)
        for condition in ({"ready": False}, {"ready": True, "terminating": True}):
            data = objects()
            data[-1]["endpoints"][1]["conditions"] = condition
            unrelated = copy.deepcopy(data[-1])
            unrelated["metadata"]["labels"]["kubernetes.io/service-name"] = "prometheus"
            unrelated["endpoints"][1]["conditions"] = {"ready": True}
            data.append(unrelated)
            self.assertEqual(runner.summarize(data)["ready_endpoints"], 1)

    def test_deleted_or_unready_pods_are_excluded_even_with_stale_endpoints(self):
        for update in ("deleting", "unready"):
            data = objects()
            if update == "deleting":
                data[3]["metadata"]["deletionTimestamp"] = "2026-09-20T00:00:00Z"
            else:
                data[3]["status"]["conditions"][0]["status"] = "False"
            self.assertEqual(runner.summarize(data)["ready_endpoints"], 1)


class DashboardCollectionTests(unittest.TestCase):
    def test_collection_uses_deployed_dashboard_queries(self):
        with tempfile.TemporaryDirectory() as directory:
            e = runner.Experiment(runner.parse_args("scale-out", ["--cluster", "test"]))
            e.raw = Path(directory)
            e.state = {"load_phases": {}, "started": "2026-09-20T00:00:00Z"}
            dashboard = {"panels": [{"id": 7, "targets": [{"refId": "A", "expr": "up"}]}]}
            e.get = Mock(return_value={"data": {"availability.json": json.dumps(dashboard)}})
            e.prometheus = Mock(return_value={"status": "success"})
            (e.raw / "observations.jsonl").write_text('{"at": "sample", "ready_uids": []}\n')
            with patch.object(runner, "now", return_value="2026-09-20T00:01:00Z"):
                e.collect()
            e.get.assert_called_once_with(*e.ns, "get", "configmap/grafana-dashboard", "-o", "json")
            e.prometheus.assert_called_once_with(
                "query_range", query="up", start=e.state["started"],
                end="2026-09-20T00:01:00Z", step="5s",
            )
            self.assertEqual(json.loads((e.raw / "prometheus/panel-7-A.json").read_text()),
                             {"status": "success"})


class CleanupTests(unittest.TestCase):
    def experiment(self):
        e = runner.Experiment(runner.parse_args("scale-out-in", ["--cluster", "test"]))
        e.minimum, e.target, e.cpu_target = 1, 4, 50
        e.original_load_args = ["profile", "--concurrency", "8"]
        e.command = Mock(return_value="logs")
        e.sample, e.collect, e.verify_requests = Mock(), Mock(), Mock()
        return e

    def test_failure_and_interrupt_stop_load_and_preserve_failure(self):
        for error in (RuntimeError("scale-out timed out"), KeyboardInterrupt("Signal 2")):
            with self.subTest(error=error), tempfile.TemporaryDirectory() as directory, patch.object(runner, "ROOT", Path(directory)):
                e = self.experiment()

                def fail():
                    e.load_started, e.load_pod = True, "aiperf-test"
                    e.load_phase = "low"
                    e.load_config_changed = True
                    raise error

                e.measure = fail
                with self.assertRaises(type(error)):
                    e.execute()
                e.command.assert_any_call("-n", "hpa-test-transformers", "scale", "deployment/aiperf", "--replicas=0")
                e.command.assert_any_call("-n", "hpa-test-transformers", "wait", "--for=delete", "pod", "-l", "app=aiperf", "--timeout=150s", timeout=170)
                e.collect.assert_called_once()
                e.verify_requests.assert_not_called()
                patches = [call.args for call in e.command.call_args_list if "patch" in call.args]
                self.assertEqual(json.loads(patches[-1][-1])["spec"]["template"]["spec"]["containers"][0]["args"], e.original_load_args)
                self.assertEqual(json.loads((e.raw / "run.json").read_text())["status"], "failed")

    def test_logging_failure_still_stops_load(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(runner, "ROOT", Path(directory)):
            e = self.experiment()
            e.measure = Mock()
            e.load_started, e.load_pod = True, "aiperf-test"
            e.load_phase = "high"
            e.command.side_effect = [RuntimeError("log unavailable"), "", ""]
            e.execute()
            e.command.assert_any_call("-n", "hpa-test-transformers", "scale", "deployment/aiperf", "--replicas=0")
            self.assertIn("log_errors", json.loads((e.raw / "run.json").read_text()))

    def test_collection_failure_is_not_reported_as_complete(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(runner, "ROOT", Path(directory)):
            e = self.experiment()
            e.measure = Mock()
            e.collect.side_effect = RuntimeError("export failed")
            with self.assertRaisesRegex(RuntimeError, "export failed"):
                e.execute()
            self.assertEqual(json.loads((e.raw / "run.json").read_text())["status"], "failed")

    def test_both_scenarios_stop_load_restore_arguments_and_record_results(self):
        for scenario, phases in (("scale-out", ["high"]), ("scale-out-in", ["high", "low"])):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory, patch.object(runner, "ROOT", Path(directory)):
                e = self.experiment()
                e.args = runner.parse_args(scenario, ["--cluster", "test"])
                e.wait_for = Mock(return_value={"ready_uids": ["original"], "stable_since": "2026-09-20T08:00:00+00:00"})
                e.get = Mock(side_effect=[{"items": [{"metadata": {"name": "aiperf-" + phase}}]} for phase in phases])

                def collect():
                    for details in e.state["load_phases"].values():
                        details["requests"] = {"success": 1, "success_after_scale_in": 1}

                e.collect = collect
                e.verify_requests = runner.Experiment.verify_requests.__get__(e)
                e.execute()
                state = json.loads((e.raw / "run.json").read_text())
                self.assertEqual(state["status"], "complete")
                self.assertEqual(state["scenario"], scenario)
                self.assertEqual(list(state["load_phases"]), phases)
                self.assertFalse(e.load_started)
                self.assertIn("load_configuration_restored", state)
                self.assertEqual(e.command.call_args_list[-1].args[-1], json.dumps({
                    "spec": {"template": {"spec": {"containers": [{"name": "aiperf", "args": e.original_load_args}]}}},
                }))
                for phase in phases:
                    self.assertIn(phase + "_load_stopped", state)


class ScenarioTests(unittest.TestCase):
    def test_cli_scenario_selection(self):
        self.assertEqual(runner.parse_args(argv=[]).scenario, "scale-out-in")
        args = runner.parse_args(argv=["--scenario", "scale-out"])
        self.assertEqual(args.scenario, "scale-out")
        self.assertIsNone(args.low_request_rate)
        args = runner.parse_args(argv=["--scenario", "scale-out-in", "--low-request-rate", "0.1"])
        self.assertEqual(args.low_request_rate, 0.1)
        for argv in (["--scenario", "unknown"],
                     ["--scenario", "scale-out", "--low-request-rate", "0.1"]):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                runner.parse_args(argv=argv)

    def test_single_node_or_wrong_worker_count_is_rejected_before_loading_resources(self):
        for labels in ((None,), ("monitor", "engine"), ("monitor", "engine", "engine", "engine")):
            with self.subTest(labels=labels):
                e = runner.Experiment(runner.parse_args("scale-out-in", []))
                e.get = Mock(return_value={"items": [
                    {"metadata": {"labels": {"workload": label} if label else {}},
                     "status": {"conditions": [{"type": "Ready", "status": "True"}]}}
                    for label in labels
                ]})
                with self.assertRaisesRegex(RuntimeError, "two engine workers"):
                    e.preflight()
                e.get.assert_called_once_with("get", "nodes", "-o", "json")

    def test_report_defaults_and_scenario_specific_options(self):
        for scenario in ("scale-out", "scale-out-in"):
            args = runner.parse_args(scenario, [])
            self.assertEqual(args.scenario, scenario)
            self.assertEqual(args.hold_seconds, 60)
            self.assertEqual(args.timeout, 600)
            self.assertIsNone(args.target_replicas)
            self.assertEqual(args.low_request_rate, 0.02 if scenario == "scale-out-in" else None)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            runner.parse_args("scale-out", ["--low-request-rate", "0.02"])

    def test_scale_out_requires_successful_high_load_without_low_load(self):
        e = runner.Experiment(runner.parse_args("scale-out", []))
        e.state = {"load_phases": {"high": {"requests": {"success": 1}}}}
        e.verify_requests()
        e.state["load_phases"]["high"]["requests"]["success"] = 0
        with self.assertRaisesRegex(RuntimeError, "high load"):
            e.verify_requests()

    def test_measurement_scope_matches_the_selected_scenario(self):
        for scenario in ("scale-out", "scale-out-in"):
            with self.subTest(scenario=scenario):
                e = runner.Experiment(runner.parse_args(scenario, []))
                e.minimum, e.target, e.cpu_target = 1, 4, 50
                e.original_load_args = ["profile", "--concurrency", "8"]
                e.wait_for = Mock(return_value={"ready_uids": ["original"], "stable_since": "2026-09-20T08:00:00+00:00"})
                e.mark, e.start_load, e.stop_load = Mock(), Mock(), Mock()
                e.measure()
                phases = ["baseline", "scale-out", "high-hold"]
                if scenario == "scale-out-in":
                    phases += ["scale-in", "low-hold"]
                    e.start_load.assert_any_call("low", runner.low_load_arguments(e.original_load_args, 0.02))
                    e.stop_load.assert_called_once()
                    e.mark.assert_any_call("scale_in_observed")
                    self.assertIn("low_hold_started", e.state)
                else:
                    e.start_load.assert_called_once_with("high", e.original_load_args)
                    e.stop_load.assert_not_called()
                    self.assertNotIn("low_hold_started", e.state)
                    self.assertNotIn("load_reduction_requested", [c.args[0] for c in e.mark.call_args_list])
                self.assertEqual([c.args[0] for c in e.wait_for.call_args_list], phases)
                e.mark.assert_called_with("measurement_complete")


class ScaleInTests(unittest.TestCase):
    def minimum(self):
        return dict(cpu_percent=20, scaling_active=True, current=1, desired=1,
                    deployment_replicas=1, available=1, ready_endpoints=1,
                    pod_count=1, terminating_pods=0)

    def test_minimum_requires_completed_deletion_and_cpu_below_target(self):
        self.assertTrue(runner.at_minimum(self.minimum(), 1, 50))
        for key, value in (("cpu_percent", None), ("cpu_percent", 50),
                           ("scaling_active", False), ("desired", 2),
                           ("current", 2), ("deployment_replicas", 2),
                           ("available", 0), ("ready_endpoints", 2),
                           ("pod_count", 2), ("terminating_pods", 1)):
            with self.subTest(key=key, value=value):
                self.assertFalse(runner.at_minimum(dict(self.minimum(), **{key: value}), 1, 50))

    def test_reduced_load_replaces_timing_options_and_keeps_payload(self):
        original = ["profile", "--model", "test", "--concurrency", "8", "--request-rate", "2",
                    "--arrival-pattern", "poisson", "--streaming", "--request-timeout-seconds", "30"]
        reduced = runner.low_load_arguments(original, 0.05)
        self.assertEqual(reduced, ["profile", "--model", "test", "--streaming", "--request-timeout-seconds", "30",
                                   "--concurrency", "1", "--request-rate", "0.05", "--request-rate-mode", "constant"])
        self.assertEqual(original[original.index("--concurrency") + 1], "8")

    def test_hold_allows_cpu_fluctuation_but_not_hpa_reexpansion(self):
        fluctuating = dict(self.minimum(), cpu_percent=54)
        self.assertFalse(runner.at_minimum(fluctuating, 1, 50))
        self.assertTrue(runner.at_minimum(fluctuating, 1))
        self.assertFalse(runner.at_minimum(dict(fluctuating, desired=2), 1))

    def test_records_require_a_success_wholly_inside_scale_in_hold(self):
        at = "2026-09-20T08:00:00+00:00"
        end = "2026-09-20T08:01:00+00:00"
        start_ns = int(datetime.fromisoformat(at).timestamp() * 1e9)
        def record(start, end, error=None):
            return {"metadata": {"request_start_ns": start_ns + start * 10**9,
                                 "request_end_ns": start_ns + end * 10**9}, "error": error}
        rows = [record(-10, 2), record(5, 10), record(59, 65), record(20, 25, {"type": "TimeoutError"})]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "profile_export.jsonl").write_text("\n".join(json.dumps(row) for row in rows))
            self.assertEqual(runner.request_counts(path, at, end),
                             {"success": 3, "error": 1, "success_after_scale_in": 1})

    def test_low_load_without_post_scale_in_success_fails(self):
        e = runner.Experiment(runner.parse_args("scale-out-in", []))
        e.state = {"load_phases": {
            "high": {"requests": {"success": 10}},
            "low": {"requests": {"success": 5, "success_after_scale_in": 0}},
        }}
        with self.assertRaisesRegex(RuntimeError, "scale-in hold"):
            e.verify_requests()
        e.state["load_phases"]["low"]["requests"]["success_after_scale_in"] = 2
        e.verify_requests()

    def test_hold_resets_after_an_unstable_sample(self):
        e = runner.Experiment(SimpleNamespace())
        clock = [0]
        e.sample = Mock(side_effect=[
            {"at": "t0", "valid": True}, {"at": "t5", "valid": False},
            {"at": "t10", "valid": True}, {"at": "t15", "valid": True},
            {"at": "t20", "valid": True},
        ])
        with patch.object(runner.time, "monotonic", side_effect=lambda: clock[0]), patch.object(
            runner.time, "sleep", side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)
        ):
            result = e.wait_for("low-hold", lambda s: s["valid"], 30, stable_seconds=10)
        self.assertEqual(result["stable_since"], "t10")
        self.assertEqual(result["at"], "t20")


if __name__ == "__main__":
    unittest.main()
