"""Check Llama and Qwen3 decoding, batching, and prefix cache compatibility."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from enhanced_support import ROOT
from transformers_cpu.base.engine import EngineSettings, Generation, TorchEngine
from transformers_cpu.enhanced.batch import engine as batching
from transformers_cpu.enhanced.cache import engine as caching

try:
    import torch
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace
    from transformers import (PreTrainedTokenizerFast, Qwen3Config, Qwen3ForCausalLM,
                              LlamaConfig, LlamaForCausalLM)
except ImportError:
    torch = None


@unittest.skipIf(torch is None, "Install transformers_cpu/requirements.txt")
class EngineTests(unittest.TestCase):
    architecture = "qwen3"

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.model_path = Path(cls.directory.name) / "model"
        torch.manual_seed(7)
        config_type, model_type = ((LlamaConfig, LlamaForCausalLM) if cls.architecture == "llama"
                                  else (Qwen3Config, Qwen3ForCausalLM))
        model = model_type(config_type(
            vocab_size=48, hidden_size=32, intermediate_size=64, num_hidden_layers=2,
            num_attention_heads=4, num_key_value_heads=2,
            head_dim=8 if cls.architecture == "llama" else 16,
            tie_word_embeddings=True,
            max_position_embeddings=128, eos_token_id=2, pad_token_id=0,
        ))
        model.save_pretrained(cls.model_path)
        tokenizer = Tokenizer(WordLevel({f"t{i}": i for i in range(48)}, unk_token="t1"))
        tokenizer.pre_tokenizer = Whitespace()
        fast = PreTrainedTokenizerFast(tokenizer_object=tokenizer, eos_token="t2", pad_token="t0")
        fast.chat_template = ("{% for message in messages %}{{ message['content'] }} {% endfor %}"
                              "{% if enable_thinking %}t9 {% endif %}t3")
        fast.save_pretrained(cls.model_path)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def setUp(self):
        self.settings = EngineSettings(self.model_path, n_ctx=64, n_threads=1)
        self.engine = TorchEngine(self.settings)
        self.addCleanup(self.engine.close)

    def request(self, prompt=None, limit=5, **options):
        return Generation(prompt or [3, 8, 9, 10], limit, 0, 1, True,
                          threading.Event(), **options)

    def test_cpu_local_loading_and_thinking_template(self):
        self.assertEqual(self.engine.model.device.type, "cpu")
        self.assertEqual(self.engine.model.dtype, torch.float32)
        self.assertEqual(self.engine.head_dim, 8 if self.architecture == "llama" else 16)
        messages = [{"role": "user", "content": "t4 t5"}]
        self.assertEqual(self.engine.prepare_prompt(messages), [4, 5, 3])
        if self.architecture == "llama":
            with self.assertRaisesRegex(ValueError, "only supported for Qwen3"):
                TorchEngine(replace(self.settings, enable_thinking=True))
        else:
            self.engine.settings = replace(self.settings, enable_thinking=True)
            self.assertEqual(self.engine.prepare_prompt(messages), [4, 5, 9, 3])
        with self.assertRaises(ValueError):
            TorchEngine(replace(self.settings, model_path=self.model_path / "missing"))

    def test_batched_padding_and_row_compaction_match_serial(self):
        requests = [self.request([3, 7], 1), self.request([3, 8, 9, 10, 11], 6),
                    self.request([4, 5, 6], 3)]
        expected = [self.engine.generate_batch([r])[0] for r in requests]
        with patch.object(self.engine.model, "forward", wraps=self.engine.model.forward) as forward:
            actual = self.engine.generate_batch(requests)
        self.assertEqual(expected, actual)
        self.assertEqual(forward.call_args_list[0].kwargs["input_ids"].shape, (3, 5))
        self.assertEqual(forward.call_args_list[1].kwargs["input_ids"].shape, (2, 1))
        self.assertEqual([r["completion_tokens"] for r in actual], [1, 6, 3])

    def test_stream_matches_complete_and_preserves_usage(self):
        pieces = []
        expected = self.engine.generate_batch([self.request()])[0]
        actual = self.engine.generate_batch([self.request(emit=pieces.append)])[0]
        self.assertEqual(actual, expected)
        self.assertEqual("".join(pieces), actual["text"])
        self.assertEqual(actual["prompt_tokens"], 4)

    def test_eos_mask_and_top_p(self):
        request = self.request()
        scores = torch.full((48,), -100.0)
        scores[2], scores[7] = 50, 20
        self.assertEqual(self.engine._sample(scores, request), 7)
        request.ignore_eos = False
        self.assertEqual(self.engine._sample(scores, request), 2)
        request.temperature, request.top_p = 0.7, 0.1
        self.assertEqual(self.engine._sample(scores, request), 2)
        with patch.object(self.engine, "_sample", return_value=2):
            result = self.engine.generate_batch([request])[0]
        self.assertEqual(result["completion_tokens"], 0)
        self.assertEqual(result["finish_reason"], "stop")

    def test_cancellation_does_not_cancel_other_rows(self):
        cancelled, active = self.request(limit=8), self.request(limit=3)
        cancelled.emit = lambda _: cancelled.cancel.set()
        result = self.engine.generate_batch([cancelled, active])
        self.assertLess(result[0]["completion_tokens"], 8)
        self.assertEqual(result[1]["completion_tokens"], 3)
        cancelled.cancel.set()
        with patch.object(self.engine, "_prefill") as prefill:
            self.assertEqual(self.engine.generate_batch([cancelled])[0]["completion_tokens"], 0)
            prefill.assert_not_called()

    def test_limits_reject_without_model_call(self):
        with patch.object(self.engine, "_forward") as forward:
            with self.assertRaises(ValueError):
                self.engine.generate_batch([self.request(limit=64)])
            forward.assert_not_called()

    def test_prefix_cache_exact_partial_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = caching.EngineSettings(**vars(self.settings), cache_dir=Path(directory),
                                              cache_ram_mib=1, cache_disk_mib=1, cache_min_prefix=2)
            engine = caching.TorchEngine(settings)
            try:
                for prompt, restored in [([3, 8, 9, 10], 0), ([3, 8, 9, 10], 3),
                                         ([3, 8, 9, 11, 12], 3), ([3, 8], 0)]:
                    before = engine.restored_tokens
                    request = self.request(prompt)
                    expected = self.engine.generate_batch([request])[0]
                    with patch.object(engine, "_forward", wraps=engine._forward) as forward:
                        self.assertEqual(engine.generate_batch([request])[0], expected)
                    self.assertEqual(engine.restored_tokens - before, restored)
                    self.assertEqual(forward.call_args_list[0].args[0].shape[1], len(prompt) - restored)
            finally:
                engine.close()
            engine = caching.TorchEngine(settings)
            try:
                result = engine.generate_batch([self.request()])[0]
                self.assertEqual(result, self.engine.generate_batch([self.request()])[0])
                self.assertEqual(engine.cache.stats["disk_hits"], 1)
                self.assertEqual(engine.restored_tokens, 3)
            finally:
                engine.close()

    def test_disk_corruption_recomputes_and_model_identity_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = caching.EngineSettings(**vars(self.settings), cache_dir=Path(directory),
                                              cache_ram_mib=0, cache_disk_mib=1, cache_min_prefix=2)
            engine = caching.TorchEngine(settings)
            try:
                expected = engine.generate_batch([self.request()])[0]
                path = next(engine.cache.directory.glob("*.kv"))
                path.write_bytes(b"corrupt")
                self.assertEqual(engine.generate_batch([self.request()])[0], expected)
                self.assertEqual(engine.cache.stats["errors"], 1)
                namespace = engine.cache.directory
            finally:
                engine.close()
            engine = caching.TorchEngine(replace(settings, n_ctx=65))
            try:
                self.assertNotEqual(namespace, engine.cache.directory)
                self.assertEqual(len(engine.cache.disk), 0)
            finally:
                engine.close()

    def test_scheduler_coalesces_concurrent_requests(self):
        settings = batching.EngineSettings(**vars(self.settings), max_parallel=3, batch_wait_ms=100)
        engine = batching.TorchEngine(settings)
        try:
            barrier = threading.Barrier(3)

            def run(index):
                barrier.wait(timeout=3)
                return engine.complete([3, 4, index + 6], index + 1, 0, 1, True, threading.Event())

            with patch.object(engine.backend, "generate_batch", wraps=engine.backend.generate_batch) as batch:
                with ThreadPoolExecutor(3) as pool:
                    results = list(pool.map(run, range(3)))
            self.assertEqual(batch.call_count, 1)
            self.assertEqual([r["completion_tokens"] for r in results], [1, 2, 3])
        finally:
            engine.close()
        self.assertFalse(engine.worker.is_alive())
        with self.assertRaises(RuntimeError):
            engine.complete([3], 1, 0, 1, True, threading.Event())


class SmolLM2ArchitectureTests(EngineTests):
    architecture = "llama"


@unittest.skipUnless(torch is not None and os.environ.get("TEST_TRANSFORMERS_MODEL_PATH"),
                     "Set TEST_TRANSFORMERS_MODEL_PATH to local SmolLM2 or Qwen3 weights")
class ModelIntegrationTests(unittest.TestCase):
    def test_real_model_base_batch_cache_and_stream(self):
        settings = EngineSettings(Path(os.environ["TEST_TRANSFORMERS_MODEL_PATH"]),
                                  n_ctx=256, n_threads=4)
        engine = TorchEngine(settings)
        try:
            prompts = [engine.prepare_prompt([{"role": "user", "content": text}])
                       for text in ["Say hello.", "Explain why libraries are useful in one sentence.",
                                    "Count from one to five."]]
            requests = [Generation(prompt, limit, 0, 1, True, threading.Event())
                        for prompt, limit in zip(prompts, [3, 12, 6])]
            expected = [engine.generate_batch([r])[0] for r in requests]
            self.assertTrue(all(result["text"] for result in expected))
            self.assertEqual(engine.generate_batch(requests), expected)
            pieces = []
            requests[0].emit = pieces.append
            engine.generate_batch([requests[0]])
            self.assertEqual("".join(pieces), expected[0]["text"])
            requests[0].emit = None
            # Verify the custom loop against Transformers' generation implementation.
            ids = torch.tensor([prompts[0]])
            with torch.inference_mode():
                reference = engine.model.generate(
                    input_ids=ids, attention_mask=torch.ones_like(ids),
                    max_new_tokens=24, do_sample=False,
                )[0, ids.shape[1]:].tolist()
            if reference and reference[-1] in engine.eos_tokens:
                reference.pop()
            actual = engine.complete(prompts[0], 24, 0, 1, False, threading.Event())
            self.assertEqual(actual["text"], engine.tokenizer.decode(reference, skip_special_tokens=True,
                                                                     clean_up_tokenization_spaces=False))
            self.assertEqual(actual["completion_tokens"], len(reference))
        finally:
            engine.close()
        with tempfile.TemporaryDirectory() as directory:
            options = caching.EngineSettings(**vars(settings), cache_dir=Path(directory),
                                             cache_ram_mib=0, cache_disk_mib=64, cache_min_prefix=2)
            for iteration in range(2):
                engine = caching.TorchEngine(options)
                try:
                    for request, result in zip(requests, expected):
                        self.assertEqual(engine.generate_batch([request])[0], result)
                    if iteration:
                        self.assertGreater(engine.restored_tokens, 0)
                        self.assertGreater(engine.cache.stats["disk_hits"], 0)
                finally:
                    engine.close()


if __name__ == "__main__":
    unittest.main()
