"""Batch Jamba prefill and decode while preserving complete prefix checkpoints."""

from collections import defaultdict
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import logging

from huggingface.runtime.sampling import Sampling
from ..model import TorchEngine as BaseEngine
from .hicache import HiCache


class HybridBackend(Sampling, BaseEngine):
    def __init__(self, settings):
        super().__init__(settings)
        from .state import HybridBuffer

        self.cache = None
        self.buffer = None
        try:
            self.buffer = HybridBuffer(self.model.config, settings.max_parallel, settings.n_ctx,
                                       self.model.dtype, settings.device,
                                       fast_mamba=self.kernel_backend == "mamba-cuda")
            self.cache = HiCache(
                settings.cache_dir, self._namespace(),
                settings.cache_gpu_mib * 1024**2 if settings.device == "cuda" else 0,
                settings.cache_ram_mib * 1024**2, settings.cache_disk_mib * 1024**2,
                settings.device, self.buffer.validate, pin_memory=settings.device == "cuda",
            )
            self.restored_tokens = 0
            logging.info("Hybrid buffer: %s bytes; Mamba backend: %s", self.buffer.size, self.kernel_backend)
        except Exception:
            self.close()
            raise

    def _namespace(self):
        files = {}
        for path in sorted(self.settings.model_path.rglob("*")):
            if path.is_file() and path.suffix in {".safetensors", ".json", ".txt", ".jinja", ".model"}:
                with path.open("rb") as source:
                    files[str(path.relative_to(self.settings.model_path))] = hashlib.file_digest(
                        source, "sha256").hexdigest()
        packages = {}
        for name in ("torch", "transformers", "mamba-ssm", "causal-conv1d", "triton"):
            try:
                packages[name] = version(name)
            except PackageNotFoundError:
                packages[name] = None
        return json.dumps(dict(format="jamba-hybrid-state-1", files=files, packages=packages,
                               dtype=self.settings.dtype, device=self.settings.device,
                               kernel_backend=self.kernel_backend, n_ctx=self.settings.n_ctx,
                               n_threads=self.settings.n_threads,
                               gpu=self.torch.cuda.get_device_capability()
                               if self.settings.device == "cuda" else None), sort_keys=True)

    def _forward(self, ids, mask=None):
        start = self.buffer.get_seq_length()
        positions = self.torch.arange(start, start + ids.shape[1], device=self.settings.device)
        output = self.model(input_ids=ids, attention_mask=mask, past_key_values=self.buffer,
                            cache_position=positions, use_cache=True, logits_to_keep=1)
        self.buffer.commit_mamba()
        return output.logits[:, -1, :]

    def _prepare(self, requests, active):
        groups = defaultdict(list)
        prepared = {}
        for index in active:
            prefix = requests[index].prompt[:-1]
            state = self.cache.get(prefix, self.settings.cache_min_prefix) if self.cache.enabled else None
            restored = len(state.tokens) if state is not None else 0
            self.restored_tokens += restored
            if state is not None and restored == len(prefix):
                prepared[index] = state
            else:
                groups[(len(prefix), restored)].append((index, state))
        for (length, restored), group in groups.items():
            group = [(index, state) for index, state in group if not requests[index].cancel.is_set()]
            if not group:
                continue
            if restored:
                self.buffer.load([state for _, state in group])
            else:
                self.buffer.reset(len(group))
            ids = self.torch.tensor([requests[index].prompt[restored:-1] for index, _ in group],
                                    dtype=self.torch.long, device=self.settings.device)
            if length and not restored:
                self._forward(ids)
            else:
                # Both Jamba kernel paths require one-token continuation of recurrent state.
                for position in range(length - restored):
                    if all(requests[index].cancel.is_set() for index, _ in group):
                        break
                    self._forward(ids[:, position:position + 1])
            for row, (index, _) in enumerate(group):
                if requests[index].cancel.is_set():
                    continue
                state = self.buffer.snapshot(row, requests[index].prompt[:-1])
                if length >= self.settings.cache_min_prefix:
                    self.cache.put(state)
                prepared[index] = state
        return prepared

    def _generate_batch(self, requests):
        torch = self.torch
        tokens, reasons = [[] for _ in requests], ["stop"] * len(requests)
        streamers = [self._streamer(r.emit) if r.emit else None for r in requests]
        active = [i for i, r in enumerate(requests) if not r.cancel.is_set()]
        with torch.inference_mode():
            prepared = self._prepare(requests, active)
            active = [index for index in active if index in prepared and not requests[index].cancel.is_set()]
            if active:
                prefix_mask = self.buffer.load([prepared[index] for index in active])
                # Only attention history is padded; Mamba states already contain the exact prefix.
                mask = torch.ones((len(active), self.settings.n_ctx), dtype=torch.long,
                                  device=self.settings.device)
                mask[:, :prefix_mask.shape[1]].copy_(prefix_mask)
                ids = torch.tensor([[requests[index].prompt[-1]] for index in active],
                                   dtype=torch.long, device=self.settings.device)
                del prepared, prefix_mask
                logits = self._forward(ids, mask[:, :self.buffer.get_seq_length() + 1])
            while active:
                sampled = self._sample_batch(logits, requests, active)
                sampled_host = sampled.cpu()
                remaining, rows = [], []
                for row, (index, token) in enumerate(zip(active, sampled_host.tolist(), strict=True)):
                    request = requests[index]
                    if request.cancel.is_set() or token in self.eos_tokens:
                        continue
                    tokens[index].append(token)
                    if streamers[index]:
                        streamers[index].put(sampled_host[row:row + 1])
                    if len(tokens[index]) == request.max_tokens:
                        reasons[index] = "length"
                    elif not request.cancel.is_set():
                        remaining.append(index)
                        rows.append(row)
                if not remaining:
                    break
                if len(rows) != len(active):
                    self.buffer.select(rows)
                    indices = torch.tensor(rows, dtype=torch.long, device=self.settings.device)
                    mask = mask.index_select(0, indices)
                    sampled = sampled.index_select(0, indices)
                logits = self._forward(sampled.unsqueeze(1), mask[:, :self.buffer.get_seq_length() + 1])
                active = remaining
        for streamer in streamers:
            if streamer:
                streamer.end()
        return [self._result(request, output, reason)
                for request, output, reason in zip(requests, tokens, reasons, strict=True)]

    def generate_batch(self, requests):
        for request in requests:
            self._validate(request)
        if len(requests) > self.settings.max_parallel:
            raise ValueError("Batch exceeds max_parallel")
        # Left padding must not push any row past the reserved KV capacity.
        groups = []
        for index, request in enumerate(requests):
            for group in groups:
                candidate = [requests[i] for i in group] + [request]
                if max(len(r.prompt) for r in candidate) + max(r.max_tokens for r in candidate) <= self.settings.n_ctx:
                    group.append(index)
                    break
            else:
                groups.append([index])
        results = [None] * len(requests)
        for group in groups:
            for index, result in zip(group, self._generate_batch([requests[i] for i in group]), strict=True):
                results[index] = result
        return results

    def generate(self, request):
        return self.generate_batch([request])[0]

    def close(self):
        try:
            if self.cache is not None and not self.cache.closed:
                self.cache.close()
                logging.info("Hybrid HiCache: %s; disk: %s; restored_tokens=%s",
                             self.cache.stats, self.cache.disk.stats, self.restored_tokens)
        finally:
            self.buffer = None
            super().close()
