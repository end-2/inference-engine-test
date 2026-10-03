"""Bounded continuous batching with RUNNING-first token budgets."""

from collections import deque
from concurrent.futures import Future
from dataclasses import dataclass, field
import json
import logging
import threading
import time

from inference.contracts import Generation
from .engine import State


@dataclass
class Work:
    kind: str
    prompt: list[int]
    max_tokens: int
    ignore_eos: bool = True
    load: object = None
    finish: object = None
    metrics: dict = field(default_factory=dict)


@dataclass(eq=False)
class Job:
    work: Work
    cancel: threading.Event
    emit: object
    future: Future = field(default_factory=Future)
    arrived: float = field(default_factory=time.perf_counter)
    started: float = 0
    first_token: float = 0
    state: object = None
    computed: int = 0
    tokens: list[int] = field(default_factory=list)
    streamer: object = None
    steps: int = 0
    prefill_steps: int = 0

    @property
    def reservation(self):
        return len(self.work.prompt) + (0 if self.work.kind == "prefill" else self.work.max_tokens)

    @property
    def remaining(self):
        return len(self.work.prompt) + len(self.tokens) - self.computed


def select_running(running, budget, chunk_limit=0):
    selected = []
    for job in running:
        if not budget:
            break
        count = min(job.remaining, budget)
        if chunk_limit:
            count = min(count, chunk_limit)
        if count:
            selected.append((job, count))
            budget -= count
    return selected, budget


class TokenScheduler:
    def __init__(self, engine, token_budget=256, max_seqs=8, max_kv_tokens=8192,
                 chunk_limit=0, trace=False):
        if min(token_budget, max_seqs, max_kv_tokens) < 1 or chunk_limit < 0:
            raise ValueError("Invalid scheduler limits")
        self.engine, self.token_budget, self.max_seqs = engine, token_budget, max_seqs
        self.max_kv_tokens, self.chunk_limit, self.trace = max_kv_tokens, chunk_limit, trace
        self.condition = threading.Condition()
        self.waiting, self.running = deque(), []
        self.closed, self.failure, self.step_id = False, None, 0
        self.worker = threading.Thread(target=self._run, name="pd-token-budget", daemon=True)
        self.worker.start()

    def submit(self, work, cancel, emit):
        self.engine.validate_prompt(work.prompt, work.max_tokens)
        job = Job(work, cancel, emit)
        if work.kind not in {"aggregated", "prefill", "decode"}:
            raise ValueError("Unknown scheduled work kind")
        if job.reservation > self.max_kv_tokens:
            raise ValueError("Request exceeds --max-kv-tokens reservation")
        with self.condition:
            if self.closed or self.failure:
                raise RuntimeError("Token scheduler is unavailable")
            self.waiting.append(job)
            self.condition.notify()
        return job.future

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify()
        self.worker.join()

    def _admit(self, job):
        job.started = time.perf_counter()
        job.streamer = self.engine._streamer(job.emit) if job.emit else None
        if job.work.kind == "decode":
            job.state = job.work.load(self.engine)
            job.work.load = None
            # Recompute only the final prompt token to sample the first output.
            # This keeps decoder admission a one-token model step as in a KV hit.
            job.computed = len(job.work.prompt) - 1
            job.state.cache.crop(job.computed)
        else:
            job.state = State(job.work.prompt, None, None, {})
        job.state.metrics.update(job.work.metrics)
        queue_ms = (job.started - job.arrived) * 1000
        job.state.metrics["decode_queue_ms" if job.work.kind == "decode" else "prefill_queue_ms"] = queue_ms
        self.running.append(job)

    def _finish(self, job, reason="stop"):
        metrics = job.state.metrics
        metrics.update(scheduler="token-budget", scheduler_steps=job.steps,
                       prefill_chunks=job.prefill_steps, token_budget=self.token_budget,
                       max_num_seqs=self.max_seqs, max_kv_tokens=self.max_kv_tokens)
        if job.work.kind == "prefill":
            try:
                result = job.work.finish(self.engine, job.state)
            except ValueError as exc:
                self.running.remove(job)
                job.state = None
                job.work.finish = None
                job.future.set_exception(exc)
                return
        else:
            if job.streamer:
                job.streamer.end()
            now = time.perf_counter()
            metrics.update(decode_ms=(now - (job.first_token or job.started)) * 1000,
                           decode_first_token_ms=((job.first_token or now) - job.started) * 1000)
            request = Generation(job.work.prompt, job.work.max_tokens, 0, 1,
                                 job.work.ignore_eos, job.cancel, job.emit)
            result = {**self.engine._result(request, job.tokens, reason), "metrics": metrics}
        job.state = None
        job.work.load = job.work.finish = None
        self.running.remove(job)
        job.future.set_result(result)

    def _run(self):
        try:
            while True:
                with self.condition:
                    while not self.running and not self.waiting and not self.closed:
                        self.condition.wait()
                    if self.closed:
                        break
                    for job in list(self.waiting):
                        if job.cancel.is_set():
                            self.waiting.remove(job)
                            job.future.cancel()
                for job in list(self.running):
                    if job.cancel.is_set():
                        self.running.remove(job)
                        job.state = None
                        job.future.cancel()
                selected, budget = select_running(self.running, self.token_budget, self.chunk_limit)
                reserved = sum(job.reservation for job in self.running)
                while budget and len(self.running) < self.max_seqs:
                    with self.condition:
                        if not self.waiting:
                            break
                        job = self.waiting[0]
                        if reserved + job.reservation > self.max_kv_tokens:
                            break
                        self.waiting.popleft()
                    try:
                        self._admit(job)
                    except ValueError as exc:
                        job.future.set_exception(exc)
                        job.state = None
                        job.work.load = job.work.finish = None
                        continue
                    except Exception as exc:
                        job.future.set_exception(exc)
                        raise
                    reserved += job.reservation
                    added, budget = select_running([job], budget, self.chunk_limit)
                    selected.extend(added)
                with self.condition:
                    waiting_count = len(self.waiting)
                if not selected:
                    continue
                self._step(selected, waiting_count)
        except Exception as exc:
            self.failure = exc
            logging.exception("PD token scheduler failed")
        finally:
            with self.condition:
                self.closed = True
                for job in [*self.running, *self.waiting]:
                    if not job.future.done():
                        job.future.set_exception(RuntimeError("Token scheduler stopped"))
                    job.state = None
                    job.work.load = job.work.finish = None
                self.running.clear()
                self.waiting.clear()

    def _step(self, selected, waiting_count):
        start = time.perf_counter()
        self.step_id += 1
        plans, prefills, decodes = [], 0, 0
        for job, count in selected:
            is_prefill = job.work.kind != "decode" and job.computed < len(job.work.prompt)
            prefills += count if is_prefill else 0
            decodes += 0 if is_prefill else count
            sequence = job.work.prompt + job.tokens
            plans.append((job.state, sequence[job.computed:job.computed + count]))
            job.prefill_steps += int(is_prefill)
            job.steps += 1
        self.engine.packed_forward(plans)
        # Transfer all sampled token IDs together after the single packed forward.
        ready = [job for job, count in selected if job.computed + count >= len(job.work.prompt)
                 and job.work.kind != "prefill"]
        token_ids = self.engine.sample_batch([(job.state.logits, job.work.ignore_eos) for job in ready])
        sampled = dict(zip(ready, token_ids))
        now = time.perf_counter()
        for job, count in selected:
            job.computed += count
            if job.computed < len(job.work.prompt):
                continue
            if job.work.kind != "decode" and not job.first_token:
                job.state.metrics["prefill_ms"] = (now - job.started) * 1000
            if job.work.kind == "prefill":
                self._finish(job)
                continue
            token = sampled[job]
            if not job.first_token:
                job.first_token = now
            if token in self.engine.eos_tokens and not job.work.ignore_eos:
                self._finish(job)
                continue
            job.tokens.append(token)
            if job.streamer:
                job.streamer.put(self.engine.torch.tensor([token]))
            if len(job.tokens) >= job.work.max_tokens:
                self._finish(job, "length")
        if self.trace:
            logging.getLogger("uvicorn.error").info("pd_scheduler %s", json.dumps({
                "step": self.step_id, "requests": len(selected), "prefill_tokens": prefills,
                "decode_tokens": decodes, "scheduled_tokens": prefills + decodes,
                "token_budget": self.token_budget, "waiting": waiting_count,
                "running": len(self.running), "step_ms": (time.perf_counter() - start) * 1000}))
