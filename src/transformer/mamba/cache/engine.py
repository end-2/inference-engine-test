"""Reuse complete Mamba prefix checkpoints through the RAM and disk LRU store."""

from dataclasses import dataclass
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import logging
from pathlib import Path

from llamacpp.enhanced.cache.cache import Snapshot, TieredCache
from transformer.mamba.engine import EngineSettings as BaseSettings, TorchEngine as BaseEngine


@dataclass(frozen=True)
class EngineSettings(BaseSettings):
    cache_dir: Path = Path("/tmp/transformers-mamba-cache")
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
        try:
            hashes = {}
            for path in sorted(settings.model_path.rglob("*")):
                if path.is_file() and path.suffix in {".safetensors", ".json", ".txt", ".jinja"}:
                    with path.open("rb") as source:
                        hashes[str(path.relative_to(settings.model_path))] = hashlib.file_digest(
                            source, "sha256").hexdigest()
            packages = {}
            for package in ("torch", "transformers", "mamba-ssm", "causal-conv1d", "kernels", "triton"):
                try:
                    packages[package] = version(package)
                except PackageNotFoundError:
                    packages[package] = None
            namespace = json.dumps({
                "format": "transformers-mamba-state-1", "files": hashes,
                "packages": packages, "kernel_backend": self.kernel_backend,
                "dtype": settings.dtype, "device": settings.device,
                "n_ctx": settings.n_ctx, "n_threads": settings.n_threads,
                "gpu": self.torch.cuda.get_device_capability() if settings.device == "cuda" else None,
            }, sort_keys=True)
            self.cache = TieredCache(settings.cache_dir, namespace,
                                     settings.cache_ram_mib * 1024**2,
                                     settings.cache_disk_mib * 1024**2)
            self.restored_tokens = 0
        except Exception:
            super().close()
            raise

    def _restore(self, prefix):
        from safetensors.torch import load
        from transformers.models.mamba.modeling_mamba import MambaCache

        snapshot = self.cache.get(prefix, self.settings.cache_min_prefix, require_full_prefix=True)
        if snapshot is None:
            return None, 0
        try:
            tensors = load(snapshot.state)
            config = self.model.config
            expected = {f"{index}.{kind}" for index in range(config.num_hidden_layers)
                        for kind in ("conv", "ssm")}
            if set(tensors) != expected:
                raise ValueError("Invalid Mamba state keys")
            for key, tensor in tensors.items():
                width = config.conv_kernel if key.endswith(".conv") else config.state_size
                if (tuple(tensor.shape) != (1, config.intermediate_size, width)
                        or tensor.dtype != self.model.dtype):
                    raise ValueError("Invalid Mamba state shape or dtype")
            cache = MambaCache(config, 1, dtype=self.model.dtype, device=self.settings.device)
            for index in range(config.num_hidden_layers):
                cache.conv_states[index].copy_(tensors[f"{index}.conv"])
                cache.ssm_states[index].copy_(tensors[f"{index}.ssm"])
            self.restored_tokens += len(snapshot.tokens)
            return cache, len(snapshot.tokens)
        except Exception:
            logging.exception("Mamba restore failed; evaluating the prompt again")
            self.cache.discard(snapshot.tokens)
            self.cache.stats["errors"] += 1
            return None, 0

    def _capture(self, prefix, cache):
        from safetensors.torch import save

        tokens = tuple(prefix)
        if (len(tokens) < self.settings.cache_min_prefix
                or tokens in self.cache.ram or tokens in self.cache.disk):
            return
        try:
            tensors = {}
            for index, (conv, ssm) in enumerate(zip(cache.conv_states, cache.ssm_states, strict=True)):
                tensors[f"{index}.conv"] = conv.detach().to("cpu").contiguous()
                tensors[f"{index}.ssm"] = ssm.detach().to("cpu").contiguous()
            self.cache.put(Snapshot(tokens, save(tensors)))
        except Exception:
            logging.exception("Mamba snapshot failed")
            self.cache.stats["errors"] += 1

    def _generate_model(self, request, inputs, options):
        prefix = request.prompt[:-1]
        if (len(prefix) < self.settings.cache_min_prefix
                or not (self.cache.ram_limit or self.cache.disk_limit)):
            return super()._generate_model(request, inputs, options)
        cache, restored = self._restore(prefix)
        ids = inputs["input_ids"]
        # Mamba's continuation path consumes one token per forward call.
        position = self.torch.tensor([self.model.config.conv_kernel], device=self.settings.device)
        if cache is None:
            cache = self.model(input_ids=ids[:, :-1], use_cache=True).cache_params
        else:
            for index in range(restored, len(prefix)):
                if request.cancel.is_set():
                    return ids
                self.model(input_ids=ids[:, index:index + 1], cache_params=cache,
                           cache_position=position, use_cache=True)
                position.add_(1)
        if request.cancel.is_set():
            return ids
        # Checkpoint before generation mutates the state; retain one token to refresh logits.
        self._capture(prefix, cache)
        return self.model.generate(**inputs, **options, cache_params=cache, cache_position=position)

    def close(self):
        try:
            self.cache.close()
            logging.info("Mamba cache stats: %s; restored_tokens=%s", self.cache.stats, self.restored_tokens)
        finally:
            super().close()
