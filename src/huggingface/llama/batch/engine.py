"""Queue Llama requests for padded batch generation."""

from huggingface.runtime.batching import EngineSettings, BatchEngine
from .backend import BatchBackend


class TorchEngine(BatchEngine):
    def __init__(self, settings, backend_factory=BatchBackend):
        super().__init__(settings, backend_factory)
