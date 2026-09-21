"""Verify mixed-sequence decode, fairness, cancellation, and worker failure."""

from pathlib import Path
import threading
import unittest

from enhanced_support import load_variant

engine_module = load_variant("enhanced-batch-llamacpp")
batching = load_variant("enhanced-batch-llamacpp", "batching")


class Sampler:
    def __init__(self, request):
        self.request, self.count, self.closed = request, 0, False

    def close(self):
        self.closed = True


class Backend:
    eog = {0}

    def __init__(self, settings):
        self.owner = threading.get_ident()
        self.rows, self.history, self.samplers = [], {}, []
        self.entered, self.release_gate = threading.Event(), threading.Event()
        self.fail, self.closed = False, False

    def prepare_prompt(self, messages):
        assert threading.get_ident() == self.owner
        return [1, 2]

    def make_sampler(self, request):
        sampler = Sampler(request)
        self.samplers.append(sampler)
        return sampler

    def decode(self, rows):
        assert threading.get_ident() == self.owner
        self.entered.set()
        if not self.release_gate.wait(5):
            raise RuntimeError("Test decode timed out")
        if self.fail:
            raise RuntimeError("decode failed")
        self.rows.append(list(rows))
        for sequence, position, token, _ in rows:
            history = self.history.setdefault(sequence, [])
            assert len(history) == position, (sequence, len(history), position)
            history.append(token)

    def sample(self, sampler, index):
        if not sampler.request.ignore_eos:
            return 0
        sampler.count += 1
        return (sampler.count - 1) % 3 + 1

    def piece(self, token):
        return {1: b"\xe2", 2: b"\x82", 3: b"\xac"}[token]

    def release(self, sequence):
        self.history.pop(sequence, None)

    def close(self):
        self.closed = True


class BatchTests(unittest.TestCase):
    def setUp(self):
        settings = engine_module.EngineSettings(Path("unused"), n_ctx=64, n_batch=4,
                                                max_parallel=2, prefill_chunk=2)
        self.worker = batching.BatchWorker(settings, Backend)
        self.backend = self.worker.backend
        self.addCleanup(self.worker.close)
        self.addCleanup(self.backend.release_gate.set)

    def enqueue(self, prompt, count=6, cancel=None, ignore_eos=True, emit=None):
        request = batching.Request(prompt, count, 0, 1, ignore_eos, cancel or threading.Event(), emit)
        self.worker._enqueue(("request", request))
        return request.future

    def test_chunked_prefill_batches_with_decode_and_reuses_slots(self):
        first = self.enqueue(list(range(24)))
        self.assertTrue(self.backend.entered.wait(2))
        pieces = []
        second = self.enqueue([1, 2], emit=pieces.append)
        third = self.enqueue([3, 4])
        self.backend.release_gate.set()
        for future in [first, second, third]:
            result = future.result(5)
            self.assertEqual(result["text"], "€€")
            self.assertEqual(result["completion_tokens"], 6)
        self.assertEqual("".join(pieces), "€€")
        self.assertEqual(self.worker.stats["max_decode_sequences"], 2)
        self.assertTrue(any(any(row[3] for row in rows) and any(not row[3] for row in rows)
                            and len({row[0] for row in rows}) == 2 for rows in self.backend.rows))
        self.assertTrue(all(len(rows) <= 4 for rows in self.backend.rows))
        self.assertTrue(all(sampler.closed for sampler in self.backend.samplers))

    def test_cancel_active_and_queued_requests_without_cancelling_peers(self):
        cancel = threading.Event()
        first = self.enqueue([1, 2], cancel=cancel)
        self.assertTrue(self.backend.entered.wait(2))
        second = self.enqueue([3, 4])
        cancelled = threading.Event()
        cancelled.set()
        third = self.enqueue([5, 6], cancel=cancelled)
        cancel.set()
        self.backend.release_gate.set()
        self.assertEqual(first.result(5)["completion_tokens"], 0)
        self.assertEqual(second.result(5)["completion_tokens"], 6)
        self.assertEqual(third.result(5)["completion_tokens"], 0)

    def test_eog_is_not_counted_and_incomplete_utf8_is_not_emitted(self):
        self.backend.release_gate.set()
        result = self.enqueue([1], ignore_eos=False).result(5)
        self.assertEqual(result["completion_tokens"], 0)
        self.assertEqual(result["finish_reason"], "stop")
        result = self.enqueue([1], count=4).result(5)
        self.assertEqual(result["text"], "€")
        self.assertEqual(result["completion_tokens"], 4)

    def test_decode_failure_unblocks_all_callers(self):
        first = self.enqueue([1, 2])
        self.assertTrue(self.backend.entered.wait(2))
        second = self.enqueue([3, 4])
        self.backend.fail = True
        with self.assertLogs(level="ERROR"):
            self.backend.release_gate.set()
            self.worker.thread.join(5)
        for future in [first, second]:
            with self.assertRaisesRegex(RuntimeError, "decode failed"):
                future.result(1)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            self.worker.prepare_prompt([])

    def test_close_resolves_active_and_waiting_requests(self):
        first = self.enqueue(list(range(24)))
        self.assertTrue(self.backend.entered.wait(2))
        second = self.enqueue([1, 2])
        with self.worker.lock:
            self.worker.closed = True
            self.worker.commands.put(("close", None))
        self.backend.release_gate.set()
        self.worker.close()
        for future in [first, second]:
            with self.assertRaisesRegex(RuntimeError, "stopped"):
                future.result(1)
        self.assertTrue(self.backend.closed)


if __name__ == "__main__":
    unittest.main()
