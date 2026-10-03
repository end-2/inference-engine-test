"""Sample one CUDA batch before reading token IDs on the host."""

from huggingface.llama.batch.backend import BatchBackend
from .graph import DecodeGraph


class GPUBatchBackend(BatchBackend):
    def __init__(self, settings):
        self.cuda_graph = getattr(settings, "cuda_graph", "auto")
        if self.cuda_graph not in {"auto", "off", "required"}:
            raise ValueError("cuda_graph must be auto, off or required")
        super().__init__(settings)
        self.graphs = {}
        self.completed_batches = {"eager": 0, "cuda_graph": 0}
        self.completed_requests = {"eager": 0, "cuda_graph": 0}

    def runtime_info(self):
        return {"cuda_graph": self.cuda_graph,
                "completed_batches": dict(self.completed_batches),
                "completed_requests": dict(self.completed_requests)}

    def close(self):
        self.graphs.clear()
        super().close()

    def _can_graph(self, requests):
        return (self.settings.device == "cuda" and requests
                and all(request.temperature == 0 and request.ignore_eos
                        and (self.cuda_graph == "required" or not request.cancel.is_set()) for request in requests)
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

    def generate_batch(self, requests):
        for request in requests:
            self._validate(request)
        use_graph = self.cuda_graph != "off" and self._can_graph(requests)
        if self.cuda_graph == "required" and not use_graph:
            raise ValueError("CUDA Graph requires greedy requests with ignore_eos=true that fit n_ctx")
        results = self._generate_graph(requests) if use_graph else self._generate_eager(requests)
        path = "cuda_graph" if use_graph else "eager"
        self.completed_batches[path] += 1
        self.completed_requests[path] += len(requests)
        return results

    def _generate_eager(self, requests):
        torch = self.torch
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
