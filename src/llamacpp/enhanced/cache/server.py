"""Serve the shared chat API with a RAM and disk prefix KV cache."""

from dataclasses import dataclass
from pathlib import Path

from llamacpp.base import server

from .engine import EngineSettings, LlamaEngine


@dataclass(frozen=True)
class Settings(server.Settings):
    cache_dir: Path = Path("/tmp/llama-kv-cache")
    cache_ram_mib: int = 64
    cache_disk_mib: int = 1024
    cache_min_prefix: int = 32

    def engine_settings(self):
        return EngineSettings(
            **vars(super().engine_settings()),
            cache_dir=self.cache_dir, cache_ram_mib=self.cache_ram_mib,
            cache_disk_mib=self.cache_disk_mib, cache_min_prefix=self.cache_min_prefix,
        )


def create_app(settings=None, engine_factory=LlamaEngine):
    return server.create_app(settings or Settings(), engine_factory)


def main():
    parser = server.create_parser(__doc__)
    parser.add_argument("--cache-dir", type=Path, default=Path("/tmp/llama-kv-cache"))
    parser.add_argument("--cache-ram-mib", type=int, default=64)
    parser.add_argument("--cache-disk-mib", type=int, default=1024)
    parser.add_argument("--cache-min-prefix", type=server.positive_int, default=32)
    server.run_server(parser, Settings, LlamaEngine)


if __name__ == "__main__":
    main()
