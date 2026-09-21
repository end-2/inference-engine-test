"""Local Llama and Qwen3 inference with CPU tensors and per-request decoding state."""

from dataclasses import dataclass
from pathlib import Path
import threading
from typing import Callable


@dataclass(frozen=True)
class EngineSettings:
    model_path: Path
    n_ctx: int = 1024
    n_threads: int = 4
    dtype: str = "float32"
    enable_thinking: bool = False

    def __post_init__(self):
        if min(self.n_ctx, self.n_threads) < 1:
            raise ValueError("n_ctx and n_threads must be positive")
        if self.dtype not in {"float32", "bfloat16"}:
            raise ValueError("dtype must be float32 or bfloat16")


@dataclass
class Generation:
    prompt: list[int]
    max_tokens: int
    temperature: float
    top_p: float
    ignore_eos: bool
    cancel: threading.Event
    emit: Callable[[str], None] | None = None


class TorchEngine:
    def __init__(self, settings: EngineSettings):
        import torch
        from transformers import AutoConfig, AutoModelForCausalLM, AutoTokenizer

        if not settings.model_path.is_dir():
            raise ValueError(f"Model directory does not exist: {settings.model_path}")
        self.settings = settings
        self.torch = torch
        torch.set_num_threads(settings.n_threads)
        config = AutoConfig.from_pretrained(
            settings.model_path, local_files_only=True, trust_remote_code=False,
        )
        if config.model_type not in {"llama", "qwen3"}:
            raise ValueError("This backend supports Llama (including SmolLM2) and Qwen3 models")
        if settings.enable_thinking and config.model_type != "qwen3":
            raise ValueError("enable_thinking is only supported for Qwen3")
        if settings.n_ctx > config.max_position_embeddings:
            raise ValueError("n_ctx exceeds the model context length")
        # Qwen3 can specify a head dimension different from hidden_size / heads.
        self.head_dim = getattr(config, "head_dim", None) or (
            config.hidden_size // config.num_attention_heads
        )
        self.tokenizer = AutoTokenizer.from_pretrained(
            settings.model_path, local_files_only=True, trust_remote_code=False,
        )
        self.model = AutoModelForCausalLM.from_pretrained(
            settings.model_path, local_files_only=True, trust_remote_code=False,
            use_safetensors=True, dtype=getattr(torch, settings.dtype),
            attn_implementation="sdpa",
        ).to("cpu").eval()
        eos = self.model.generation_config.eos_token_id
        self.eos_tokens = set(eos if isinstance(eos, list) else [eos]) - {None}
        if self.tokenizer.eos_token_id is not None:
            self.eos_tokens.add(self.tokenizer.eos_token_id)
        self.pad_token = self.tokenizer.pad_token_id
        if self.pad_token is None:
            self.pad_token = next(iter(self.eos_tokens))
        self.tokenizer_lock = threading.Lock()

    def prepare_prompt(self, messages):
        with self.tokenizer_lock:
            options = ({"enable_thinking": self.settings.enable_thinking}
                       if self.model.config.model_type == "qwen3" else {})
            return self.tokenizer.apply_chat_template(
                messages, tokenize=True, add_generation_prompt=True,
                **options,
            )

    def _forward(self, ids, mask, cache=None):
        torch = self.torch
        past = cache.get_seq_length() if cache is not None else 0
        positions = mask.long().cumsum(-1) - 1
        positions.masked_fill_(mask == 0, 0)
        output = self.model(
            input_ids=ids, attention_mask=mask, past_key_values=cache,
            position_ids=positions[:, -ids.shape[1]:],
            cache_position=torch.arange(past, past + ids.shape[1], device="cpu"),
            use_cache=True, logits_to_keep=1,
        )
        return output.logits[:, -1, :], output.past_key_values

    def _prefill(self, prompts):
        torch = self.torch
        width = max(map(len, prompts))
        ids = torch.full((len(prompts), width), self.pad_token, dtype=torch.long)
        mask = torch.zeros_like(ids)
        for index, prompt in enumerate(prompts):
            ids[index, -len(prompt):] = torch.tensor(prompt, dtype=torch.long)
            mask[index, -len(prompt):] = 1
        logits, cache = self._forward(ids, mask)
        return logits, cache, mask

    def _sample(self, logits, request):
        torch = self.torch
        scores = logits.float().clone()
        if request.ignore_eos:
            scores[list(self.eos_tokens)] = -float("inf")
        if request.temperature == 0:
            return int(scores.argmax())
        scores /= request.temperature
        if request.top_p < 1:
            ordered, indices = scores.sort(descending=True)
            remove = ordered.softmax(-1).cumsum(-1) > request.top_p
            remove[1:] = remove[:-1].clone()
            remove[0] = False
            scores[indices[remove]] = -float("inf")
        return int(torch.multinomial(scores.softmax(-1), 1))

    def _streamer(self, emit):
        from transformers import TextStreamer

        class CallbackStreamer(TextStreamer):
            def on_finalized_text(self, text, stream_end=False):
                if text:
                    emit(text)

        # TextStreamer retains incomplete UTF-8 and words until they can be decoded.
        return CallbackStreamer(self.tokenizer, skip_special_tokens=True,
                                clean_up_tokenization_spaces=False)

    def generate_batch(self, requests):
        torch = self.torch
        for request in requests:
            if not request.prompt or request.max_tokens < 1:
                raise ValueError("Prompt and output token limit must be positive")
            if len(request.prompt) + request.max_tokens > self.settings.n_ctx:
                raise ValueError("Input and output tokens exceed n_ctx")
        tokens = [[] for _ in requests]
        reasons = ["stop"] * len(requests)
        streamers = [self._streamer(r.emit) if r.emit else None for r in requests]
        active = [i for i, request in enumerate(requests) if not request.cancel.is_set()]
        with torch.inference_mode():
            if active:
                logits, cache, mask = self._prefill([requests[i].prompt for i in active])
            while active:
                remaining, rows, next_tokens = [], [], []
                for row, index in enumerate(active):
                    request = requests[index]
                    if request.cancel.is_set():
                        continue
                    token = self._sample(logits[row], request)
                    if token in self.eos_tokens:
                        continue
                    tokens[index].append(token)
                    if streamers[index]:
                        streamers[index].put(torch.tensor([token]))
                    if len(tokens[index]) == request.max_tokens:
                        reasons[index] = "length"
                        continue
                    remaining.append(index)
                    rows.append(row)
                    next_tokens.append([token])
                if not remaining:
                    break
                if len(rows) != len(active):
                    indices = torch.tensor(rows, dtype=torch.long)
                    cache.batch_select_indices(indices)
                    mask = mask.index_select(0, indices)
                mask = torch.cat((mask, torch.ones((len(rows), 1), dtype=mask.dtype)), dim=1)
                logits, cache = self._forward(torch.tensor(next_tokens), mask, cache)
                active = remaining
        results = []
        for index, request in enumerate(requests):
            if streamers[index]:
                streamers[index].end()
            results.append({
                "text": self.tokenizer.decode(tokens[index], skip_special_tokens=True,
                                              clean_up_tokenization_spaces=False),
                "finish_reason": reasons[index], "prompt_tokens": len(request.prompt),
                "completion_tokens": len(tokens[index]),
            })
        return results

    def complete(self, prompt, max_tokens, temperature, top_p, ignore_eos, cancel):
        return self.generate_batch([Generation(
            prompt, max_tokens, temperature, top_p, ignore_eos, cancel,
        )])[0]

    def stream(self, prompt, max_tokens, temperature, top_p, ignore_eos, cancel, emit):
        return self.generate_batch([Generation(
            prompt, max_tokens, temperature, top_p, ignore_eos, cancel, emit,
        )])[0]

    def close(self):
        self.model = None
