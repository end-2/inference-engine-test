"""Persist only native KV sequence state; refresh logits after restoring it."""

import ctypes
import hashlib
import json
import logging
from pathlib import Path
import platform
import sys

from .cache import Snapshot, TieredCache, common_prefix


class PrefixCache:
    def __init__(self, llama, settings):
        import llama_cpp
        from llama_cpp import llama_cpp as api

        self.api, self.llama = api, llama
        self.min_prefix = settings.cache_min_prefix
        with settings.model_path.open("rb") as model:
            digest = hashlib.file_digest(model, "sha256").hexdigest()
        with Path(api._lib._name).open("rb") as library:
            library_digest = hashlib.file_digest(library, "sha256").hexdigest()
        namespace = json.dumps({"format": 1, "model": digest, "llama_cpp": llama_cpp.__version__,
                                "library": library_digest,
                                "n_ctx": settings.n_ctx, "arch": platform.machine(),
                                "byteorder": sys.byteorder}, sort_keys=True)
        self.cache = TieredCache(settings.cache_dir, namespace,
                                 settings.cache_ram_mib * 1024**2,
                                 settings.cache_disk_mib * 1024**2)
        self.restored_tokens = 0

    def restore(self, prompt):
        current = common_prefix(self.llama._input_ids, prompt)
        snapshot = self.cache.get(prompt, min_prefix=max(self.min_prefix, current + 1))
        if snapshot is None:
            return
        try:
            self.llama._ctx.kv_cache_clear()
            data = (ctypes.c_uint8 * len(snapshot.state)).from_buffer_copy(snapshot.state)
            copied = self.api.llama_state_seq_set_data(self.llama._ctx.ctx, data, len(data), 0)
            if copied != len(data):
                raise ValueError("Native KV snapshot could not be restored")
            self.llama.input_ids[:len(snapshot.tokens)] = snapshot.tokens
            self.llama.n_tokens = len(snapshot.tokens)
            # Sequence snapshots do not contain logits. generate() replays the
            # final prompt token on exact hits and evaluates new suffixes otherwise.
            self.llama._requires_eval = True
            self.restored_tokens += min(common_prefix(snapshot.tokens, prompt), len(prompt) - 1)
        except Exception:
            logging.exception("KV restore failed; evaluating the prompt again")
            self.llama._ctx.kv_cache_clear()
            self.llama.reset()
            self.cache.discard(snapshot.tokens)
            self.cache.stats["errors"] += 1

    def capture(self, prompt):
        tokens = tuple(prompt)
        if (len(prompt) < self.min_prefix or tokens in self.cache.ram or tokens in self.cache.disk
                or not (self.cache.ram_limit or self.cache.disk_limit)):
            return
        try:
            size = self.api.llama_state_seq_get_size(self.llama._ctx.ctx, 0)
            data = (ctypes.c_uint8 * size)()
            copied = self.api.llama_state_seq_get_data(self.llama._ctx.ctx, data, size, 0)
            if copied != size:
                raise ValueError("Native KV snapshot is incomplete")
            self.cache.put(Snapshot(tuple(prompt), bytes(data)))
        except Exception:
            logging.exception("KV snapshot failed")
            self.cache.stats["errors"] += 1

    def close(self):
        self.cache.close()
        logging.info("KV cache stats: %s; restored_tokens=%s", self.cache.stats, self.restored_tokens)
