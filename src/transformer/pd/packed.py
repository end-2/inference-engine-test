"""Pack request tokens into one Llama forward with isolated causal attention."""

from .engine import PDEngine


class PackedEngine(PDEngine):
    def packed_forward(self, plans):
        from transformers import DynamicCache

        torch = self.torch
        device = self.settings.device
        lengths = [state.cache.get_seq_length() if state.cache is not None else 0 for state, _ in plans]
        counts = [len(ids) for _, ids in plans]
        past, total = sum(lengths), sum(counts)
        if not total or any(n < 1 for n in counts):
            raise ValueError("Packed queries must be nonempty")
        with torch.inference_mode():
            cache = DynamicCache(config=self.model.config)
            if past:
                for layer in range(self.model.config.num_hidden_layers):
                    keys = [state.cache.layers[layer].keys for (state, _), length in zip(plans, lengths) if length]
                    values = [state.cache.layers[layer].values for (state, _), length in zip(plans, lengths) if length]
                    cache.update(torch.cat(keys, dim=2), torch.cat(values, dim=2), layer)
            mask = torch.full((1, 1, total, past + total), torch.finfo(self.model.dtype).min,
                              dtype=self.model.dtype, device=device)
            old_offset = new_offset = 0
            positions, last = [], []
            for length, count in zip(lengths, counts):
                mask[:, :, new_offset:new_offset + count, old_offset:old_offset + length] = 0
                causal = torch.full((count, count), torch.finfo(self.model.dtype).min,
                                    dtype=self.model.dtype, device=device).triu(diagonal=1)
                mask[:, :, new_offset:new_offset + count, past + new_offset:past + new_offset + count] = causal
                positions.extend(range(length, length + count))
                old_offset += length
                new_offset += count
                last.append(new_offset - 1)
            ids = torch.tensor([[token for _, chunk in plans for token in chunk]], dtype=torch.long, device=device)
            output = self.model(input_ids=ids, attention_mask=mask,
                                position_ids=torch.tensor([positions], dtype=torch.long, device=device),
                                cache_position=torch.arange(past, past + total, device=device),
                                past_key_values=cache, use_cache=True,
                                logits_to_keep=torch.tensor(last, dtype=torch.long, device=device))
            old_offset = new_offset = 0
            for index, ((state, _), length, count) in enumerate(zip(plans, lengths, counts)):
                separate = DynamicCache(config=self.model.config)
                for layer, packed_layer in enumerate(output.past_key_values.layers):
                    def extract(tensor):
                        return torch.cat((tensor[:, :, old_offset:old_offset + length, :],
                                          tensor[:, :, past + new_offset:past + new_offset + count, :]), dim=2)
                    separate.update(extract(packed_layer.keys), extract(packed_layer.values), layer)
                state.cache = separate
                state.logits = output.logits[:, index, :].float().clone()
                old_offset += length
                new_offset += count
            self.synchronize()

    def sample_batch(self, rows):
        if not rows:
            return []
        scores = self.torch.cat([logits for logits, _ in rows], dim=0)
        for index, (_, ignore_eos) in enumerate(rows):
            if ignore_eos:
                scores[index, sorted(self.eos_tokens)] = -float("inf")
        return scores.argmax(dim=-1).cpu().tolist()
