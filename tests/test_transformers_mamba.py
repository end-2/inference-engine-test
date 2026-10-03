"""Mamba checkpoint correctness, persistence, isolation and CUDA parity."""

from dataclasses import replace
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from enhanced_support import ROOT
from inference.contracts import Generation
from huggingface.mamba.base.engine import EngineSettings, TorchEngine
from huggingface.mamba.cache import engine as caching
from inference.cache import Snapshot

try:
    import torch
    from safetensors.torch import load, save
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace
    from transformers import MambaConfig, MambaForCausalLM, PreTrainedTokenizerFast
except ImportError:
    torch = None


@unittest.skipIf(torch is None, "Install huggingface/requirements.txt")
class MambaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.model_path = Path(cls.directory.name) / "model"
        torch.manual_seed(7)
        MambaForCausalLM(MambaConfig(
            vocab_size=64, hidden_size=32, state_size=8, num_hidden_layers=2,
            expand=2, conv_kernel=4, bos_token_id=1, eos_token_id=2, pad_token_id=0,
        )).save_pretrained(cls.model_path)
        tokenizer = Tokenizer(WordLevel({f"t{i}": i for i in range(64)}, unk_token="t1"))
        tokenizer.pre_tokenizer = Whitespace()
        PreTrainedTokenizerFast(tokenizer_object=tokenizer, eos_token="t2", pad_token="t0").save_pretrained(cls.model_path)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def setUp(self):
        self.settings = EngineSettings(self.model_path, n_ctx=64, n_threads=1)
        self.base = TorchEngine(self.settings)
        self.addCleanup(self.base.close)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def cached(self, **kwargs):
        settings = caching.EngineSettings(**vars(self.settings), cache_dir=Path(self.temp.name),
                                          cache_min_prefix=2, cache_ram_mib=1, cache_disk_mib=1)
        engine = caching.TorchEngine(replace(settings, **kwargs))
        self.addCleanup(engine.close)
        return engine

    def request(self, prompt=None, limit=5):
        return Generation(prompt if prompt is not None else [3, 8, 9, 10], limit, 0, 1,
                          True, threading.Event())

    def test_raw_prompt_and_role_fallback(self):
        self.assertEqual(self.base.prepare_prompt([{"role": "user", "content": "t4 t5"}]), [4, 5])
        messages = [{"role": "system", "content": "t6"}, {"role": "user", "content": "t7"}]
        expected = self.base.tokenizer.encode("System: t6\nUser: t7\nAssistant:", add_special_tokens=False)
        self.assertEqual(self.base.prepare_prompt(messages), expected)
        self.base.tokenizer.chat_template = "t3 {{ messages[0]['content'] }} t8"
        self.assertEqual(self.base.prepare_prompt([{"role": "user", "content": "t4"}]), [3, 4, 8])

    def test_exact_extended_divergent_and_shorter_prompts(self):
        engine = self.cached()
        cases = [([3, 8, 9, 10], 0), ([3, 8, 9, 10], 3),
                 ([3, 8, 9, 11, 12, 13], 3), ([3, 8, 7, 12], 0),
                 ([3, 8, 9], 0), ([3, 8, 35, 14], 2)]
        for prompt, restored in cases:
            with self.subTest(prompt=prompt):
                before = engine.restored_tokens
                request = self.request(prompt)
                expected = self.base.generate(request)
                with patch.object(engine.model, "forward", wraps=engine.model.forward) as forward:
                    self.assertEqual(engine.generate(request), expected)
                self.assertEqual(engine.restored_tokens - before, restored)
                if restored:
                    self.assertTrue(all(call.kwargs["input_ids"].shape[1] == 1 for call in forward.call_args_list))

    def test_snapshots_are_prefix_only_and_reusable_after_other_requests(self):
        engine = self.cached()
        request = self.request()
        expected = engine.generate(request)
        key = tuple(request.prompt[:-1])
        snapshot = engine.cache.ram[key]
        self.assertEqual(set(engine.cache.ram), {key})
        direct = engine.model(torch.tensor([key]), use_cache=True).cache_params
        for index in range(engine.model.config.num_hidden_layers):
            torch.testing.assert_close(load(snapshot.state)[f"{index}.ssm"], direct.ssm_states[index])
        engine.generate(self.request([3, 8, 9, 22, 23]))
        self.assertEqual(engine.cache.ram[key].state, snapshot.state)
        self.assertEqual(engine.generate(request), expected)

    def test_disk_restart_and_corruption_fallback(self):
        engine = self.cached()
        expected = engine.generate(self.request())
        engine.close()
        restarted = self.cached(cache_ram_mib=0)
        self.assertEqual(restarted.generate(self.request()), expected)
        self.assertEqual(restarted.cache.stats["disk_hits"], 1)
        path = next(restarted.cache.directory.glob("*.kv"))
        path.write_bytes(b"corrupt")
        self.assertEqual(restarted.generate(self.request()), expected)
        self.assertEqual(restarted.cache.stats["errors"], 1)

    def test_invalid_state_shape_dtype_and_keys_recompute(self):
        engine = self.cached()
        request = self.request()
        expected = engine.generate(request)
        key = tuple(request.prompt[:-1])
        original = engine.cache.ram[key]
        for corruption in ("shape", "dtype", "keys"):
            tensors = load(original.state)
            if corruption == "shape":
                tensors["0.ssm"] = tensors["0.ssm"][:, :, :1].contiguous()
            elif corruption == "dtype":
                tensors["0.ssm"] = tensors["0.ssm"].half()
            else:
                del tensors["0.ssm"]
            engine.cache.put(Snapshot(key, save(tensors)))
            with self.assertLogs(level="ERROR"):
                self.assertEqual(engine.generate(request), expected)
        self.assertEqual(engine.cache.stats["errors"], 3)

    def test_disabled_cache_short_prompts_and_limits(self):
        engine = self.cached(cache_ram_mib=0, cache_disk_mib=0)
        for prompt in ([3], [3, 8], [3, 8, 9, 10]):
            request = self.request(prompt)
            self.assertEqual(engine.generate(request), self.base.generate(request))
        self.assertEqual(engine.restored_tokens, 0)
        self.assertFalse(engine.cache.ram or engine.cache.disk)
        for request in (self.request([]), self.request(limit=64)):
            with self.assertRaises(ValueError):
                engine.generate(request)

    def test_sampling_streaming_and_eos_match_base(self):
        engine = self.cached()
        for ignore_eos in (True, False):
            request = self.request(limit=8)
            request.ignore_eos = ignore_eos
            request.temperature, request.top_p = 0.7, 0.8
            torch.manual_seed(19)
            expected = self.base.generate(request)
            for _ in range(2):
                pieces = []
                request.emit = pieces.append
                torch.manual_seed(19)
                self.assertEqual(engine.generate(request), expected)
                self.assertEqual("".join(pieces), expected["text"])

    def test_cancellation_keeps_checkpoint_clean(self):
        engine = self.cached()
        request = self.request(limit=16)
        request.emit = lambda _: request.cancel.set()
        result = engine.generate(request)
        self.assertEqual(result["finish_reason"], "stop")
        self.assertLess(result["completion_tokens"], 16)
        self.assertEqual(engine.generate(self.request()), self.base.generate(self.request()))
        with patch.object(engine.model, "forward") as forward:
            self.assertEqual(engine.generate(request)["completion_tokens"], 0)
            forward.assert_not_called()

    def test_cancel_during_suffix_does_not_capture_partial_state(self):
        engine = self.cached()
        engine.generate(self.request())
        request = self.request([3, 8, 9, 11, 12, 13])
        forward = engine.model.forward

        def cancel(*args, **kwargs):
            result = forward(*args, **kwargs)
            request.cancel.set()
            return result

        with patch.object(engine.model, "forward", side_effect=cancel):
            self.assertEqual(engine.generate(request)["completion_tokens"], 0)
        self.assertNotIn(tuple(request.prompt[:-1]), engine.cache.ram)

    def test_namespace_changes_with_context_and_model_files(self):
        engine = self.cached()
        directory = engine.cache.directory
        engine.close()
        changed = self.cached(n_ctx=63)
        self.assertNotEqual(directory, changed.cache.directory)
        changed.close()
        # Alter a copied model identity without changing the shared fixture.
        import shutil
        model_path = Path(self.temp.name) / "changed-model"
        shutil.copytree(self.model_path, model_path)
        with (model_path / "tokenizer_config.json").open("a") as target:
            target.write("\n")
        self.assertNotEqual(directory, self.cached(model_path=model_path).cache.directory)

    @unittest.skipUnless(torch is not None and torch.cuda.is_available(), "CUDA required")
    def test_cuda_float32_float16_cold_warm_and_disk(self):
        for dtype in ("float32", "float16"):
            with self.subTest(dtype=dtype):
                base = TorchEngine(replace(self.settings, device="cuda", dtype=dtype))
                self.addCleanup(base.close)
                engine = self.cached(device="cuda", dtype=dtype)
                for prompt in ([3, 8, 9, 10], [3, 8, 9, 11, 12]):
                    request = self.request(prompt)
                    expected = base.generate(request)
                    self.assertEqual(engine.generate(request), expected)
                    self.assertEqual(engine.generate(request), expected)
                engine.close()
                engine = self.cached(device="cuda", dtype=dtype, cache_ram_mib=0)
                self.assertEqual(engine.generate(self.request()), base.generate(self.request()))
                self.assertEqual(engine.cache.stats["disk_hits"], 1)
                engine.close()


if __name__ == "__main__":
    unittest.main()
