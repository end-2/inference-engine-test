"""Native engine integration tests; set TEST_MODEL_PATH to a GGUF file."""

import os
from pathlib import Path
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from base.engine import EngineSettings, LlamaEngine


@unittest.skipUnless(os.environ.get("TEST_MODEL_PATH"), "TEST_MODEL_PATH is not set")
class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = LlamaEngine(EngineSettings(
            model_path=Path(os.environ["TEST_MODEL_PATH"]), n_ctx=128, n_threads=2))

    @classmethod
    def tearDownClass(cls):
        cls.engine.close()

    def test_stream_counts_match_native_nonstream_usage(self):
        for content, ignore_eos in [("한국어로 인사해 주세요.", True),
                                    ("Say hello.", False)]:
            with self.subTest(content=content):
                prompt = self.engine.prepare_prompt([{"role": "user", "content": content}])
                self.assertGreater(len(prompt), len(self.engine.llama.tokenize(
                    content.encode(), add_bos=False)))
                args = (prompt, 16, 0.0, 1.0, ignore_eos, threading.Event())
                complete = self.engine.complete(*args)
                pieces = []
                streamed = self.engine.stream(*args, pieces.append)
                self.assertEqual("".join(pieces), complete["text"])
                for field in ("prompt_tokens", "completion_tokens", "finish_reason"):
                    self.assertEqual(streamed[field], complete[field], field)
                if ignore_eos:
                    self.assertEqual(streamed["completion_tokens"], 16)
                    self.assertEqual(streamed["finish_reason"], "length")

    def test_pre_cancelled_generation_stops(self):
        prompt = self.engine.prepare_prompt([{"role": "user", "content": "Hello"}])
        cancel = threading.Event()
        cancel.set()
        result = self.engine.complete(prompt, 16, 0.0, 1.0, True, cancel)
        self.assertEqual(result["completion_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
