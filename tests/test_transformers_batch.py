"""Exercise worker shutdown and failure without loading model weights."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
import unittest

from enhanced_support import ROOT
from transformers_cpu.enhanced.batch.engine import EngineSettings, TorchEngine


class BlockingBackend:
    def __init__(self, settings):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.fail = False
        self.closed = False

    def generate_batch(self, requests):
        self.entered.set()
        if self.fail:
            if not self.release.wait(3):
                raise TimeoutError("Test backend was not released")
            raise ValueError("Model failure")
        if not requests[0].cancel.wait(3):
            raise TimeoutError("Generation was not cancelled")
        return [{"cancelled": request.cancel.is_set()} for request in requests]

    def close(self):
        self.closed = True


class WorkerTests(unittest.TestCase):
    def engine(self):
        settings = EngineSettings(Path("unused"), max_parallel=1, batch_wait_ms=0)
        return TorchEngine(settings, backend_factory=BlockingBackend)

    def submit(self, pool, engine):
        return pool.submit(engine.complete, [3, 4], 8, 0, 1, True, threading.Event())

    def test_close_cancels_active_request_and_releases_waiters(self):
        engine = self.engine()
        try:
            with ThreadPoolExecutor(2) as pool:
                active = self.submit(pool, engine)
                self.assertTrue(engine.backend.entered.wait(2))
                pending = self.submit(pool, engine)
                engine.close()
                self.assertEqual(active.result(timeout=2), {"cancelled": True})
                with self.assertRaises(RuntimeError):
                    pending.result(timeout=2)
            self.assertTrue(engine.backend.closed)
            self.assertFalse(engine.worker.is_alive())
            self.assertFalse(engine.healthy)
        finally:
            engine.close()

    def test_model_failure_releases_all_waiters_and_fails_health(self):
        engine = self.engine()
        engine.backend.fail = True
        try:
            with self.assertLogs(level="ERROR"), ThreadPoolExecutor(2) as pool:
                active = self.submit(pool, engine)
                self.assertTrue(engine.backend.entered.wait(2))
                pending = self.submit(pool, engine)
                engine.backend.release.set()
                with self.assertRaisesRegex(ValueError, "Model failure"):
                    active.result(timeout=2)
                with self.assertRaises(RuntimeError):
                    pending.result(timeout=2)
            self.assertFalse(engine.healthy)
        finally:
            engine.backend.release.set()
            engine.close()


if __name__ == "__main__":
    unittest.main()
