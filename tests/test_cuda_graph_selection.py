"""Verify graph selection and reporting without requiring CUDA model weights."""

from pathlib import Path
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from enhanced_support import ROOT
from inference.contracts import Generation
from huggingface.llama.batch.gpu.backend import GPUBatchBackend
from huggingface.llama.batch.gpu.server import Settings, create_parser


class GraphSelectionTests(unittest.TestCase):
    def backend(self, mode):
        backend = object.__new__(GPUBatchBackend)
        backend.cuda_graph = mode
        backend.settings = SimpleNamespace(device="cuda", n_ctx=32)
        backend.completed_batches = {"eager": 0, "cuda_graph": 0}
        backend.completed_requests = {"eager": 0, "cuda_graph": 0}
        backend._generate_graph = Mock(return_value=[{"text": "graph"}])
        backend._generate_eager = Mock(return_value=[{"text": "eager"}])
        return backend

    def request(self, **options):
        values = dict(prompt=[1, 2, 3], max_tokens=4, temperature=0, top_p=1,
                      ignore_eos=True, cancel=threading.Event())
        return Generation(**(values | options))

    def test_off_never_enters_graph_even_for_eligible_requests(self):
        backend = self.backend("off")
        backend.generate_batch([self.request(), self.request()])
        backend._generate_graph.assert_not_called()
        self.assertEqual(backend.runtime_info(), {
            "cuda_graph": "off", "completed_batches": {"eager": 1, "cuda_graph": 0},
            "completed_requests": {"eager": 2, "cuda_graph": 0}})

    def test_auto_records_both_actual_paths(self):
        backend = self.backend("auto")
        backend.generate_batch([self.request()])
        backend.generate_batch([self.request(temperature=0.7)])
        self.assertEqual(backend.runtime_info()["completed_batches"], {"eager": 1, "cuda_graph": 1})

    def test_required_rejects_ineligible_requests_without_fallback(self):
        for options in ({"temperature": 0.7}, {"ignore_eos": False}, {"max_tokens": 30}):
            backend = self.backend("required")
            with self.subTest(options=options), self.assertRaises(ValueError):
                backend.generate_batch([self.request(**options)])
            backend._generate_eager.assert_not_called()
            backend._generate_graph.assert_not_called()
            self.assertEqual(sum(backend.runtime_info()["completed_batches"].values()), 0)

    def test_required_keeps_cancelled_requests_on_cancellation_aware_graph_path(self):
        backend = self.backend("required")
        request = self.request()
        request.cancel.set()
        backend.generate_batch([request])
        backend._generate_graph.assert_called_once()
        backend._generate_eager.assert_not_called()

    def test_failed_generation_does_not_count_as_completed(self):
        backend = self.backend("required")
        backend._generate_graph.side_effect = RuntimeError("capture failed")
        with self.assertRaisesRegex(RuntimeError, "capture failed"):
            backend.generate_batch([self.request()])
        self.assertEqual(sum(backend.runtime_info()["completed_requests"].values()), 0)

    def test_cli_mode_reaches_engine_settings_and_rejects_cpu(self):
        args = vars(create_parser().parse_args(["--model", "/model", "--cuda-graph", "off"]))
        args.pop("host")
        args.pop("port")
        settings = Settings(**args).engine_settings()
        self.assertEqual(settings.cuda_graph, "off")
        self.assertEqual(settings.model_path, Path("/model"))
        self.assertEqual(Settings().engine_settings().cuda_graph, "auto")
        with self.assertRaises(ValueError):
            Settings(device="cpu")
        with self.assertRaises(ValueError):
            Settings(cuda_graph="unknown")


if __name__ == "__main__":
    unittest.main()
