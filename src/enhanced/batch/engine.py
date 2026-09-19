"""CPU inference with continuous batching and chunked prompt processing."""

from dataclasses import dataclass

from base.engine import EngineSettings as BaseEngineSettings

from .batching import BatchWorker
from .native import NativeBackend


@dataclass(frozen=True)
class EngineSettings(BaseEngineSettings):
    n_threads_batch: int | None = None
    n_ubatch: int = 512
    max_parallel: int = 8
    prefill_chunk: int = 64

    def __post_init__(self):
        for name in ("n_ctx", "n_batch", "n_threads", "n_ubatch", "max_parallel", "prefill_chunk"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be greater than zero")
        if self.n_threads_batch is not None and self.n_threads_batch < 1:
            raise ValueError("n_threads_batch must be greater than zero")
        if self.max_parallel > self.n_batch:
            raise ValueError("max_parallel must not exceed n_batch")


class LlamaEngine:
    def __init__(self, settings, backend_factory=NativeBackend):
        self.worker = BatchWorker(settings, backend_factory)

    def prepare_prompt(self, messages):
        return self.worker.prepare_prompt(messages)

    @property
    def healthy(self):
        return not self.worker.closed

    def complete(self, prompt, max_tokens, temperature, top_p, ignore_eos, cancel):
        return self.worker.generate(prompt, max_tokens, temperature, top_p, ignore_eos, cancel)

    def stream(self, prompt, max_tokens, temperature, top_p, ignore_eos, cancel, emit):
        return self.worker.generate(prompt, max_tokens, temperature, top_p, ignore_eos, cancel, emit)

    def close(self):
        self.worker.close()
