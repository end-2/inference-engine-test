"""GPU batch settings and worker."""

from dataclasses import dataclass

from huggingface.runtime.batching import EngineSettings as BatchSettings, BatchEngine
from .backend import GPUBatchBackend


@dataclass(frozen=True)
class EngineSettings(BatchSettings):
    device: str = "cuda"

    def __post_init__(self):
        super().__post_init__()
        if self.device != "cuda":
            raise ValueError("GPU batch requires device=cuda")


class TorchEngine(BatchEngine):
    def __init__(self, settings, backend_factory=GPUBatchBackend):
        if settings.device != "cuda":
            raise ValueError("GPU batch requires device=cuda")
        super().__init__(settings, backend_factory=backend_factory)
