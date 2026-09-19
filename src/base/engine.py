"""CPU inference engine on llama-cpp-python and GGUF weights."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EngineSettings:
    model_path: Path
    n_ctx: int = 2048
    n_batch: int = 512
    n_threads: int = 4


class LlamaEngine:
    """Format, tokenize, and generate on one model worker thread."""

    def __init__(self, settings: EngineSettings):
        from llama_cpp import Llama, StoppingCriteriaList, llama_vocab_is_eog
        from llama_cpp.llama_chat_format import Jinja2ChatFormatter

        if not settings.model_path.is_file():
            raise ValueError(f"Model file does not exist: {settings.model_path}")

        class CountingLlama(Llama):
            # Streaming completions omit usage. Count sampled token IDs instead
            # of retokenizing text, which can merge tokens or lose special tokens.
            def generate(self, *args, **kwargs):
                self.completion_tokens = 0
                for token in super().generate(*args, **kwargs):
                    if token not in self.eog_tokens:
                        self.completion_tokens += 1
                    yield token

        self.llama = CountingLlama(
            model_path=str(settings.model_path),
            n_ctx=settings.n_ctx,
            n_batch=settings.n_batch,
            n_threads=settings.n_threads,
            n_gpu_layers=0,
            verbose=False,
        )
        try:
            # The vocabulary handle is required by llama-cpp-python's pinned
            # low-level API to find every end-of-generation token.
            self.llama.eog_tokens = {
                token for token in range(self.llama.n_vocab())
                if llama_vocab_is_eog(self.llama._model.vocab, token)
            }
            self.formatter = Jinja2ChatFormatter(
                template=self.llama.metadata["tokenizer.chat_template"],
                eos_token=self._special_token(self.llama.token_eos()),
                bos_token=self._special_token(self.llama.token_bos()),
            )
        except Exception:
            self.llama.close()
            raise
        self.stopping_criteria = StoppingCriteriaList

    def _special_token(self, token: int) -> str:
        if token < 0:
            return ""
        return self.llama.detokenize([token], special=True).decode("utf-8")

    def prepare_prompt(self, messages: list[dict]) -> list[int]:
        formatted = self.formatter(messages=messages)
        return self.llama.tokenize(
            formatted.prompt.encode("utf-8"),
            add_bos=not formatted.added_special,
            special=True,
        )

    def _completion(self, prompt, max_tokens, temperature, top_p, ignore_eos, cancel, stream):
        return self.llama.create_completion(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            logit_bias={token: float("-inf") for token in self.llama.eog_tokens}
            if ignore_eos else None,
            stopping_criteria=self.stopping_criteria([lambda tokens, scores: cancel.is_set()]),
            stream=stream,
        )

    def complete(self, prompt, max_tokens, temperature, top_p, ignore_eos, cancel) -> dict:
        response = self._completion(
            prompt, max_tokens, temperature, top_p, ignore_eos, cancel, stream=False
        )
        choice = response["choices"][0]
        return {
            "text": choice["text"],
            "finish_reason": choice["finish_reason"],
            **response["usage"],
        }

    def stream(self, prompt, max_tokens, temperature, top_p, ignore_eos, cancel, emit) -> dict:
        finish_reason = "stop"
        for chunk in self._completion(
            prompt, max_tokens, temperature, top_p, ignore_eos, cancel, stream=True
        ):
            choice = chunk["choices"][0]
            if choice["text"]:
                emit(choice["text"])
            if choice["finish_reason"]:
                finish_reason = choice["finish_reason"]
        return {
            "finish_reason": finish_reason,
            "prompt_tokens": len(prompt),
            "completion_tokens": self.llama.completion_tokens,
        }

    def close(self):
        self.llama.close()
