"""Sample one CUDA batch before reading token IDs on the host."""

from transformer.enhanced.batch.backend import BatchBackend
from .graph import DecodeGraph


class GPUBatchBackend(BatchBackend):
    def __init__(self, settings):
        super().__init__(settings)
        self.graphs = {}

    def close(self):
        self.graphs.clear()
        super().close()

    def _can_graph(self, requests):
        return (self.settings.device == "cuda" and requests
                and all(request.temperature == 0 and request.ignore_eos
                        and not request.cancel.is_set() for request in requests)
                and max(len(request.prompt) for request in requests)
                + max(request.max_tokens for request in requests) <= self.settings.n_ctx)

    def _generate_graph(self, requests):
        torch = self.torch
        graph = self.graphs.get(len(requests))
        if graph is None:
            graph = self.graphs[len(requests)] = DecodeGraph(self, len(requests))
        tokens = [[] for _ in requests]
        reasons = ["stop"] * len(requests)
        streamers = [self._streamer(request.emit) if request.emit else None for request in requests]
        with torch.inference_mode():
            for step in range(max(request.max_tokens for request in requests)):
                sampled_host = (graph.prefill([request.prompt for request in requests])
                                if step == 0 else graph.replay())
                token_ids = sampled_host.tolist()
                for index, request in enumerate(requests):
                    if request.cancel.is_set() or len(tokens[index]) >= request.max_tokens:
                        continue
                    tokens[index].append(token_ids[index])
                    if streamers[index]:
                        streamers[index].put(sampled_host[index:index + 1])
                    if len(tokens[index]) == request.max_tokens:
                        reasons[index] = "length"
                if all(request.cancel.is_set() or len(tokens[index]) == request.max_tokens
                       for index, request in enumerate(requests)):
                    break
        results = []
        for index, request in enumerate(requests):
            if streamers[index]:
                streamers[index].end()
            results.append(self._result(request, tokens[index], reasons[index]))
        return results

    def _sample_batch(self, logits, requests, active):
        torch = self.torch
        first = requests[active[0]]
        uniform = all(
            (requests[index].temperature, requests[index].top_p, requests[index].ignore_eos)
            == (first.temperature, first.top_p, first.ignore_eos)
            for index in active
        )
        if uniform:
            scores = logits.float()
            if first.ignore_eos:
                scores[:, sorted(self.eos_tokens)] = -float("inf")
            if first.temperature == 0:
                return scores.argmax(dim=-1)
            scores = scores / first.temperature
            if first.top_p < 1:
                from transformers import TopPLogitsWarper
                scores = TopPLogitsWarper(first.top_p)(None, scores)
            return torch.multinomial(scores.softmax(dim=-1), 1).squeeze(-1)

        sampled = []
        for row, index in enumerate(active):
            request = requests[index]
            scores = self._processors(request)(None, logits[row].float().unsqueeze(0))
            sampled.append(scores.argmax().reshape(()) if request.temperature == 0 else
                           torch.multinomial(scores.softmax(dim=-1), 1).reshape(()))
        return torch.stack(sampled)

    def generate_batch(self, requests):
        torch = self.torch
        for request in requests:
            self._validate(request)
        if self._can_graph(requests):
            return self._generate_graph(requests)
        tokens = [[] for _ in requests]
        reasons = ["stop"] * len(requests)
        streamers = [self._streamer(request.emit) if request.emit else None for request in requests]
        active = [index for index, request in enumerate(requests) if not request.cancel.is_set()]
        with torch.inference_mode():
            if active:
                logits, cache, mask = self._prefill([requests[index].prompt for index in active])
            while active:
                sampled = self._sample_batch(logits, requests, active)
                # Streaming needs host token IDs. One transfer serves the entire batch.
                sampled_host = sampled.cpu()
                token_ids = sampled_host.tolist()
                remaining, rows = [], []
                for row, index in enumerate(active):
                    request = requests[index]
                    if request.cancel.is_set():
                        continue
                    token = token_ids[row]
                    if token in self.eos_tokens:
                        continue
                    tokens[index].append(token)
                    if streamers[index]:
                        streamers[index].put(sampled_host[row:row + 1])
                    if len(tokens[index]) == request.max_tokens:
                        reasons[index] = "length"
                        continue
                    remaining.append(index)
                    rows.append(row)
                if not remaining:
                    break
                if len(rows) != len(active):
                    indices = torch.tensor(rows, dtype=torch.long, device=self.settings.device)
                    cache.batch_select_indices(indices)
                    mask = mask.index_select(0, indices)
                    sampled = sampled.index_select(0, indices)
                mask = torch.cat((mask, torch.ones((len(rows), 1), dtype=mask.dtype,
                                                   device=self.settings.device)), dim=1)
                logits, cache = self._forward(sampled.unsqueeze(1), mask, cache)
                active = remaining
        results = []
        for index, request in enumerate(requests):
            if streamers[index]:
                streamers[index].end()
            results.append(self._result(request, tokens[index], reasons[index]))
        return results
