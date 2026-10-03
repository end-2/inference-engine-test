"""Verify packed attention isolation, KV handoff, and scheduler admission."""

from dataclasses import replace
import threading
import unittest
from unittest.mock import patch

import test_pd
from test_pd import TinyModel, torch

if torch is not None:
    from huggingface.llama.base.engine import EngineSettings
    from huggingface.llama.inference_distributed.engine import State
    from huggingface.llama.inference_distributed.packed import PackedEngine
    from huggingface.llama.inference_distributed.scheduler import Job, TokenScheduler, Work, select_running
    from huggingface.llama.inference_distributed import server


@unittest.skipIf(torch is None, "Install Transformers and PD requirements")
class PackedTests(TinyModel, unittest.TestCase):
    def setUp(self):
        self.engine = PackedEngine(EngineSettings(self.model_path, n_ctx=64, n_threads=1))
        self.addCleanup(self.engine.close)

    def scheduler(self, **kwargs):
        scheduler = TokenScheduler(self.engine, **kwargs)
        self.addCleanup(scheduler.close)
        return scheduler

    def test_mixed_chunks_and_decode_match_isolated_logits_and_cache(self):
        sequences = [[4, 5, 6, 7, 8], [12, 13, 14], [9, 10, 11, 12]]
        states = [State(prompt, None, None, {}) for prompt in sequences]
        for chunks in ([[4, 5], [12], [9, 10, 11]], [[6, 7, 8], [13, 14], [12]]):
            with patch.object(self.engine.model, "forward", wraps=self.engine.model.forward) as forward:
                self.engine.packed_forward(list(zip(states, chunks)))
            self.assertEqual(forward.call_count, 1)
            self.assertEqual(forward.call_args.kwargs["input_ids"].numel(), sum(map(len, chunks)))
        for state, sequence in zip(states, sequences):
            expected = self.engine.prefill(sequence)
            torch.testing.assert_close(state.logits, expected.logits, atol=2e-6, rtol=2e-5)
            for actual, target in zip(state.cache.layers, expected.cache.layers):
                torch.testing.assert_close(actual.keys, target.keys, atol=2e-6, rtol=2e-5)
                torch.testing.assert_close(actual.values, target.values, atol=2e-6, rtol=2e-5)

    def test_continuous_batch_matches_serial_and_reuses_freed_slots(self):
        prompts = [[4, 5, 6], [7] * 25, [9, 10], [11] * 18]
        counts = [12, 3, 8, 6]
        expected = [self.engine.decode(self.engine.prefill(p), n, True, threading.Event())
                    for p, n in zip(prompts, counts)]
        scheduler = self.scheduler(token_budget=8, max_seqs=2, max_kv_tokens=64, trace=True)
        with patch.object(self.engine, "packed_forward", wraps=self.engine.packed_forward) as forward:
            with scheduler.condition:
                futures = [scheduler.submit(Work("aggregated", p, n), threading.Event(), None)
                           for p, n in zip(prompts, counts)]
            actual = [f.result(timeout=10) for f in futures]
        for got, target in zip(actual, expected):
            self.assertEqual({k: v for k, v in got.items() if k != "metrics"},
                             {k: v for k, v in target.items() if k != "metrics"})
        sizes = [[len(ids) for _, ids in call.args[0]] for call in forward.call_args_list]
        self.assertTrue(all(sum(size) <= 8 and len(size) <= 2 for size in sizes))
        self.assertTrue(any(1 in size and max(size) > 1 for size in sizes), sizes)
        self.assertGreater(actual[1]["metrics"]["prefill_chunks"], 1)

    def test_transferred_state_recomputes_only_last_prompt_token(self):
        prompt = [4, 5, 6, 7]
        state = self.engine.prefill(prompt)
        payload = self.engine.export_state(state)
        metadata = {"fingerprint": self.engine.fingerprint, "prompt": prompt,
                    "max_tokens": 5, "metrics": state.metrics}
        expected = self.engine.decode(state, 5, True, threading.Event())
        scheduler = self.scheduler(token_budget=8)
        with patch.object(self.engine.model, "forward", wraps=self.engine.model.forward) as forward:
            actual = scheduler.submit(Work("decode", prompt, 5,
                load=lambda engine: engine.import_state(metadata, payload)), threading.Event(), None).result(10)
        self.assertEqual(actual["text"], expected["text"])
        self.assertEqual(actual["completion_tokens"], 5)
        self.assertEqual(forward.call_count, 5)
        self.assertEqual(forward.call_args_list[0].kwargs["input_ids"].tolist(), [[7]])
        self.assertEqual(actual["metrics"]["prefill_chunks"], 0)

    def test_invalid_import_does_not_stall_following_request_and_cancel_releases_slot(self):
        scheduler = self.scheduler(token_budget=4, max_seqs=1, max_kv_tokens=16)
        def invalid(engine):
            raise ValueError("Invalid state")
        cancelled = threading.Event()
        cancelled.set()
        with scheduler.condition:
            bad = scheduler.submit(Work("decode", [4, 5], 2, load=invalid), threading.Event(), None)
            gone = scheduler.submit(Work("aggregated", [4], 2), cancelled, None)
            good = scheduler.submit(Work("aggregated", [4, 5], 3), threading.Event(), None)
        with self.assertRaisesRegex(ValueError, "Invalid state"):
            bad.result(10)
        self.assertEqual(good.result(10)["completion_tokens"], 3)
        self.assertTrue(gone.cancelled())
        with self.assertRaisesRegex(ValueError, "reservation"):
            scheduler.submit(Work("aggregated", [4] * 16, 1), threading.Event(), None)

    def test_running_order_includes_partial_prefill_and_honors_chunk_cap(self):
        decode = Job(Work("aggregated", [4] * 5, 10), threading.Event(), None,
                     computed=5, tokens=[6])
        partial = Job(Work("aggregated", [4] * 20, 2), threading.Event(), None, computed=3)
        younger_decode = Job(Work("aggregated", [7] * 5, 10), threading.Event(), None,
                             computed=5, tokens=[8])
        selected, remaining = select_running([decode, partial, younger_decode], 8)
        self.assertEqual(selected, [(decode, 1), (partial, 7)])
        self.assertEqual(remaining, 0)
        selected, remaining = select_running([decode, partial, younger_decode], 8, 4)
        self.assertEqual(selected, [(decode, 1), (partial, 4), (younger_decode, 1)])
        self.assertEqual(remaining, 2)

    def test_cancel_running_request_releases_kv_reservation(self):
        scheduler = self.scheduler(token_budget=4, max_seqs=8, max_kv_tokens=16)
        started, release, cancel = threading.Event(), threading.Event(), threading.Event()
        forward = self.engine.packed_forward
        sizes = []

        def blocked(plans):
            sizes.append(len(plans))
            started.set()
            if not release.wait(5):
                raise RuntimeError("Test forward timed out")
            forward(plans)

        with patch.object(self.engine, "packed_forward", side_effect=blocked):
            try:
                first = scheduler.submit(Work("aggregated", [4] * 8, 8), cancel, None)
                self.assertTrue(started.wait(5))
                second = scheduler.submit(Work("aggregated", [5, 6], 3), threading.Event(), None)
                self.assertFalse(second.done())
                cancel.set()
            finally:
                release.set()
            self.assertEqual(second.result(10)["completion_tokens"], 3)
        self.assertTrue(first.cancelled())
        self.assertTrue(all(n == 1 for n in sizes))

    def test_fatal_forward_fails_all_requests_and_closes_scheduler(self):
        scheduler = self.scheduler(token_budget=4, max_seqs=1)
        with self.assertLogs(level="ERROR"), patch.object(self.engine, "packed_forward", side_effect=RuntimeError("GPU failure")):
            with scheduler.condition:
                futures = [scheduler.submit(Work("aggregated", [4, 5], 3), threading.Event(), None)
                           for _ in range(2)]
            for future in futures:
                with self.assertRaisesRegex(RuntimeError, "scheduler stopped"):
                    future.result(10)
            scheduler.close()
        self.assertTrue(scheduler.closed)
        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            scheduler.submit(Work("aggregated", [4], 1), threading.Event(), None)


class ScheduledAPITests(test_pd.APITests):
    async def asyncSetUp(self):
        create = server.create_app
        with patch.object(server, "create_app", side_effect=lambda settings: create(replace(
                settings, scheduler="token-budget", max_num_batched_tokens=4, max_num_seqs=2,
                max_kv_tokens=128))):
            await super().asyncSetUp()


if __name__ == "__main__":
    unittest.main()
