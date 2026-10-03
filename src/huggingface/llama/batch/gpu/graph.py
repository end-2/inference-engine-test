"""Reuse one CUDA decode graph for each batch width."""


class DecodeGraph:
    def __init__(self, backend, batch_size):
        from transformers import StaticCache

        self.backend = backend
        self.torch = backend.torch
        torch = self.torch
        self.batch_size = batch_size
        self.capacity = backend.settings.n_ctx
        model = backend.model
        config = model.config
        self.cache = StaticCache(config=config, max_cache_len=self.capacity)
        self.cache.early_initialization(
            batch_size=batch_size, num_heads=config.num_key_value_heads,
            head_dim=backend.head_dim, dtype=model.dtype, device=model.device,
        )
        self.mask = torch.ones((batch_size, self.capacity), dtype=torch.long, device=model.device)
        self.ids = torch.zeros((batch_size, 1), dtype=torch.long, device=model.device)
        self.cache_position = torch.full((1,), self.capacity - 1, dtype=torch.long, device=model.device)
        self.position_ids = torch.full((batch_size, 1), self.capacity - 1,
                                       dtype=torch.long, device=model.device)
        self.eos = sorted(backend.eos_tokens)
        self.eos_indices = torch.tensor(self.eos, dtype=torch.long, device=model.device)
        self._capture()

    def _step(self):
        output = self.backend.model(
            input_ids=self.ids, attention_mask=self.mask, position_ids=self.position_ids,
            past_key_values=self.cache, cache_position=self.cache_position,
            use_cache=True, logits_to_keep=1,
        )
        scores = output.logits[:, -1, :].float()
        if self.eos:
            scores.index_fill_(1, self.eos_indices, -float("inf"))
        self.ids.copy_(scores.argmax(dim=-1, keepdim=True))
        self.cache_position.add_(1)
        self.position_ids.add_(1)

    def _capture(self):
        torch = self.torch
        with torch.inference_mode():
            stream = torch.cuda.Stream()
            stream.wait_stream(torch.cuda.current_stream())
            with torch.cuda.stream(stream):
                for _ in range(3):
                    self.cache_position.fill_(self.capacity - 1)
                    self.position_ids.fill_(self.capacity - 1)
                    self._step()
            torch.cuda.current_stream().wait_stream(stream)
            self.cache_position.fill_(self.capacity - 1)
            self.position_ids.fill_(self.capacity - 1)
            self.graph = torch.cuda.CUDAGraph()
            with torch.cuda.graph(self.graph):
                self._step()
            self.cache.reset()

    def prefill(self, prompts):
        torch = self.torch
        self.cache.reset()
        with self.backend.tokenizer_lock:
            inputs = self.backend.tokenizer.pad(
                {"input_ids": prompts}, padding=True, return_tensors="pt",
            )
        ids = inputs.input_ids.to(self.backend.settings.device)
        mask = inputs.attention_mask.to(self.backend.settings.device)
        length = ids.shape[1]
        self.mask.fill_(1)
        self.mask[:, :length].copy_(mask)
        position_ids = mask.long().cumsum(dim=-1) - 1
        position_ids.masked_fill_(mask == 0, 0)
        with torch.inference_mode():
            output = self.backend.model(
                input_ids=ids, attention_mask=self.mask, position_ids=position_ids,
                past_key_values=self.cache,
                cache_position=torch.arange(length, device=self.backend.settings.device),
                use_cache=True, logits_to_keep=1,
            )
            scores = output.logits[:, -1, :].float()
            if self.eos:
                scores.index_fill_(1, self.eos_indices, -float("inf"))
            self.ids.copy_(scores.argmax(dim=-1, keepdim=True))
            self.cache_position.fill_(length)
            self.position_ids.copy_(mask.sum(dim=-1).unsqueeze(1))
        return self.ids.squeeze(1).cpu()

    def replay(self):
        self.graph.replay()
        return self.ids.squeeze(1).cpu()
