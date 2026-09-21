"""CPU llama.cpp operations owned by the batching worker."""

from contextlib import ExitStack, closing
import ctypes
import secrets


class NativeBackend:
    def __init__(self, settings):
        import llama_cpp as api
        from llama_cpp._internals import LlamaBatch, LlamaContext, LlamaModel, LlamaSampler
        from llama_cpp._logger import set_verbose
        from llama_cpp.llama_chat_format import Jinja2ChatFormatter

        self.api = api
        self.sampler_type = LlamaSampler
        self.stack = ExitStack()
        try:
            set_verbose(False)
            api.llama_backend_init()
            model_params = api.llama_model_default_params()
            model_params.n_gpu_layers = 0
            model_params.load_mode = api.LLAMA_LOAD_MODE_MMAP
            self.model = self.stack.enter_context(closing(LlamaModel(
                path_model=str(settings.model_path), params=model_params, verbose=False)))
            params = api.llama_context_default_params()
            # n_ctx is the per-request budget exposed by the HTTP API.
            params.n_ctx = settings.n_ctx * settings.max_parallel
            params.n_seq_max = settings.max_parallel
            params.n_batch = settings.n_batch
            params.n_ubatch = min(settings.n_batch, settings.n_ubatch)
            params.n_threads = settings.n_threads
            params.n_threads_batch = settings.n_threads_batch or settings.n_threads
            params.flash_attn_type = api.LLAMA_FLASH_ATTN_TYPE_DISABLED
            self.ctx = self.stack.enter_context(closing(LlamaContext(
                model=self.model, params=params, verbose=False)))
            self.batch = self.stack.enter_context(closing(LlamaBatch(
                n_tokens=settings.n_batch, embd=0, n_seq_max=1, verbose=False)))
            self.eog = {token for token in range(self.model.n_vocab())
                        if api.llama_vocab_is_eog(self.model.vocab, token)}
            self.formatter = Jinja2ChatFormatter(
                template=self.model.metadata()["tokenizer.chat_template"],
                eos_token=self.special(self.model.token_eos()),
                bos_token=self.special(self.model.token_bos()))
        except BaseException:
            self.stack.close()
            raise

    def special(self, token):
        return self.piece(token, special=True).decode("utf-8") if token >= 0 else ""

    def prepare_prompt(self, messages):
        formatted = self.formatter(messages=messages)
        return self.model.tokenize(formatted.prompt.encode(),
                                   add_bos=not formatted.added_special, special=True)

    def make_sampler(self, request):
        sampler = self.sampler_type()
        try:
            if request.ignore_eos:
                sampler.add_logit_bias(self.model.n_vocab(),
                                       {token: float("-inf") for token in self.eog})
            if request.temperature == 0:
                sampler.add_greedy()
            else:
                # Match create_completion's default top-k and min-p filters.
                sampler.add_top_k(40)
                sampler.add_top_p(request.top_p)
                sampler.add_min_p(0.05)
                sampler.add_temp(request.temperature)
                sampler.add_dist(secrets.randbits(32))
            return sampler
        except BaseException:
            sampler.close()
            raise

    def decode(self, rows):
        batch = self.batch.batch
        batch.n_tokens = len(rows)
        for i, (sequence, position, token, logits) in enumerate(rows):
            batch.token[i] = token
            batch.pos[i] = position
            batch.n_seq_id[i] = 1
            batch.seq_id[i][0] = sequence
            batch.logits[i] = logits
        self.ctx.decode(self.batch)

    def sample(self, sampler, index):
        return sampler.sample(self.ctx, index)

    def piece(self, token, special=False):
        size = 256
        while True:
            buffer = ctypes.create_string_buffer(size)
            count = self.api.llama_token_to_piece(
                self.model.vocab, token, buffer, size, 0, special)
            if count >= 0:
                return buffer.raw[:count]
            size = -count

    def release(self, sequence):
        if not self.ctx.kv_cache_seq_rm(sequence, 0, -1):
            raise RuntimeError("Model cannot remove a finished sequence")

    def close(self):
        self.stack.close()
