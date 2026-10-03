"""GPU batch settings and worker with explicit CUDA Graph selection."""

from dataclasses import dataclass

from huggingface.runtime.batching import EngineSettings as BatchSettings, BatchEngine
from .backend import GPUBatchBackend


@dataclass(frozen=True)
class EngineSettings(BatchSettings):
    device: str = "cuda"
    cuda_graph: str = "auto"

    def __post_init__(self):
        super().__post_init__()
        if self.device != "cuda":
            raise ValueError("GPU batch requires device=cuda")
        if self.cuda_graph not in {"auto", "off", "required"}:
            raise ValueError("cuda_graph must be auto, off or required")


class TorchEngine(BatchEngine):
    def __init__(self, settings, backend_factory=GPUBatchBackend):
        if settings.device != "cuda":
            raise ValueError("GPU batch requires device=cuda")
        super().__init__(settings, backend_factory=backend_factory)

    def runtime_info(self):
        return self.backend.runtime_info()
