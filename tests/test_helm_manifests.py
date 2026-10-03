"""Check rendered Kubernetes contracts and the render-before-apply boundary."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from manifest_support import ROOT, render


class ManifestTests(unittest.TestCase):
    def test_all_profiles_have_consistent_selectors_mounts_and_references(self):
        profiles = sorted((ROOT / "k8s").glob("*/profiles/*.yaml")) + [ROOT / "k8s/metrics-server"]
        self.assertEqual(len(profiles), 35)
        for profile in profiles:
            with self.subTest(profile=profile.relative_to(ROOT)):
                resources = render(profile)
                identities = [(d["kind"], d["metadata"].get("namespace", "default"),
                               d["metadata"]["name"]) for d in resources]
                self.assertEqual(len(identities), len(set(identities)))
                pods = [d["spec"]["template"] for d in resources
                        if d["kind"] in {"Deployment", "StatefulSet", "Job"}]
                claims = {d["metadata"]["name"] for d in resources if d["kind"] == "PersistentVolumeClaim"}
                configmaps = {d["metadata"]["name"] for d in resources if d["kind"] == "ConfigMap"}
                for obj in resources:
                    if obj["kind"] == "Service":
                        selector = obj["spec"].get("selector", {})
                        self.assertTrue(any(selector.items() <= pod["metadata"]["labels"].items() for pod in pods))
                    if obj["kind"] in {"Deployment", "StatefulSet"}:
                        self.assertLessEqual(obj["spec"]["selector"]["matchLabels"].items(),
                                             obj["spec"]["template"]["metadata"]["labels"].items())
                pods += [d for d in resources if d["kind"] == "Pod"]
                for pod in pods:
                    spec = pod["spec"]
                    volumes = {v["name"]: v for v in spec.get("volumes", [])}
                    for volume in volumes.values():
                        if "persistentVolumeClaim" in volume:
                            self.assertIn(volume["persistentVolumeClaim"]["claimName"], claims)
                        if "configMap" in volume:
                            self.assertIn(volume["configMap"]["name"], configmaps)
                    for container in spec["containers"]:
                        for arg in container.get("args", []):
                            self.assertIsInstance(arg, str)
                        for mount in container.get("volumeMounts", []):
                            self.assertIn(mount["name"], volumes)
                        for env in container.get("envFrom", []):
                            if "configMapRef" in env:
                                self.assertIn(env["configMapRef"]["name"], configmaps)

    def test_image_and_resource_overrides_preserve_model_and_cache(self):
        resources = render(ROOT / "k8s/inference/profiles/transformers-enhanced-cache-gpu.yaml",
                           "--set-string", "container.image=example/inference:test",
                           "--set-string", "container.resources.requests.cpu=3,container.resources.limits.cpu=3")
        deployment = next(d for d in resources if d["kind"] == "Deployment")
        spec = deployment["spec"]["template"]["spec"]
        container = spec["containers"][0]
        self.assertEqual(container["image"], "example/inference:test")
        self.assertEqual(container["resources"]["requests"], container["resources"]["limits"])
        self.assertEqual(container["resources"]["limits"]["cpu"], "3")
        self.assertEqual(container["resources"]["limits"]["nvidia.com/gpu"], 1)
        self.assertTrue(next(m for m in container["volumeMounts"] if m["name"] == "model")["readOnly"])
        self.assertIn("--cache-dir", container["args"])

    def test_pd_setting_changes_update_all_configmap_references(self):
        profile = ROOT / "k8s/inference-distributed/profiles/mps-4-scheduled-disaggregated.yaml"
        old = render(profile)
        new = render(profile, "--set-string", "settings.TOKEN_BUDGET=32")
        old_config = next(d for d in old if d["kind"] == "ConfigMap")
        new_config = next(d for d in new if d["kind"] == "ConfigMap")
        self.assertNotEqual(old_config["metadata"]["name"], new_config["metadata"]["name"])
        self.assertEqual(new_config["data"]["TOKEN_BUDGET"], "32")
        for obj in new:
            if obj["kind"] in {"Deployment", "StatefulSet"}:
                container = obj["spec"]["template"]["spec"]["containers"][0]
                self.assertEqual(container["envFrom"][0]["configMapRef"]["name"], new_config["metadata"]["name"])

    def test_invalid_pd_profiles_fail(self):
        for option in ("slots=3", "mode=unknown", "scheduler=unknown", "scheduler=token-budget,slots=2"):
            with self.subTest(option=option):
                result = subprocess.run([str(ROOT / "scripts/render-k8s.sh"),
                                         str(ROOT / "k8s/inference-distributed/profiles/mps-2-aggregated.yaml"), "--set", option],
                                        capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)

    def test_experiment_dashboards_and_rules_remain_parseable(self):
        import yaml

        for scenario in ("availability", "hpa"):
            for backend in ("llamacpp", "transformers"):
                resources = render(ROOT / f"k8s/experiment/profiles/{scenario}-{backend}.yaml")
                maps = {d["metadata"]["name"]: d["data"] for d in resources if d["kind"] == "ConfigMap"}
                dashboard = json.loads(maps["grafana-dashboard"]["availability.json"])
                self.assertEqual(dashboard["uid"], f"{scenario}-test-{backend}")
                self.assertTrue(any("{{" in target.get("legendFormat", "")
                                    for panel in dashboard["panels"] for target in panel.get("targets", [])))
                rules = yaml.safe_load(maps["prometheus-config"]["rules.yml"])
                self.assertTrue(rules["groups"])
                self.assertEqual(sum(d["kind"] == "HorizontalPodAutoscaler" for d in resources),
                                 int(scenario == "hpa"))


class ApplyTests(unittest.TestCase):
    def test_render_failure_never_calls_cluster_and_apply_errors_propagate(self):
        with tempfile.TemporaryDirectory(prefix="helm profile test ") as directory:
            directory = Path(directory)
            trace = directory / "trace"
            cluster = directory / "cluster wrapper.sh"
            cluster.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$HELM_TEST_TRACE"\nexit 19\n')
            cluster.chmod(0o755)
            env = {**os.environ, "LOCAL_K8S_SCRIPT": str(cluster), "HELM_TEST_TRACE": str(trace)}
            command = [str(ROOT / "scripts/k8s.sh"), "apply", str(ROOT / "k8s/inference-distributed/profiles/mps-2-aggregated.yaml")]
            result = subprocess.run([*command, "--set", "slots=3"], env=env, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(trace.exists())
            for action in ("apply", "delete"):
                command[1] = action
                result = subprocess.run(command, env=env, capture_output=True)
                self.assertEqual(result.returncode, 19)
                args = trace.read_text().splitlines()
                self.assertEqual(args[:3], ["kubectl", action, "-f"])
                self.assertFalse(Path(args[3]).exists())


if __name__ == "__main__":
    unittest.main()
