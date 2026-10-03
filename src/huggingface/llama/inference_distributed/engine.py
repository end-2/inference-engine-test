"""Use the same prefill and greedy decode loop on both deployment paths."""

from dataclasses import dataclass
import hashlib
import time

from inference.contracts import Generation
from huggingface.llama.model import TorchEngine


@dataclass
class State:
    prompt: list[int]
    cache: object
    logits: object
    metrics: dict


class PDEngine(TorchEngine):
    def __init__(self, settings):
        super().__init__(settings)
        digest = hashlib.sha256()
        # Detect different weights or tokenizers even when served names agree.
        for path in sorted(settings.model_path.iterdir()):
            if path.is_file() and path.suffix in {".json", ".safetensors", ".model"}:
                digest.update(path.name.encode())
                with path.open("rb") as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(chunk)
        digest.update(f"pd-v1:{settings.dtype}:{settings.n_ctx}".encode())
        self.fingerprint = digest.hexdigest()

    def synchronize(self):
        if self.settings.device == "cuda":
            self.torch.cuda.synchronize()

    def _forward(self, ids, cache=None):
        torch = self.torch
        past = cache.get_seq_length() if cache is not None else 0
        mask = torch.ones((1, past + ids.shape[1]), dtype=torch.long, device=ids.device)
        output = self.model(
            input_ids=ids, attention_mask=mask, past_key_values=cache,
            cache_position=torch.arange(past, past + ids.shape[1], device=ids.device),
            use_cache=True, logits_to_keep=1,
        )
        return output.logits[:, -1, :].float(), output.past_key_values

    def validate_prompt(self, prompt, max_tokens):
        if (not isinstance(prompt, list) or not prompt
                or any(type(t) is not int or not 0 <= t < self.model.config.vocab_size for t in prompt)):
            raise ValueError("Invalid prompt token IDs")
        if type(max_tokens) is not int or max_tokens < 1 or len(prompt) + max_tokens > self.settings.n_ctx:
            raise ValueError("Input and output tokens exceed the context limit")

    def prefill(self, prompt):
        from transformers import DynamicCache

        start = time.perf_counter()
        with self.torch.inference_mode():
            ids = self.torch.tensor([prompt], dtype=self.torch.long, device=self.settings.device)
            logits, cache = self._forward(ids, DynamicCache(config=self.model.config))
            self.synchronize()
        return State(prompt, cache, logits, {"prefill_ms": (time.perf_counter() - start) * 1000})

    def export_state(self, state):
        from safetensors.torch import save

        start = time.perf_counter()
        tensors = {"logits": state.logits.cpu().contiguous()}
        for index, layer in enumerate(state.cache.layers):
            tensors[f"key.{index}"] = layer.keys.cpu().contiguous()
            tensors[f"value.{index}"] = layer.values.cpu().contiguous()
        payload = save(tensors)
        state.metrics["export_ms"] = (time.perf_counter() - start) * 1000
        state.metrics["kv_bytes"] = sum(t.numel() * t.element_size() for k, t in tensors.items() if k != "logits")
        return payload

    def import_state(self, metadata, payload):
        from safetensors.torch import load
        from transformers import DynamicCache

        start = time.perf_counter()
        if metadata.get("fingerprint") != self.fingerprint:
            raise ValueError("Prefill and decode model fingerprints differ")
        prompt = metadata["prompt"]
        self.validate_prompt(prompt, metadata["max_tokens"])
        try:
            tensors = load(payload)
        except Exception as exc:
            raise ValueError("Invalid safetensors state") from exc
        config = self.model.config
        expected = {"logits"} | {f"{kind}.{i}" for i in range(config.num_hidden_layers) for kind in ("key", "value")}
        if set(tensors) != expected:
            raise ValueError("State layer names do not match the model")
        shape = (1, config.num_key_value_heads, len(prompt), self.head_dim)
        for name, tensor in tensors.items():
            target_shape = (1, config.vocab_size) if name == "logits" else shape
            target_dtype = self.torch.float32 if name == "logits" else self.model.dtype
            if tuple(tensor.shape) != target_shape or tensor.dtype != target_dtype:
                raise ValueError(f"Invalid state shape or dtype: {name}")
        with self.torch.inference_mode():
            cache = DynamicCache(config=config)
            for i in range(config.num_hidden_layers):
                cache.update(tensors[f"key.{i}"].to(self.settings.device),
                             tensors[f"value.{i}"].to(self.settings.device), i)
            logits = tensors["logits"].to(self.settings.device)
            self.synchronize()
        metrics = dict(metadata["metrics"])
        metrics["import_ms"] = (time.perf_counter() - start) * 1000
        return State(prompt, cache, logits, metrics)

    def decode(self, state, max_tokens, ignore_eos, cancel, emit=None):
        self.validate_prompt(state.prompt, max_tokens)
        torch = self.torch
        request = Generation(state.prompt, max_tokens, 0, 1, ignore_eos, cancel, emit)
        streamer = self._streamer(emit) if emit else None
        tokens, reason = [], "stop"
        start = time.perf_counter()
        first_token_ms = None
        with torch.inference_mode():
            logits, cache = state.logits, state.cache
            while not cancel.is_set() and len(tokens) < max_tokens:
                if ignore_eos:
                    logits[:, sorted(self.eos_tokens)] = -float("inf")
                token = int(logits.argmax(-1).item())
                if first_token_ms is None:
                    first_token_ms = (time.perf_counter() - start) * 1000
                if token in self.eos_tokens:
                    break
                tokens.append(token)
                if streamer:
                    streamer.put(torch.tensor([token]))
                if len(tokens) == max_tokens:
                    reason = "length"
                    break
                if cancel.is_set():
                    break
                ids = torch.tensor([[token]], dtype=torch.long, device=self.settings.device)
                logits, cache = self._forward(ids, cache)
            self.synchronize()
        if streamer:
            streamer.end()
        return {
            **self._result(request, tokens, reason),
            "metrics": {**state.metrics, "decode_ms": (time.perf_counter() - start) * 1000,
                        "decode_first_token_ms": first_token_ms},
        }
