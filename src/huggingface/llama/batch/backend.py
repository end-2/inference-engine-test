"""Decode heterogeneous batches and remove finished rows between model calls."""

from huggingface.runtime.sampling import Sampling
from ..model import TorchEngine


class BatchBackend(Sampling, TorchEngine):
    def _forward(self, ids, mask, cache=None):
        past = cache.get_seq_length() if cache is not None else 0
        inputs = self.model.prepare_inputs_for_generation(
            ids, attention_mask=mask, past_key_values=cache,
            cache_position=self.torch.arange(past, past + ids.shape[1], device=self.settings.device),
            use_cache=True, logits_to_keep=1,
        )
        output = self.model(**inputs)
        return output.logits[:, -1, :], output.past_key_values

    def _prefill(self, prompts):
        with self.tokenizer_lock:
            inputs = self.tokenizer.pad({"input_ids": prompts}, padding=True, return_tensors="pt")
        ids = inputs.input_ids.to(self.settings.device)
        mask = inputs.attention_mask.to(self.settings.device)
        logits, cache = self._forward(ids, mask)
        return logits, cache, mask

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
                        streamers[index].put(torch.tensor([token], device=self.settings.device))
                    if len(tokens[index]) == request.max_tokens:
                        reasons[index] = "length"
                        continue
                    remaining.append(index)
                    rows.append(row)
                    next_tokens.append([token])
                if not remaining:
                    break
                if len(rows) != len(active):
                    indices = torch.tensor(rows, dtype=torch.long, device=self.settings.device)
                    cache.batch_select_indices(indices)
                    mask = mask.index_select(0, indices)
                mask = torch.cat((mask, torch.ones((len(rows), 1), dtype=mask.dtype,
                                                   device=self.settings.device)), dim=1)
                logits, cache = self._forward(torch.tensor(next_tokens, device=self.settings.device), mask, cache)
                active = remaining
        results = []
        for index, request in enumerate(requests):
            if streamers[index]:
                streamers[index].end()
            results.append(self._result(request, tokens[index], reasons[index]))
        return results
