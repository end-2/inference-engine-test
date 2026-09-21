"""Reuse prompt KV tensors through the shared RAM and disk LRU store."""

from dataclasses import dataclass
import hashlib
import json
import logging
from pathlib import Path
import platform

from llamacpp.enhanced.cache.cache import Snapshot, TieredCache, common_prefix
from transformers_cpu.base.engine import EngineSettings as BaseSettings
from transformers_cpu.base.engine import TorchEngine as BaseEngine


@dataclass(frozen=True)
class EngineSettings(BaseSettings):
    cache_dir: Path = Path("/tmp/transformers-kv-cache")
    cache_ram_mib: int = 64
    cache_disk_mib: int = 1024
    cache_min_prefix: int = 32

    def __post_init__(self):
        super().__post_init__()
        if min(self.cache_ram_mib, self.cache_disk_mib) < 0 or self.cache_min_prefix < 1:
            raise ValueError("Cache budgets must be nonnegative and cache_min_prefix positive")


class TorchEngine(BaseEngine):
    def __init__(self, settings):
        super().__init__(settings)
        import transformers

        try:
            hashes = {}
            for path in sorted(settings.model_path.rglob("*")):
                if path.is_file() and path.suffix in {".safetensors", ".json", ".txt", ".jinja"}:
                    with path.open("rb") as source:
                        hashes[str(path.relative_to(settings.model_path))] = hashlib.file_digest(
                            source, "sha256").hexdigest()
            namespace = json.dumps({
                "format": "transformers-dynamic-kv-2", "files": hashes,
                "model_type": self.model.config.model_type, "head_dim": self.head_dim,
                "torch": self.torch.__version__, "transformers": transformers.__version__,
                "dtype": settings.dtype, "n_ctx": settings.n_ctx, "arch": platform.machine(),
                "attention": "sdpa", "n_threads": settings.n_threads,
            }, sort_keys=True)
            self.cache = TieredCache(settings.cache_dir, namespace,
                                     settings.cache_ram_mib * 1024**2,
                                     settings.cache_disk_mib * 1024**2)
            self.restored_tokens = 0
        except Exception:
            super().close()
            raise

    def _restore(self, prompt):
        from safetensors.torch import load
        from transformers import DynamicCache

        snapshot = self.cache.get(prompt, self.settings.cache_min_prefix)
        if snapshot is None:
            return None, 0
        # Keep one prompt token to refresh logits even on an exact cache hit.
        shared = min(common_prefix(snapshot.tokens, prompt), len(prompt) - 1)
        if shared < self.settings.cache_min_prefix:
            return None, 0
        try:
            tensors = load(snapshot.state)
            config = self.model.config
            shape = (1, config.num_key_value_heads, len(snapshot.tokens), self.head_dim)
            if len(tensors) != 2 * config.num_hidden_layers:
                raise ValueError("Invalid KV layer count")
            layers = []
            for index in range(config.num_hidden_layers):
                pair = []
                for kind in ("key", "value"):
                    tensor = tensors[f"{index}.{kind}"]
                    if tuple(tensor.shape) != shape or tensor.dtype != self.model.dtype:
                        raise ValueError("Invalid KV tensor shape or dtype")
                    pair.append(tensor[:, :, :shared, :].clone())
                layers.append(tuple(pair))
            cache = DynamicCache.from_legacy_cache(tuple(layers))
            self.restored_tokens += shared
            return cache, shared
        except Exception:
            logging.exception("KV restore failed; evaluating the prompt again")
            self.cache.discard(snapshot.tokens)
            self.cache.stats["errors"] += 1
            return None, 0

    def _capture(self, prompt, cache):
        from safetensors.torch import save

        tokens = tuple(prompt)
        if (len(prompt) < self.settings.cache_min_prefix
                or not (self.cache.ram_limit or self.cache.disk_limit)
                or tokens in self.cache.ram or tokens in self.cache.disk):
            return
        try:
            tensors = {}
            for index, (key, value) in enumerate(cache.to_legacy_cache()):
                tensors[f"{index}.key"] = key.contiguous()
                tensors[f"{index}.value"] = value.contiguous()
            self.cache.put(Snapshot(tokens, save(tensors)))
        except Exception:
            logging.exception("KV snapshot failed")
            self.cache.stats["errors"] += 1

    def _prefill(self, prompts):
        if len(prompts) != 1:
            raise ValueError("Prefix cache requires serial requests")
        prompt = prompts[0]
        cache, shared = self._restore(prompt)
        ids = self.torch.tensor([prompt[shared:]], dtype=self.torch.long)
        mask = self.torch.ones((1, len(prompt)), dtype=self.torch.long)
        logits, cache = self._forward(ids, mask, cache)
        self._capture(prompt, cache)
        return logits, cache, mask

    def close(self):
        try:
            self.cache.close()
            logging.info("KV cache stats: %s; restored_tokens=%s",
                         self.cache.stats, self.restored_tokens)
        finally:
            super().close()
