"""Serve Jamba with batching, reusable Mamba buffers and three-tier prefix caching."""

from dataclasses import dataclass
import logging
from pathlib import Path

from huggingface.runtime import server
from huggingface.runtime.server import BatchSettings
from .engine import EngineSettings, TorchEngine


@dataclass(frozen=True)
class Settings(BatchSettings):
    served_model_name: str = "jamba-hybrid"
    cache_dir: Path = EngineSettings.cache_dir
    cache_gpu_mib: int = EngineSettings.cache_gpu_mib
    cache_ram_mib: int = EngineSettings.cache_ram_mib
    cache_disk_mib: int = EngineSettings.cache_disk_mib
    cache_min_prefix: int = EngineSettings.cache_min_prefix
    mamba_kernels: str = EngineSettings.mamba_kernels

    def engine_settings(self):
        return EngineSettings(**vars(super().engine_settings()), cache_dir=self.cache_dir,
                              cache_gpu_mib=self.cache_gpu_mib, cache_ram_mib=self.cache_ram_mib,
                              cache_disk_mib=self.cache_disk_mib, cache_min_prefix=self.cache_min_prefix,
                              mamba_kernels=self.mamba_kernels)


def create_app(settings=None, engine_factory=TorchEngine):
    return server.create_app(settings or Settings(), engine_factory)


def create_parser():
    parser = server.create_parser(__doc__)
    parser.set_defaults(served_model_name=Settings.served_model_name)
    parser.add_argument("--max-parallel", type=server.api.positive_int, default=4)
    parser.add_argument("--batch-wait-ms", type=float, default=5)
    parser.add_argument("--cache-dir", type=Path, default=Settings.cache_dir)
    parser.add_argument("--cache-gpu-mib", type=int, default=Settings.cache_gpu_mib)
    parser.add_argument("--cache-ram-mib", type=int, default=Settings.cache_ram_mib)
    parser.add_argument("--cache-disk-mib", type=int, default=Settings.cache_disk_mib)
    parser.add_argument("--cache-min-prefix", type=server.api.positive_int, default=Settings.cache_min_prefix)
    parser.add_argument("--mamba-kernels", choices=("auto", "off", "required"), default="auto")
    return parser


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    server.run_server(create_parser(), Settings, TorchEngine)


if __name__ == "__main__":
    main()
