"""Local SmolLM2 inference with CPU tensors and per-request decoding state."""

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
        from transformers import AutoConfig, AutoTokenizer, LlamaForCausalLM

        if not settings.model_path.is_dir():
            raise ValueError(f"Model directory does not exist: {settings.model_path}")
        self.settings = settings
        self.torch = torch
        torch.set_num_threads(settings.n_threads)
        config = AutoConfig.from_pretrained(
            settings.model_path, local_files_only=True, trust_remote_code=False,
        )
        if config.model_type != "llama":
            raise ValueError("SmolLM2 requires a Llama model configuration")
        if settings.n_ctx > config.max_position_embeddings:
            raise ValueError("n_ctx exceeds the model context length")
        self.head_dim = config.hidden_size // config.num_attention_heads
        self.tokenizer = AutoTokenizer.from_pretrained(
            settings.model_path, local_files_only=True, trust_remote_code=False,
        )
        self.model = LlamaForCausalLM.from_pretrained(
            settings.model_path, config=config, local_files_only=True,
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
        self.tokenizer.pad_token_id = self.pad_token
        self.tokenizer.padding_side = "left"
        self.tokenizer_lock = threading.Lock()

    def prepare_prompt(self, messages):
        with self.tokenizer_lock:
            return self.tokenizer.apply_chat_template(
                messages, tokenize=True, add_generation_prompt=True,
            )

    def _validate(self, request):
        if not request.prompt or request.max_tokens < 1:
            raise ValueError("Prompt and output token limit must be positive")
        if len(request.prompt) + request.max_tokens > self.settings.n_ctx:
            raise ValueError("Input and output tokens exceed n_ctx")

    def _result(self, request, tokens, reason):
        return {
            "text": self.tokenizer.decode(tokens, skip_special_tokens=True,
                                          clean_up_tokenization_spaces=False),
            "finish_reason": reason, "prompt_tokens": len(request.prompt),
            "completion_tokens": len(tokens),
        }

    def _streamer(self, emit, skip_prompt=False):
        from transformers import TextStreamer

        class CallbackStreamer(TextStreamer):
            def on_finalized_text(self, text, stream_end=False):
                if text:
                    emit(text)

        return CallbackStreamer(self.tokenizer, skip_prompt=skip_prompt,
                                skip_special_tokens=True, clean_up_tokenization_spaces=False)

    def _generate_model(self, request, inputs, options):
        return self.model.generate(**inputs, **options)

    def generate(self, request):
        from transformers import GenerationConfig, StoppingCriteria, StoppingCriteriaList

        self._validate(request)
        if request.cancel.is_set():
            return self._result(request, [], "stop")

        class Cancelled(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs):
                return request.cancel.is_set()

        # An explicit config avoids model defaults such as top_k=50 changing sampling.
        config = GenerationConfig(
            max_new_tokens=request.max_tokens, do_sample=request.temperature > 0,
            temperature=request.temperature if request.temperature > 0 else 1.0,
            top_p=request.top_p if request.temperature > 0 else 1.0,
            top_k=0 if request.temperature > 0 else None,
            eos_token_id=sorted(self.eos_tokens), pad_token_id=self.pad_token,
            suppress_tokens=sorted(self.eos_tokens) if request.ignore_eos else None,
            use_cache=True,
        )
        ids = self.torch.tensor([request.prompt], dtype=self.torch.long)
        inputs = {"input_ids": ids, "attention_mask": self.torch.ones_like(ids)}
        options = {
            "generation_config": config, "use_model_defaults": False,
            "stopping_criteria": StoppingCriteriaList([Cancelled()]),
            "streamer": self._streamer(request.emit, skip_prompt=True) if request.emit else None,
        }
        with self.torch.inference_mode():
            output = self._generate_model(request, inputs, options)
        tokens = output[0, len(request.prompt):].tolist()
        # API usage excludes the prompt and terminal EOS, including at the length limit.
        eos = bool(tokens and tokens[-1] in self.eos_tokens)
        if eos:
            tokens.pop()
        reason = "length" if not eos and len(tokens) == request.max_tokens else "stop"
        return self._result(request, tokens, reason)

    def complete(self, prompt, max_tokens, temperature, top_p, ignore_eos, cancel):
        return self.generate(Generation(
            prompt, max_tokens, temperature, top_p, ignore_eos, cancel,
        ))

    def stream(self, prompt, max_tokens, temperature, top_p, ignore_eos, cancel, emit):
        return self.generate(Generation(
            prompt, max_tokens, temperature, top_p, ignore_eos, cancel, emit,
        ))

    def close(self):
        self.model = None
