"""Coalesce queued requests into padded batches owned by one model worker."""

from concurrent.futures import Future
from dataclasses import dataclass
import logging
import math
import queue
import threading
import time

from transformers_cpu.base.engine import EngineSettings as BaseSettings, Generation
from .backend import BatchBackend


@dataclass(frozen=True)
class EngineSettings(BaseSettings):
    max_parallel: int = 4
    batch_wait_ms: float = 5

    def __post_init__(self):
        super().__post_init__()
        if self.max_parallel < 1 or not math.isfinite(self.batch_wait_ms) or self.batch_wait_ms < 0:
            raise ValueError("max_parallel must be positive and batch_wait_ms finite and nonnegative")


class TorchEngine:
    def __init__(self, settings, backend_factory=BatchBackend):
        self.settings = settings
        self.backend = backend_factory(settings)
        self.pending = queue.Queue()
        self.lock = threading.Lock()
        self.closed = False
        self.active = []
        self.worker = threading.Thread(target=self._run, name="torch-batch", daemon=True)
        self.worker.start()

    @property
    def healthy(self):
        return not self.closed

    def prepare_prompt(self, messages):
        return self.backend.prepare_prompt(messages)

    def _run(self):
        try:
            while True:
                first = self.pending.get()
                if first is None:
                    return
                jobs = [first]
                deadline = time.monotonic() + self.settings.batch_wait_ms / 1000
                while len(jobs) < self.settings.max_parallel:
                    try:
                        job = self.pending.get(timeout=max(0, deadline - time.monotonic()))
                    except queue.Empty:
                        break
                    if job is None:
                        break
                    jobs.append(job)
                with self.lock:
                    self.active = jobs
                    if self.closed:
                        for request, _ in jobs:
                            request.cancel.set()
                try:
                    results = self.backend.generate_batch([request for request, _ in jobs])
                    for (_, future), result in zip(jobs, results, strict=True):
                        future.set_result(result)
                except Exception as exc:
                    for _, future in jobs:
                        if not future.done():
                            future.set_exception(exc)
                    raise
                finally:
                    with self.lock:
                        self.active = []
                if self.closed:
                    return
        except Exception:
            logging.exception("CPU batch worker failed")
        finally:
            with self.lock:
                self.closed = True
                while not self.pending.empty():
                    job = self.pending.get_nowait()
                    if job is not None:
                        job[1].set_exception(RuntimeError("Batch worker is closed"))

    def _generate(self, *args):
        request, future = Generation(*args), Future()
        with self.lock:
            if self.closed:
                raise RuntimeError("Batch worker is closed")
            self.pending.put((request, future))
        return future.result()

    def complete(self, *args):
        return self._generate(*args)

    def stream(self, *args):
        return self._generate(*args)

    def close(self):
        with self.lock:
            self.closed = True
            for request, _ in self.active:
                request.cancel.set()
            self.pending.put(None)
        self.worker.join()
        self.backend.close()
