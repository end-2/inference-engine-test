"""Schedule independent sequences on one native context and worker thread."""

import codecs
from collections import deque
from concurrent.futures import Future
from dataclasses import dataclass, field
import logging
import queue
import threading


@dataclass
class Request:
    prompt: list[int]
    max_tokens: int
    temperature: float
    top_p: float
    ignore_eos: bool
    cancel: threading.Event
    emit: object = None
    future: Future = field(default_factory=Future)
    position: int = 0
    generated: list[int] = field(default_factory=list)
    text: list[str] = field(default_factory=list)
    decoder: object = field(default_factory=lambda: codecs.getincrementaldecoder("utf-8")("ignore"))
    sequence: int | None = None
    sampler: object = None


class BatchWorker:
    def __init__(self, settings, backend_factory):
        self.settings = settings
        self.commands = queue.Queue()
        self.lock = threading.Lock()
        self.closed = False
        self.ready = Future()
        self.pending = deque()
        self.active = {}
        self.stats = {"decode_calls": 0, "batched_decode_calls": 0, "max_decode_sequences": 0}
        self.thread = threading.Thread(target=self._run, args=(backend_factory,),
                                       name="llama-batch", daemon=True)
        self.thread.start()
        self.ready.result()

    def _enqueue(self, command):
        with self.lock:
            if self.closed:
                raise RuntimeError("Batch worker is closed")
            self.commands.put(command)

    def prepare_prompt(self, messages):
        future = Future()
        self._enqueue(("prompt", (messages, future)))
        return future.result()

    def generate(self, prompt, max_tokens, temperature, top_p, ignore_eos, cancel, emit=None):
        if not prompt or max_tokens < 1 or len(prompt) + max_tokens > self.settings.n_ctx:
            raise ValueError("Input and output tokens must fit n_ctx")
        request = Request(list(prompt), max_tokens, temperature, top_p, ignore_eos, cancel, emit)
        self._enqueue(("request", request))
        return request.future.result()

    def close(self):
        with self.lock:
            if not self.closed:
                self.closed = True
                self.commands.put(("close", None))
        self.thread.join()

    def _command(self, command):
        kind, value = command
        if kind == "close":
            return False
        if kind == "request":
            self.pending.append(value)
        else:
            messages, future = value
            try:
                future.set_result(self.backend.prepare_prompt(messages))
            except Exception as exc:
                future.set_exception(exc)
        return True

    def _run(self, backend_factory):
        self.backend = None
        failure = RuntimeError("Batch worker stopped")
        try:
            self.backend = backend_factory(self.settings)
            self.ready.set_result(None)
            while True:
                if not self.active and not self.pending:
                    if not self._command(self.commands.get()):
                        break
                # Bound command handling so a stream of arrivals cannot starve decode.
                for _ in range(64):
                    try:
                        command = self.commands.get_nowait()
                    except queue.Empty:
                        break
                    if not self._command(command):
                        return
                self._admit()
                if self.active:
                    self._step()
        except BaseException as exc:
            failure = exc
            if not self.ready.done():
                self.ready.set_exception(exc)
            else:
                logging.exception("Batch worker failed")
        finally:
            with self.lock:
                self.closed = True
            for request in list(self.active.values()) + list(self.pending):
                if request.sampler:
                    request.sampler.close()
                if not request.future.done():
                    request.future.set_exception(failure)
            while not self.commands.empty():
                kind, value = self.commands.get_nowait()
                future = value.future if kind == "request" else value[1] if kind == "prompt" else None
                if future is not None and not future.done():
                    future.set_exception(failure)
            if self.backend:
                self.backend.close()

    def _admit(self):
        for request in list(self.active.values()):
            if request.cancel.is_set():
                self._finish(request, "stop")
        while self.pending and len(self.active) < self.settings.max_parallel:
            request = self.pending.popleft()
            if request.cancel.is_set():
                self._finish(request, "stop")
                continue
            sequence = next(i for i in range(self.settings.max_parallel) if i not in self.active)
            try:
                request.sampler = self.backend.make_sampler(request)
            except Exception as exc:
                request.future.set_exception(exc)
                continue
            request.sequence = sequence
            self.active[sequence] = request

    def _step(self):
        rows, samples = [], []
        requests = list(self.active.values())
        # Reserve one token for each decoding sequence before adding prompt chunks.
        decoding = [r for r in requests if r.generated]
        prefilling = [r for r in requests if not r.generated]
        for request in decoding:
            rows.append((request.sequence, request.position, request.generated[-1], True))
            request.position += 1
            samples.append((request, len(rows) - 1))
        for i, request in enumerate(prefilling):
            budget = self.settings.n_batch - len(rows)
            count = min(self.settings.prefill_chunk, budget // (len(prefilling) - i),
                        len(request.prompt) - request.position)
            for token in request.prompt[request.position:request.position + count]:
                request.position += 1
                last = request.position == len(request.prompt)
                rows.append((request.sequence, request.position - 1, token, last))
            if request.position == len(request.prompt):
                samples.append((request, len(rows) - 1))
        self.backend.decode(rows)
        sequences = len({row[0] for row in rows})
        self.stats["decode_calls"] += 1
        self.stats["batched_decode_calls"] += int(sequences > 1)
        self.stats["max_decode_sequences"] = max(self.stats["max_decode_sequences"], sequences)
        for request, index in samples:
            if request.cancel.is_set():
                self._finish(request, "stop")
                continue
            token = self.backend.sample(request.sampler, index)
            if token in self.backend.eog:
                self._finish(request, "stop")
                continue
            request.generated.append(token)
            self._emit(request, request.decoder.decode(self.backend.piece(token)))
            if len(request.generated) == request.max_tokens:
                self._finish(request, "length")

    def _emit(self, request, text):
        if text:
            request.text.append(text)
            if request.emit:
                request.emit(text)

    def _finish(self, request, reason):
        self._emit(request, request.decoder.decode(b"", final=True))
        if request.sequence is not None:
            self.backend.release(request.sequence)
            del self.active[request.sequence]
            request.sampler.close()
        request.future.set_result({"text": "".join(request.text), "finish_reason": reason,
                                   "prompt_tokens": len(request.prompt),
                                   "completion_tokens": len(request.generated)})
