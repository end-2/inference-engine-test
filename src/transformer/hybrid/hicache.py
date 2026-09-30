"""Exclusive device, host and disk LRU tiers for complete hybrid checkpoints."""

from collections import OrderedDict
import logging

from llamacpp.enhanced.cache.cache import Snapshot, TieredCache


class HiCache:
    def __init__(self, directory, namespace, gpu_bytes, ram_bytes, disk_bytes,
                 device, validate, *, pin_memory=False):
        if min(gpu_bytes, ram_bytes, disk_bytes) < 0:
            raise ValueError("HiCache budgets must be nonnegative")
        self.disk = TieredCache(directory, namespace, 0, disk_bytes)
        self.gpu, self.ram = OrderedDict(), OrderedDict()
        self.gpu_limit, self.ram_limit = gpu_bytes, ram_bytes
        self.gpu_bytes = self.ram_bytes = 0
        self.device, self.validate, self.pin_memory = device, validate, pin_memory
        self.stats = dict(gpu_hits=0, ram_hits=0, disk_hits=0, misses=0,
                          gpu_spills=0, ram_spills=0, gpu_oom_fallbacks=0, errors=0)
        self.closed = False

    @property
    def enabled(self):
        return bool(self.gpu_limit or self.ram_limit or self.disk.disk_limit)

    def contains(self, tokens):
        return tokens in self.gpu or tokens in self.ram or tokens in self.disk.disk

    def _write_disk(self, state):
        from safetensors.torch import save

        if self.disk.disk_limit:
            try:
                tensors = {name: tensor.detach().cpu().contiguous() for name, tensor in state.tensors.items()}
                self.disk.put(Snapshot(state.tokens, save(tensors)))
            except Exception:
                self.stats["errors"] += 1
                logging.exception("Hybrid checkpoint disk write failed")

    def _put_ram(self, state):
        if state.size > self.ram_limit:
            self._write_disk(state)
            return
        while self.ram_bytes + state.size > self.ram_limit:
            _, old = self.ram.popitem(last=False)
            self.ram_bytes -= old.size
            self._write_disk(old)
            self.stats["ram_spills"] += 1
            del old
        host = state.copy_to("cpu", pin_memory=self.pin_memory)
        self.ram[state.tokens] = host
        self.ram_bytes += host.size

    def _put_gpu(self, state):
        import torch

        if state.size > self.gpu_limit:
            self._put_ram(state)
            return
        while self.gpu_bytes + state.size > self.gpu_limit:
            _, old = self.gpu.popitem(last=False)
            self.gpu_bytes -= old.size
            self._put_ram(old)
            self.stats["gpu_spills"] += 1
            del old
        try:
            resident = state.copy_to(self.device)
        except torch.cuda.OutOfMemoryError:
            self.stats["gpu_oom_fallbacks"] += 1
            self._put_ram(state)
            return
        self.gpu[state.tokens] = resident
        self.gpu_bytes += resident.size

    def put(self, state):
        if self.closed:
            raise RuntimeError("HiCache is closed")
        if not self.enabled or self.contains(state.tokens):
            return
        self.validate(state)
        self._put_gpu(state)

    def discard(self, tokens):
        if tokens in self.gpu:
            self.gpu_bytes -= self.gpu.pop(tokens).size
        if tokens in self.ram:
            self.ram_bytes -= self.ram.pop(tokens).size
        self.disk.discard(tokens)

    def get(self, prefix, min_prefix):
        from safetensors import SafetensorError
        from safetensors.torch import load
        from .state import HybridState

        if self.closed:
            raise RuntimeError("HiCache is closed")
        prefix = tuple(prefix)
        while True:
            candidates = (tokens for tier in (self.gpu, self.ram, self.disk.disk) for tokens in tier
                          if len(tokens) >= min_prefix and prefix[:len(tokens)] == tokens)
            best = max(candidates, key=len, default=None)
            if best is None:
                self.stats["misses"] += 1
                return None
            try:
                if best in self.gpu:
                    self.gpu.move_to_end(best)
                    self.stats["gpu_hits"] += 1
                    return self.gpu[best]
                if best in self.ram:
                    state = self.ram[best]
                    self.validate(state)
                    self.stats["ram_hits"] += 1
                    if state.size <= self.gpu_limit:
                        self.ram_bytes -= self.ram.pop(best).size
                        self._put_gpu(state)
                        return self.gpu.get(best, self.ram.get(best, state))
                    self.ram.move_to_end(best)
                    return state
                snapshot = self.disk.get(best, min_prefix, require_full_prefix=True)
                if snapshot is None:
                    continue
                best = snapshot.tokens
                state = HybridState(best, load(snapshot.state))
                self.validate(state)
                self.stats["disk_hits"] += 1
                if state.size <= max(self.gpu_limit, self.ram_limit):
                    self.disk.discard(best)
                    self._put_gpu(state)
                    return self.gpu.get(best, self.ram.get(best, state))
                return state
            except (ValueError, KeyError, SafetensorError):
                self.discard(best)
                self.stats["errors"] += 1
                logging.exception("Invalid hybrid checkpoint; recomputing prefix")

    def close(self):
        if self.closed:
            return
        try:
            for state in list(self.ram.values()) + list(self.gpu.values()):
                self._write_disk(state)
        finally:
            self.gpu.clear()
            self.ram.clear()
            self.gpu_bytes = self.ram_bytes = 0
            self.closed = True
            self.validate = None
            self.disk.close()
