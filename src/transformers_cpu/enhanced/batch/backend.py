"""Decode heterogeneous batches and remove finished rows between model calls."""

from transformers_cpu.base.engine import TorchEngine


class BatchBackend(TorchEngine):
    def _forward(self, ids, mask, cache=None):
        past = cache.get_seq_length() if cache is not None else 0
        inputs = self.model.prepare_inputs_for_generation(
            ids, attention_mask=mask, past_key_values=cache,
            cache_position=self.torch.arange(past, past + ids.shape[1]),
            use_cache=True, logits_to_keep=1,
        )
        output = self.model(**inputs)
        return output.logits[:, -1, :], output.past_key_values

    def _prefill(self, prompts):
        with self.tokenizer_lock:
            inputs = self.tokenizer.pad({"input_ids": prompts}, padding=True, return_tensors="pt")
        logits, cache = self._forward(inputs.input_ids, inputs.attention_mask)
        return logits, cache, inputs.attention_mask

    def _processors(self, request):
        from transformers import (LogitsProcessorList, SuppressTokensLogitsProcessor,
                                  TemperatureLogitsWarper, TopPLogitsWarper)

        processors = LogitsProcessorList()
        if request.ignore_eos:
            processors.append(SuppressTokensLogitsProcessor(sorted(self.eos_tokens), device="cpu"))
        if request.temperature > 0:
            processors.append(TemperatureLogitsWarper(float(request.temperature)))
            if request.top_p < 1:
                processors.append(TopPLogitsWarper(request.top_p))
        return processors

    def _sample(self, logits, request, processors):
        scores = processors(None, logits.float().unsqueeze(0))
        if request.temperature == 0:
            return int(scores.argmax())
        return int(self.torch.multinomial(scores.softmax(-1), 1))

    def generate_batch(self, requests):
        torch = self.torch
        for request in requests:
            self._validate(request)
        processors = [self._processors(request) for request in requests]
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
                    token = self._sample(logits[row], request, processors[index])
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
            results.append(self._result(request, tokens[index], reasons[index]))
        return results

