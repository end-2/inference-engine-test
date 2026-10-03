"""Keep shared runtime and model experiments independently importable."""

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SourceBoundaryTests(unittest.TestCase):
    def assert_imports_without(self, modules, forbidden):
        # A fresh interpreter avoids modules already loaded by other model tests.
        result = subprocess.run(
            [sys.executable, "-c", """
import importlib
import importlib.abc
import json
import sys

modules, forbidden = json.loads(sys.argv[1])

class Boundary(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == name or fullname.startswith(name + ".") for name in forbidden):
            raise ImportError("Unexpected dependency: " + fullname)

sys.meta_path.insert(0, Boundary())
for module in modules:
    importlib.import_module(module)
""", json.dumps([modules, forbidden])],
            env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_runtime_does_not_require_model_families(self):
        self.assert_imports_without(
            [f"huggingface.runtime.{module}" for module in
             ("engine", "batching", "sampling", "prompts", "server")],
            ["huggingface.llama", "huggingface.mamba", "huggingface.jamba", "llamacpp"],
        )

    def test_model_features_do_not_require_other_families_or_baseline_entrypoints(self):
        features = {
            "llama": ("batch.server", "batch.gpu.server", "cache.server", "metrics.server",
                      "inference_distributed.server", "inference_distributed.router"),
            "mamba": ("cache.server",),
            "jamba": ("hybrid.server",),
        }
        for family, modules in features.items():
            with self.subTest(family=family):
                forbidden = [f"huggingface.{other}" for other in features if other != family]
                self.assert_imports_without(
                    [f"huggingface.{family}.{module}" for module in modules],
                    [*forbidden, f"huggingface.{family}.base", "llamacpp"],
                )

    def test_llamacpp_does_not_require_huggingface_runtime(self):
        self.assert_imports_without(
            [f"llamacpp.{variant}.server" for variant in ("base", "batch", "cache", "metrics")],
            ["huggingface", "transformers", "torch"],
        )


if __name__ == "__main__":
    unittest.main()
