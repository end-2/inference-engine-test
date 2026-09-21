"""Extend the base inference engine with persistent prefix KV reuse."""

from dataclasses import dataclass
from pathlib import Path

from llamacpp.base.engine import EngineSettings as BaseEngineSettings, LlamaEngine as BaseLlamaEngine

from .prefix_cache import PrefixCache


@dataclass(frozen=True)
class EngineSettings(BaseEngineSettings):
    cache_dir: Path = Path("/tmp/llama-kv-cache")
    cache_ram_mib: int = 64
    cache_disk_mib: int = 1024
    cache_min_prefix: int = 32

    def __post_init__(self):
        if self.cache_ram_mib < 0 or self.cache_disk_mib < 0 or self.cache_min_prefix < 1:
            raise ValueError("Cache budgets must be nonnegative and cache_min_prefix positive")


class LlamaEngine(BaseLlamaEngine):
    def __init__(self, settings: EngineSettings):
        super().__init__(settings)
        try:
            self.prefix_cache = PrefixCache(self.llama, settings)
        except Exception:
            super().close()
            raise

    def _generate(self, generate, tokens, *args, **kwargs):
        prompt = list(tokens)
        if kwargs.get("reset", True):
            self.prefix_cache.restore(prompt)
        source = super()._generate(generate, prompt, *args, **kwargs)
        try:
            for index, token in enumerate(source):
                if index == 0:
                    self.prefix_cache.capture(prompt)
                yield token
        finally:
            source.close()

    def close(self):
        try:
            self.prefix_cache.close()
        finally:
            super().close()
