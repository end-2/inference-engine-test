"""Verify Jamba hybrid state, batched decoding and hierarchical cache correctness."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from enhanced_support import ROOT
from transformer.base.engine import Generation
from transformer.hybrid.engine import EngineSettings, TorchEngine

try:
    import torch
    from safetensors.torch import save
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace
    from transformers import JambaConfig, JambaForCausalLM, PreTrainedTokenizerFast
    from transformer.hybrid.backend import HybridBackend
    from transformer.hybrid.state import HybridState
    from llamacpp.enhanced.cache.cache import Snapshot
except ImportError:
    torch = None


@unittest.skipIf(torch is None, "Install transformer/requirements.txt")
class HybridTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.model_path = Path(cls.directory.name) / "model"
        torch.manual_seed(7)
        JambaForCausalLM(JambaConfig(
            vocab_size=64, hidden_size=24, intermediate_size=48, num_hidden_layers=3,
            num_attention_heads=4, num_key_value_heads=2, attn_layer_period=2, attn_layer_offset=1,
            num_experts=2, num_experts_per_tok=1, expert_layer_period=2, expert_layer_offset=1,
            mamba_d_state=4, mamba_d_conv=3, mamba_expand=2, use_mamba_kernels=False,
            max_position_embeddings=128, eos_token_id=2, pad_token_id=0,
        )).save_pretrained(cls.model_path)
        tokenizer = Tokenizer(WordLevel({f"t{i}": i for i in range(64)}, unk_token="t1"))
        tokenizer.pre_tokenizer = Whitespace()
        PreTrainedTokenizerFast(tokenizer_object=tokenizer, eos_token="t2", pad_token="t0").save_pretrained(cls.model_path)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = EngineSettings(self.model_path, n_ctx=48, n_threads=1, max_parallel=4,
                                       cache_dir=Path(self.temp.name), cache_min_prefix=2,
                                       cache_gpu_mib=0, cache_ram_mib=1, cache_disk_mib=1)

    def backend(self, **kwargs):
        backend = HybridBackend(replace(self.settings, **kwargs))
        self.addCleanup(backend.close)
        return backend

    def request(self, prompt=None, limit=4):
        return Generation(prompt if prompt is not None else [3, 8, 9, 10], limit,
                          0, 1, True, threading.Event())

    def reference(self, backend, request):
        from transformers import GenerationConfig

        config = GenerationConfig(
            max_new_tokens=request.max_tokens, do_sample=request.temperature > 0,
            temperature=request.temperature if request.temperature > 0 else 1,
            top_p=request.top_p if request.temperature > 0 else 1,
            top_k=0 if request.temperature > 0 else None, eos_token_id=sorted(backend.eos_tokens),
            suppress_tokens=sorted(backend.eos_tokens) if request.ignore_eos else None,
            pad_token_id=backend.pad_token, use_cache=False,
        )
        ids = torch.tensor([request.prompt], device=backend.settings.device)
        with torch.inference_mode():
            output = backend.model.generate(ids, generation_config=config, use_model_defaults=False)
        tokens = output[0, len(request.prompt):].tolist()
        eos = bool(tokens and tokens[-1] in backend.eos_tokens)
        if eos:
            tokens.pop()
        return backend._result(request, tokens, "length" if not eos and len(tokens) == request.max_tokens else "stop")

    def test_cold_warm_extended_divergent_and_shorter_prefixes(self):
        backend = self.backend()
        for prompt, restored in [([3, 8, 9, 10], 0), ([3, 8, 9, 10], 3),
                                 ([3, 8, 9, 11, 12, 13], 3), ([3, 8, 7, 12], 0),
                                 ([3, 8, 9], 0), ([3, 8, 35, 14], 2)]:
            with self.subTest(prompt=prompt):
                request = self.request(prompt)
                before = backend.restored_tokens
                self.assertEqual(backend.generate(request), self.reference(backend, request))
                self.assertEqual(backend.restored_tokens - before, restored)

    def test_serial_base_uses_dynamic_state_and_matches_hybrid(self):
        from transformer.hybrid.base import EngineSettings as BaseSettings, TorchEngine as BaseEngine

        base = BaseEngine(BaseSettings(self.model_path, n_ctx=48, n_threads=1))
        self.addCleanup(base.close)
        backend = self.backend()
        request = self.request()
        with patch.object(base.model, "forward", wraps=base.model.forward) as forward:
            expected = base.generate(request)
        self.assertEqual(forward.call_args_list[0].kwargs["input_ids"].shape[1], len(request.prompt))
        self.assertEqual(forward.call_args_list[1].kwargs["input_ids"].shape[1], 1)
        self.assertIsNotNone(forward.call_args_list[1].kwargs["past_key_values"])
        self.assertEqual(backend.generate(request), expected)
        self.assertEqual(backend.generate(request), expected)

    def test_mixed_lengths_batch_compaction_and_single_token_prompt(self):
        backend = self.backend()
        requests = [self.request([3], 3), self.request([3, 8, 9, 10, 11], 1),
                    self.request([4, 5, 6], 6)]
        expected = [self.reference(backend, request) for request in requests]
        for _ in range(2):
            with patch.object(backend.model, "forward", wraps=backend.model.forward) as forward:
                self.assertEqual(backend.generate_batch(requests), expected)
            shapes = [call.kwargs["input_ids"].shape for call in forward.call_args_list]
            self.assertIn(torch.Size([3, 1]), shapes)
            self.assertIn(torch.Size([2, 1]), shapes)
            self.assertIn(torch.Size([1, 1]), shapes)

    def test_equal_length_prefill_is_batched(self):
        backend = self.backend()
        requests = [self.request([3, 8, 9, 10]), self.request([4, 5, 6, 7])]
        with patch.object(backend.model, "forward", wraps=backend.model.forward) as forward:
            actual = backend.generate_batch(requests)
        self.assertEqual(forward.call_args_list[0].kwargs["input_ids"].shape, (2, 3))
        self.assertEqual(actual, [self.reference(backend, request) for request in requests])

    def test_snapshot_is_immutable_and_captures_both_kinds_of_state(self):
        backend = self.backend()
        backend.generate(self.request())
        key = (3, 8, 9)
        original = backend.cache.ram[key]
        frozen = {name: tensor.clone() for name, tensor in original.tensors.items()}
        self.assertEqual(set(frozen), {"0.conv", "0.ssm", "1.key", "1.value", "2.conv", "2.ssm"})
        self.assertEqual(frozen["1.key"].shape[2], len(key))
        backend.generate(self.request([3, 8, 9, 22, 23]))
        backend.generate(self.request())
        for name, tensor in original.tensors.items():
            self.assertTrue(torch.equal(tensor, frozen[name]))

    def test_buffer_addresses_survive_generation_and_compaction(self):
        backend = self.backend()
        pointers = {name: tensor.data_ptr() for name, tensor in backend.buffer.storage.items()}
        for _ in range(2):
            backend.generate_batch([self.request(limit=1), self.request([4, 5, 6], 5)])
            self.assertEqual(pointers, {name: tensor.data_ptr() for name, tensor in backend.buffer.storage.items()})

    def test_snapshot_rejects_cropping_recurrent_state(self):
        backend = self.backend()
        backend.generate(self.request())
        with self.assertRaisesRegex(ValueError, "prefix boundary"):
            backend.buffer.snapshot(0, [3, 8])

    def test_gpu_admission_oom_falls_back_to_host_without_losing_state(self):
        backend = self.backend()
        backend.generate(self.request())
        state = backend.cache.ram[(3, 8, 9)]
        backend.cache.discard(state.tokens)
        backend.cache.gpu_limit = state.size
        copy = HybridState.copy_to
        attempts = 0

        def fail_gpu(state, device, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise torch.cuda.OutOfMemoryError("Synthetic cache admission OOM")
            return copy(state, device, **kwargs)

        with patch.object(HybridState, "copy_to", fail_gpu):
            backend.cache.put(state)
        self.assertIn(state.tokens, backend.cache.ram)
        self.assertNotIn(state.tokens, backend.cache.gpu)
        self.assertEqual(backend.cache.stats["gpu_oom_fallbacks"], 1)
        self.assertEqual(backend.generate(self.request()), self.reference(backend, self.request()))

    def test_oversized_checkpoint_is_not_retained(self):
        backend = self.backend()
        backend.generate(self.request())
        state = backend.cache.ram[(3, 8, 9)]
        backend.cache.discard(state.tokens)
        backend.cache.gpu_limit = backend.cache.ram_limit = backend.cache.disk.disk_limit = 1
        backend.cache.put(state)
        self.assertFalse(backend.cache.contains(state.tokens))
        self.assertEqual(backend.cache.gpu_bytes + backend.cache.ram_bytes + backend.cache.disk.disk_bytes, 0)

    def test_hicache_spill_promotion_lru_and_disk_deletion(self):
        backend = self.backend()
        backend.generate(self.request())
        cache = backend.cache
        a = cache.ram[(3, 8, 9)]
        cache.discard(a.tokens)
        # CPU tensors exercise tier admission deterministically without requiring CUDA.
        cache.gpu_limit = cache.ram_limit = a.size
        b, c = HybridState((4, 5, 6), a.tensors), HybridState((7, 8, 9), a.tensors)
        cache.put(a)
        cache.put(b)
        cache.put(c)
        self.assertIn(c.tokens, cache.gpu)
        self.assertIn(b.tokens, cache.ram)
        self.assertIn(a.tokens, cache.disk.disk)
        restored = cache.get(a.tokens, 2)
        self.assertEqual(restored.tokens, a.tokens)
        self.assertIn(a.tokens, cache.gpu)
        self.assertIn(c.tokens, cache.ram)
        self.assertIn(b.tokens, cache.disk.disk)
        self.assertEqual(cache.stats["disk_hits"], 1)
        self.assertEqual(cache.get(c.tokens, 2).tokens, c.tokens)
        self.assertEqual(cache.stats["ram_hits"], 1)
        self.assertEqual(cache.get(c.tokens, 2).tokens, c.tokens)
        self.assertEqual(cache.stats["gpu_hits"], 1)
        cache.disk.disk_limit = 1
        cache.disk._trim_disk()
        self.assertGreater(cache.disk.stats["evictions"], 0)
        self.assertFalse(cache.disk.disk)
        self.assertLessEqual(cache.gpu_bytes, cache.gpu_limit)
        self.assertLessEqual(cache.ram_bytes, cache.ram_limit)

    def test_disk_restart_and_corruption_recompute(self):
        backend = self.backend(cache_ram_mib=0)
        expected = backend.generate(self.request())
        directory = backend.cache.disk.directory
        backend.close()
        restarted = self.backend(cache_ram_mib=0)
        self.assertEqual(restarted.generate(self.request()), expected)
        self.assertEqual(restarted.cache.stats["disk_hits"], 1)
        next(directory.glob("*.kv")).write_bytes(b"corrupt")
        self.assertEqual(restarted.generate(self.request()), expected)
        self.assertEqual(restarted.cache.disk.stats["errors"], 1)

    def test_invalid_checkpoint_shape_dtype_keys_and_payload(self):
        backend = self.backend(cache_ram_mib=0)
        expected = backend.generate(self.request())
        key = (3, 8, 9)
        state = backend.cache.get(key, 2)
        for corruption in ("shape", "dtype", "keys", "payload"):
            tensors = dict(state.tensors)
            if corruption == "shape":
                tensors["1.key"] = tensors["1.key"][:, :, :1].contiguous()
            elif corruption == "dtype":
                tensors["0.ssm"] = tensors["0.ssm"].half()
            elif corruption == "keys":
                del tensors["0.conv"]
            payload = b"invalid safetensors" if corruption == "payload" else save(tensors)
            backend.cache.disk.put(Snapshot(key, payload))
            with self.assertLogs(level="ERROR"):
                self.assertEqual(backend.generate(self.request()), expected)
        self.assertEqual(backend.cache.stats["errors"], 4)

    def test_disabled_cache_and_context_limits(self):
        backend = self.backend(cache_ram_mib=0, cache_disk_mib=0)
        self.assertEqual(backend.generate(self.request()), self.reference(backend, self.request()))
        self.assertFalse(backend.cache.gpu or backend.cache.ram or backend.cache.disk.disk)
        for request in (self.request([]), self.request(limit=48)):
            with patch.object(backend.model, "forward") as forward, self.assertRaises(ValueError):
                backend.generate(request)
            forward.assert_not_called()

    def test_padding_capacity_partitions_instead_of_rejecting_valid_requests(self):
        backend = self.backend(n_ctx=12)
        requests = [self.request([3, 4, 5, 6, 7, 8, 9, 10], 2), self.request([3], 10)]
        self.assertEqual(backend.generate_batch(requests), [self.reference(backend, r) for r in requests])

    def test_streaming_sampling_eos_and_cancellation(self):
        backend = self.backend()
        for ignore_eos in (True, False):
            request = self.request(limit=8)
            request.ignore_eos = ignore_eos
            request.temperature, request.top_p = 0.7, 0.8
            torch.manual_seed(19)
            expected = self.reference(backend, request)
            for _ in range(2):
                pieces = []
                request.emit = pieces.append
                torch.manual_seed(19)
                self.assertEqual(backend.generate(request), expected)
                self.assertEqual("".join(pieces), expected["text"])
        cancelled, active = self.request(limit=10), self.request([4, 5, 6], 5)
        cancelled.emit = lambda _: cancelled.cancel.set()
        actual = backend.generate_batch([cancelled, active])
        self.assertLess(actual[0]["completion_tokens"], 10)
        self.assertEqual(actual[0]["finish_reason"], "stop")
        self.assertEqual(actual[1], self.reference(backend, active))
        with patch.object(backend.model, "forward") as forward:
            self.assertEqual(backend.generate(cancelled)["completion_tokens"], 0)
            forward.assert_not_called()

    def test_mixed_sampling_options_and_forced_eos_remove_rows(self):
        backend = self.backend()
        requests = [self.request(limit=2), self.request([4, 5, 6], 4)]
        requests[1].temperature, requests[1].top_p = 0.5, 0.2
        self.assertEqual([r["completion_tokens"] for r in backend.generate_batch(requests)], [2, 4])
        requests[0].ignore_eos = False
        sample = backend._sample_batch

        def force_eos(logits, requests, active):
            values = sample(logits, requests, active)
            if 0 in active:
                values[active.index(0)] = next(iter(backend.eos_tokens))
            return values

        with patch.object(backend, "_sample_batch", side_effect=force_eos):
            actual = backend.generate_batch(requests)
        self.assertEqual(actual[0]["completion_tokens"], 0)
        self.assertEqual(actual[0]["finish_reason"], "stop")
        self.assertEqual(actual[1]["completion_tokens"], 4)

    def test_cancel_during_restored_suffix_does_not_store_partial_checkpoint(self):
        backend = self.backend()
        backend.generate(self.request())
        request = self.request([3, 8, 9, 11, 12, 13])
        forward = backend.model.forward

        def cancel(*args, **kwargs):
            output = forward(*args, **kwargs)
            request.cancel.set()
            return output

        with patch.object(backend.model, "forward", side_effect=cancel):
            self.assertEqual(backend.generate(request)["completion_tokens"], 0)
        self.assertFalse(backend.cache.contains(tuple(request.prompt[:-1])))

    def test_namespace_isolation_and_unsupported_models(self):
        backend = self.backend()
        backend.generate(self.request())
        changed = self.backend(n_ctx=49)
        self.assertNotEqual(backend.cache.disk.directory, changed.cache.disk.directory)
        self.assertEqual(changed.restored_tokens, 0)
        with patch("transformers.AutoConfig.from_pretrained", return_value=type("Config", (), {"model_type": "mamba"})()):
            with self.assertRaisesRegex(ValueError, "Jamba"):
                self.backend()
        with self.assertRaisesRegex(ValueError, "CUDA kernels"):
            self.backend(mamba_kernels="required")

    def test_worker_batches_concurrent_requests(self):
        engine = TorchEngine(replace(self.settings, batch_wait_ms=40))
        self.addCleanup(engine.close)
        requests = [self.request(), self.request([4, 5, 6])]
        expected = [self.reference(engine.backend, request) for request in requests]
        barrier = threading.Barrier(2)

        def run(request):
            barrier.wait(timeout=5)
            return engine.complete(request.prompt, request.max_tokens, request.temperature,
                                   request.top_p, request.ignore_eos, request.cancel)

        with patch.object(engine.backend, "generate_batch", wraps=engine.backend.generate_batch) as batch:
            with ThreadPoolExecutor(2) as pool:
                self.assertEqual(list(pool.map(run, requests)), expected)
            self.assertEqual(len(batch.call_args_list), 1)
            self.assertEqual(len(batch.call_args.args[0]), 2)
        engine.close()
        self.assertFalse(engine.worker.is_alive())

    @unittest.skipUnless(torch is not None and torch.cuda.is_available(), "CUDA PyTorch required")
    def test_cuda_half_and_float_buffers_cache_and_batch(self):
        for dtype in ("float32", "float16"):
            backend = self.backend(device="cuda", dtype=dtype, cache_gpu_mib=1)
            requests = [self.request([3], 3), self.request(), self.request([4, 5, 6, 7, 8], 2)]
            expected = [self.reference(backend, request) for request in requests]
            for _ in range(2):
                self.assertEqual(backend.generate_batch(requests), expected)
            self.assertGreater(backend.cache.stats["gpu_hits"], 0)
            state = next(iter(backend.cache.gpu.values()))
            self.assertTrue(all(t.is_cuda for t in state.tensors.values()))
            self.assertEqual(state.tensors["0.ssm"].dtype, torch.float32)
            for level in ("ram", "disk"):
                backend.cache.gpu_limit = 0
                backend.cache.ram_limit = 1024**2 if level == "ram" else 0
                residents = list(backend.cache.gpu.values()) + list(backend.cache.ram.values())
                for resident in residents:
                    backend.cache.discard(resident.tokens)
                    backend.cache.put(resident)
                if level == "ram":
                    self.assertTrue(all(t.is_pinned() for s in backend.cache.ram.values() for t in s.tensors.values()))
                backend.cache.gpu_limit = 1024**2
                self.assertEqual(backend.generate_batch(requests), expected)
                self.assertGreater(backend.cache.stats[f"{level}_hits"], 0)
            backend.close()


if __name__ == "__main__":
    unittest.main()
