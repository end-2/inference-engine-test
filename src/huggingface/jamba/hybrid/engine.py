"""Queue Jamba requests for one hybrid batch worker."""

from dataclasses import dataclass
from pathlib import Path

from huggingface.runtime.batching import EngineSettings as BatchSettings, BatchEngine


@dataclass(frozen=True)
class EngineSettings(BatchSettings):
    cache_dir: Path = Path("/tmp/transformers-hybrid-cache")
    cache_gpu_mib: int = 64
    cache_ram_mib: int = 256
    cache_disk_mib: int = 1024
    cache_min_prefix: int = 32
    mamba_kernels: str = "auto"

    def __post_init__(self):
        super().__post_init__()
        if min(self.cache_gpu_mib, self.cache_ram_mib, self.cache_disk_mib) < 0:
            raise ValueError("HiCache budgets must be nonnegative")
        if self.cache_min_prefix < 1:
            raise ValueError("cache_min_prefix must be positive")
        if self.mamba_kernels not in {"auto", "off", "required"}:
            raise ValueError("mamba_kernels must be auto, off or required")


class TorchEngine(BatchEngine):
    def __init__(self, settings, backend_factory=None):
        from .backend import HybridBackend

        super().__init__(settings, backend_factory=backend_factory or HybridBackend)
