"""Serve Mamba with persistent prefix state checkpoints."""

from dataclasses import dataclass
import logging
from pathlib import Path

from transformer.base import server
from transformer.mamba.server import Settings as BaseSettings
from .engine import EngineSettings, TorchEngine


@dataclass(frozen=True)
class Settings(BaseSettings):
    cache_dir: Path = Path("/tmp/transformers-mamba-cache")
    cache_ram_mib: int = 64
    cache_disk_mib: int = 1024
    cache_min_prefix: int = 32

    def engine_settings(self):
        return EngineSettings(**vars(super().engine_settings()), cache_dir=self.cache_dir,
                              cache_ram_mib=self.cache_ram_mib, cache_disk_mib=self.cache_disk_mib,
                              cache_min_prefix=self.cache_min_prefix)


def create_app(settings=None, engine_factory=TorchEngine):
    return server.create_app(settings or Settings(), engine_factory)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = server.create_parser(__doc__)
    parser.set_defaults(served_model_name=Settings.served_model_name)
    parser.add_argument("--cache-dir", type=Path, default=Settings.cache_dir)
    parser.add_argument("--cache-ram-mib", type=int, default=64)
    parser.add_argument("--cache-disk-mib", type=int, default=1024)
    parser.add_argument("--cache-min-prefix", type=server.api.positive_int, default=32)
    server.run_server(parser, Settings, TorchEngine)


if __name__ == "__main__":
    main()
