"""Native batching and tiered KV integration; requires TEST_MODEL_PATH."""

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import tempfile
import threading
import unittest

from enhanced_support import load_variant


@unittest.skipUnless(os.environ.get("TEST_MODEL_PATH"), "TEST_MODEL_PATH is not set")
class NativeEnhancedTests(unittest.TestCase):
    def setUp(self):
        self.model = Path(os.environ["TEST_MODEL_PATH"])
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def engine(self, variant, **options):
        module = load_variant(variant)
        engine = module.LlamaEngine(module.EngineSettings(
            self.model, n_ctx=256, n_threads=2, n_batch=64, **options))
        self.addCleanup(engine.close)
        return engine

    @staticmethod
    def prompt(engine, content="Say hello."):
        return engine.prepare_prompt([{"role": "user", "content": content}])

    @staticmethod
    def complete(engine, prompt, count=16):
        return engine.complete(prompt, count, 0, 1, True, threading.Event())

    def test_native_batch_concurrent_requests_and_stream_tokens(self):
        engine = self.engine("enhanced-batch", max_parallel=3, prefill_chunk=8, n_ubatch=64)
        prompts = [self.prompt(engine, text) for text in ["Say hello.", "한국어로 인사해 주세요.",
                   "Count from one to ten.", "Name two colors.", "Say goodbye."]]
        barrier = threading.Barrier(len(prompts))

        def generate(prompt):
            barrier.wait(5)
            return self.complete(engine, prompt)

        with ThreadPoolExecutor(max_workers=len(prompts)) as pool:
            futures = [pool.submit(generate, prompt) for prompt in prompts]
            results = [future.result(60) for future in futures]
        for prompt, result in zip(prompts, results):
            self.assertEqual(result["prompt_tokens"], len(prompt))
            self.assertEqual(result["completion_tokens"], 16)
            self.assertEqual(result["finish_reason"], "length")
        self.assertGreater(engine.worker.stats["batched_decode_calls"], 0)
        self.assertEqual(engine.worker.stats["max_decode_sequences"], 3)
        pieces = []
        streamed = engine.stream(prompts[0], 16, 0, 1, True, threading.Event(), pieces.append)
        self.assertEqual("".join(pieces), results[0]["text"])
        self.assertEqual(streamed["completion_tokens"], 16)
        cancelled = threading.Event()
        cancelled.set()
        self.assertEqual(engine.complete(prompts[0], 16, 0, 1, True, cancelled)["completion_tokens"], 0)

    def test_native_cache_spill_promotion_and_restart_match_uncached_output(self):
        options = dict(cache_dir=Path(self.directory.name), cache_ram_mib=4,
                       cache_disk_mib=8, cache_min_prefix=1)
        engine = self.engine("enhanced-cache", **options)
        prompt = self.prompt(engine)
        expected = self.complete(engine, prompt)
        cache = engine.prefix_cache.cache
        snapshot = cache.ram[tuple(prompt)]
        cache.ram_limit = snapshot.size * 3 // 2
        other = self.prompt(engine, "Describe the ocean.")
        self.complete(engine, other)
        self.assertIn(tuple(prompt), cache.disk)
        cache.ram_limit = 4 * 1024**2
        restored = self.complete(engine, prompt)
        self.assertEqual(expected, restored)
        self.assertGreater(cache.stats["disk_hits"], 0)
        self.assertIn(tuple(prompt), cache.ram)
        self.complete(engine, other)
        pieces = []
        streamed = engine.stream(prompt, 16, 0, 1, True, threading.Event(), pieces.append)
        self.assertEqual("".join(pieces), expected["text"])
        self.assertEqual(streamed["completion_tokens"], 16)
        self.assertGreater(cache.stats["ram_hits"], 0)
        engine.close()
        restarted = self.engine("enhanced-cache", **options)
        self.assertEqual(self.complete(restarted, prompt), expected)
        self.assertEqual(restarted.prefix_cache.cache.stats["disk_hits"], 1)
        self.assertEqual(restarted.prefix_cache.cache.stats["errors"], 0)

    def test_restored_partial_prefix_matches_cold_inference(self):
        engine = self.engine("enhanced-cache", cache_dir=Path(self.directory.name),
                             cache_ram_mib=4, cache_disk_mib=8, cache_min_prefix=1)
        first = self.prompt(engine, "The quick brown fox jumps over the lazy dog. Continue.")
        second = self.prompt(engine, "The quick brown fox jumps over the fence. Continue.")
        self.complete(engine, first)
        self.complete(engine, self.prompt(engine, "Name three colors."))
        restored = self.complete(engine, second)
        self.assertGreater(engine.prefix_cache.restored_tokens, 0)
        cold = self.engine("base")
        self.assertEqual(restored, self.complete(cold, second))


if __name__ == "__main__":
    unittest.main()
