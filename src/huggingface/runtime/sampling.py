"""Token sampling shared by padded Llama batches and Jamba hybrid batches."""


class Sampling:
    def _processors(self, request):
        from transformers import (LogitsProcessorList, SuppressTokensLogitsProcessor,
                                  TemperatureLogitsWarper, TopPLogitsWarper)

        processors = LogitsProcessorList()
        if request.ignore_eos:
            processors.append(SuppressTokensLogitsProcessor(sorted(self.eos_tokens), device=self.settings.device))
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
