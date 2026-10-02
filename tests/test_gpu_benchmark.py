"""GPU benchmark routing, manifests, and collection checks."""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

try:
    import yaml
except ImportError:
    yaml = None

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
spec = importlib.util.spec_from_file_location("benchmark_gpu_test", ROOT / "scripts/run-benchmark.py")
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)
suite_spec = importlib.util.spec_from_file_location("suite_gpu_test", ROOT / "scripts/run-benchmark-suite.py")
suite = importlib.util.module_from_spec(suite_spec)
suite_spec.loader.exec_module(suite)


class GPUSettingsTests(unittest.TestCase):
    def test_exclusive_benchmarks_reject_mps_before_cluster_changes(self):
        for module in (benchmark, suite):
            with self.subTest(module=module.__name__), patch.dict(os.environ, {"GPU_SHARING": "mps"}), \
                    patch("sys.argv", ["benchmark", "--device", "gpu"]), patch("sys.stderr"), self.assertRaises(SystemExit):
                module.parse_args()

    def test_transformers_device_defaults_and_cpu_validation(self):
        from transformer.base.engine import EngineSettings
        self.assertEqual(EngineSettings(Path("model")).dtype, "float32")
        self.assertEqual(EngineSettings(Path("model"), device="cuda").dtype, "float16")
        with self.assertRaises(ValueError):
            EngineSettings(Path("model"), device="cpu", dtype="float16")

    def test_gpu_routes_images_manifests_and_reports(self):
        with patch.dict(os.environ, {}, clear=True), patch("sys.argv", ["run-benchmark.py", "--device", "gpu"]):
            args = benchmark.parse_args()
        self.assertEqual(args.image, "local/transformers-base-gpu:0.1.0")
        self.assertEqual(args.build_target, "transformers-base-gpu")
        self.assertEqual(args.manifests, ROOT / "k8s/gpu/transformers-base")
        self.assertEqual(args.reports_dir, ROOT / "docs/reports/gpu/transformers")
        with patch.dict(os.environ, {}, clear=True), patch("sys.argv", ["run-benchmark-suite.py", "--device", "gpu"]):
            options = suite.parse_args()
        self.assertEqual(options.reports_dir, ROOT / "docs/reports/gpu/transformers")
        metadata = {"backend": "transformers", "device": "gpu", "image_tag": "test",
                    "benchmark_image": "local/aiperf:test", "inference_node": "worker", "benchmark_node": "control"}
        command = suite.case_command(suite.plan(1)[0], metadata, Path("reports"))
        arguments = dict(zip(command[2::2], command[3::2], strict=True))
        self.assertEqual(arguments["--device"], "gpu")
        self.assertEqual(arguments["--image"], "local/transformers-base-gpu:test")
        self.assertEqual(arguments["--manifests"], str(ROOT / "k8s/gpu/transformers-base"))

    def test_gpu_image_build_uses_cuda_dockerfile(self):
        with tempfile.TemporaryDirectory() as directory:
            context = Path(directory)
            (context / "Dockerfile.gpu").write_text("FROM scratch\n")
            commands = []
            def execute(*args, **kwargs):
                commands.append(args)
                if args[:3] == ("docker", "image", "inspect"):
                    return subprocess.CompletedProcess(args, 1, "", "missing") if len(commands) == 1 else subprocess.CompletedProcess(
                        args, 0, '[{"Id":"image","Config":{"Labels":{}}}]', "")
                return subprocess.CompletedProcess(args, 0, "", "")
            with patch.object(benchmark, "run", side_effect=execute), patch.object(
                benchmark, "kube_json", return_value={"items": []}
            ):
                benchmark.ensure_image("local/test-gpu:1", context, "transformers-base-gpu")
            build = next(command for command in commands if command[:2] == ("docker", "build"))
            self.assertNotIn("--no-cache", build)
            self.assertEqual(build[build.index("-f") + 1], context / "Dockerfile.gpu")
            self.assertEqual(build[build.index("--target") + 1], "transformers-base-gpu")

    def test_gpu_image_can_be_reused_from_worker_without_host_copy(self):
        def execute(*args, **kwargs):
            if args[:3] == ("docker", "image", "inspect"):
                return subprocess.CompletedProcess(args, 1, "", "missing")
            return subprocess.CompletedProcess(args, 0, '{"status":{"id":"sha256:fixed"}}', "")
        with patch.object(benchmark, "run", side_effect=execute) as run:
            info = benchmark.ensure_image("local/test-gpu:1", None, load_nodes=["worker"])
        self.assertEqual(info["id"], "sha256:fixed")
        self.assertEqual(run.call_count, 2)

    @unittest.skipIf(yaml is None, "PyYAML is needed to inspect manifests")
    def test_all_gpu_deployments_request_one_gpu(self):
        names = ("transformers-base", "transformers-enhanced-batch", "transformers-enhanced-cache",
                 "transformers-mamba-base", "transformers-mamba-cache",
                 "base-llamacpp", "enhanced-batch-llamacpp", "enhanced-cache-llamacpp")
        for name in names:
            with self.subTest(name=name):
                path = ROOT / "k8s/gpu" / name / "deployment.yaml"
                obj = yaml.safe_load(path.read_text())
                pod = obj["spec"]["template"]["spec"]
                container = pod["containers"][0]
                self.assertEqual(pod["runtimeClassName"], "nvidia")
                self.assertEqual(container["resources"]["requests"]["nvidia.com/gpu"], 1)
                self.assertEqual(container["resources"]["limits"]["nvidia.com/gpu"], 1)
                self.assertEqual(container["resources"]["requests"]["cpu"], "4")
                self.assertEqual(container["resources"]["requests"]["memory"], "4Gi")
                self.assertTrue(container["image"].startswith(f"local/{name}-gpu:"))
                arguments = dict(zip(container["args"][::2], container["args"][1::2], strict=True))
                if name.startswith("transformers"):
                    self.assertEqual(arguments["--device"], "cuda")
                    self.assertEqual(arguments["--dtype"], "float16")
                else:
                    self.assertEqual(arguments["--n-gpu-layers"], "-1")

    def test_gpu_worker_selection_and_allocatable_check(self):
        nodes = {"items": [
            {"metadata": {"name": "cp", "labels": {"node-role.kubernetes.io/control-plane": ""}},
             "status": {"conditions": [{"type": "Ready", "status": "True"}], "allocatable": {}}},
            {"metadata": {"name": "worker", "labels": {}},
             "status": {"conditions": [{"type": "Ready", "status": "True"}],
                        "allocatable": {"nvidia.com/gpu": "1"}}}]}
        self.assertEqual(benchmark.resolve_nodes(None, None, nodes, "gpu"), ("worker", "cp"))
        nodes["items"][1]["status"]["allocatable"].clear()
        with self.assertRaisesRegex(RuntimeError, "GPU worker"):
            benchmark.resolve_nodes(None, None, nodes, "gpu")

    def test_mamba_routes_model_profile_and_suite(self):
        with patch.dict(os.environ, {}, clear=True), patch("sys.argv", [
            "run-benchmark.py", "--backend", "mamba", "--device", "gpu",
        ]):
            args = benchmark.parse_args()
        self.assertEqual(args.model, "state-spaces/mamba-130m-hf")
        self.assertEqual(args.image, "local/transformers-mamba-base-gpu:0.1.0")
        self.assertEqual(args.manifests, ROOT / "k8s/gpu/transformers-mamba-base")
        self.assertEqual(args.reports_dir, ROOT / "docs/reports/gpu/mamba")
        with patch.object(benchmark, "render", return_value={}) as render:
            benchmark.benchmark_manifests("mamba")
        render.assert_called_once_with(ROOT / "k8s/aiperf-mamba")
        with patch.object(benchmark, "run") as run:
            benchmark.prepare_model("mamba")
        run.assert_called_once_with(ROOT / "scripts/download-transformers-model.sh", "mamba-130m")
        cases = suite.plan(2, "mamba")
        self.assertEqual(len(cases), 6)
        self.assertEqual({case["variant"] for case in cases}, {"base", "cache"})
        metadata = {"backend": "mamba", "device": "gpu", "image_tag": "test",
                    "benchmark_image": "local/aiperf:test", "inference_node": "worker", "benchmark_node": "control"}
        command = suite.case_command(cases[1], metadata, Path("reports"))
        args = dict(zip(command[2::2], command[3::2], strict=True))
        self.assertEqual(args["--image"], "local/transformers-mamba-cache-gpu:test")
        self.assertEqual(args["--deployment"], "transformers-mamba-base")

    @unittest.skipIf(yaml is None, "PyYAML is needed to inspect manifests")
    def test_mamba_manifests_use_own_weights_tokenizer_and_cache(self):
        for device in ("", "gpu"):
            for variant in ("base", "cache"):
                root = ROOT / "k8s" / device / f"transformers-mamba-{variant}"
                deployment = yaml.safe_load((root / "deployment.yaml").read_text())
                service = yaml.safe_load((root / "service.yaml").read_text())
                pod = deployment["spec"]["template"]["spec"]
                args = pod["containers"][0]["args"]
                self.assertEqual(args[args.index("--served-model-name") + 1], "state-spaces/mamba-130m-hf")
                self.assertEqual(service["spec"]["selector"], deployment["spec"]["selector"]["matchLabels"])
                model = next(v for v in pod["volumes"] if v["name"] == "model")
                self.assertEqual(model["hostPath"]["path"], "/models/mamba-130m")
                if variant == "cache":
                    cache = next(v for v in pod["volumes"] if v["name"] == "cache")
                    self.assertEqual(cache["persistentVolumeClaim"]["claimName"], "transformers-mamba-cache")
        profile = yaml.safe_load((ROOT / "k8s/aiperf-mamba/job.yaml").read_text())
        spec = profile["spec"]["template"]["spec"]
        self.assertEqual(next(v for v in spec["volumes"] if v["name"] == "tokenizer")["hostPath"]["path"],
                         "/models/mamba-130m")

    def test_gpu_suite_loads_each_image_only_on_its_node(self):
        metadata = {"backend": "transformers", "device": "gpu", "image_tag": "test",
                    "benchmark_image": "local/aiperf:test", "inference_node": "worker",
                    "benchmark_node": "control", "images": {}}
        with patch.object(suite.benchmark, "ensure_image", return_value={"id": "image"}) as ensure:
            suite.prepare_images(metadata, build=False)
        self.assertEqual(len(ensure.call_args_list), 4)
        self.assertTrue(all(call.kwargs["load_nodes"] == ["worker"] for call in ensure.call_args_list[:3]))
        self.assertEqual(ensure.call_args_list[-1].kwargs["load_nodes"], ["control"])

    def test_gpu_samples_record_uuid_and_mean_max(self):
        with tempfile.TemporaryDirectory() as directory:
            outputs = iter(("GPU-id, 20, 100, 8192\n", "GPU-id, 40, 200, 8192\n"))
            def execute(*args, **kwargs):
                return subprocess.CompletedProcess(args, 0, next(outputs), "")
            with patch.object(benchmark, "run", side_effect=execute):
                sampler = benchmark.GPUSampler(Path(directory))
                sampler.sample()
                sampler.sample()
            summary = sampler.summary()
            self.assertEqual(summary["gpu_uuid"], "GPU-id")
            self.assertEqual(summary["gpu_samples"], 2)
            self.assertEqual(summary["gpu_utilization_avg_pct"], 30)
            self.assertEqual(summary["gpu_memory_used_max_mib"], 200)
            self.assertEqual(len((Path(directory) / "gpu.csv").read_text().splitlines()), 3)


if __name__ == "__main__":
    unittest.main()
