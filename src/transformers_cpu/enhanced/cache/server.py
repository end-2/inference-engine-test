"""Serve local models with persistent prefix KV caching on CPU."""

from dataclasses import dataclass
from pathlib import Path

from transformers_cpu.base import server
from .engine import EngineSettings, TorchEngine


@dataclass(frozen=True)
class Settings(server.Settings):
    cache_dir: Path = Path("/tmp/transformers-kv-cache")
    cache_ram_mib: int = 64
    cache_disk_mib: int = 1024
    cache_min_prefix: int = 32

    def engine_settings(self):
        return EngineSettings(**vars(super().engine_settings()),
                              cache_dir=self.cache_dir, cache_ram_mib=self.cache_ram_mib,
                              cache_disk_mib=self.cache_disk_mib,
                              cache_min_prefix=self.cache_min_prefix)


def create_app(settings=None, engine_factory=TorchEngine):
    return server.create_app(settings or Settings(), engine_factory)


def main():
    parser = server.create_parser(__doc__)
    parser.add_argument("--cache-dir", type=Path, default=Path("/tmp/transformers-kv-cache"))
    parser.add_argument("--cache-ram-mib", type=int, default=64)
    parser.add_argument("--cache-disk-mib", type=int, default=1024)
    parser.add_argument("--cache-min-prefix", type=server.api.positive_int, default=32)
    server.run_server(parser, Settings, TorchEngine)


if __name__ == "__main__":
    main()
