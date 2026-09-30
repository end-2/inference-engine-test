"""Keep attention history and recurrent state at the same token boundary."""

from dataclasses import dataclass

import torch
from transformers.models.jamba.modeling_jamba import HybridMambaAttentionDynamicCache


@dataclass(frozen=True)
class HybridState:
    tokens: tuple[int, ...]
    tensors: dict[str, torch.Tensor]

    @property
    def size(self):
        return len(self.tokens) * 8 + sum(t.numel() * t.element_size() for t in self.tensors.values())

    def copy_to(self, device, *, pin_memory=False):
        tensors = {}
        for name, tensor in self.tensors.items():
            copy = tensor.detach().to(device=device, copy=True).contiguous()
            if pin_memory and copy.device.type == "cpu":
                copy = copy.pin_memory()
            tensors[name] = copy
        return HybridState(self.tokens, tensors)


class HybridBuffer(HybridMambaAttentionDynamicCache):
    """Reserve one batch workspace and reuse its KV, convolution and SSM storage."""

    def __init__(self, config, max_batch, capacity, dtype, device, *, fast_mamba=False):
        super().__init__(config, max_batch, dtype=dtype, device=device)
        self.config, self.max_batch, self.capacity = config, max_batch, capacity
        self.device = torch.device(device)
        self.storage = {}
        for index, kind in enumerate(self.layers_block_type):
            if kind == "attention":
                shape = (max_batch, config.num_key_value_heads, capacity,
                         config.hidden_size // config.num_attention_heads)
                for name in ("key", "value"):
                    self.storage[f"{index}.{name}"] = torch.empty(shape, dtype=dtype, device=device)
            else:
                self.storage[f"{index}.conv"] = self.conv_states[index]
                # The PyTorch recurrence accumulates in float32, even with half weights.
                self.storage[f"{index}.ssm"] = self.ssm_states[index].to(
                    dtype=dtype if fast_mamba else torch.float32)
        self.reset(1)

    @property
    def size(self):
        return sum(t.numel() * t.element_size() for t in self.storage.values())

    def _bind(self):
        for index, kind in enumerate(self.layers_block_type):
            if kind == "attention":
                length = self.lengths[index]
                self.key_cache[index] = self.storage[f"{index}.key"][:self.batch_size, :, :length]
                self.value_cache[index] = self.storage[f"{index}.value"][:self.batch_size, :, :length]
            else:
                self.conv_states[index] = self.storage[f"{index}.conv"][:self.batch_size]
                self.ssm_states[index] = self.storage[f"{index}.ssm"][:self.batch_size]

    def reset(self, batch_size):
        if not 1 <= batch_size <= self.max_batch:
            raise ValueError("Batch exceeds hybrid buffer capacity")
        self.batch_size = batch_size
        self.lengths = [0] * len(self.layers_block_type)
        self.has_previous_state = False
        for name, tensor in self.storage.items():
            if name.endswith((".conv", ".ssm")):
                tensor[:batch_size].zero_()
        self._bind()

    def update(self, key_states, value_states, layer_idx, cache_kwargs=None):
        start = self.lengths[layer_idx]
        end = start + key_states.shape[2]
        if end > self.capacity:
            raise ValueError("KV history exceeds hybrid buffer capacity")
        self.storage[f"{layer_idx}.key"][:self.batch_size, :, start:end].copy_(key_states)
        self.storage[f"{layer_idx}.value"][:self.batch_size, :, start:end].copy_(value_states)
        self.lengths[layer_idx] = end
        self.key_cache[layer_idx] = self.storage[f"{layer_idx}.key"][:self.batch_size, :, :end]
        self.value_cache[layer_idx] = self.storage[f"{layer_idx}.value"][:self.batch_size, :, :end]
        return self.key_cache[layer_idx], self.value_cache[layer_idx]

    def get_seq_length(self, layer_idx=0):
        if layer_idx not in self.transformer_layers:
            layer_idx = self.transformer_layers[0]
        return self.lengths[layer_idx]

    def commit_mamba(self):
        # Jamba's fallback replaces tensors; move results back into the reusable buffer.
        for index, kind in enumerate(self.layers_block_type):
            if kind == "mamba":
                for name, states in (("conv", self.conv_states), ("ssm", self.ssm_states)):
                    target = self.storage[f"{index}.{name}"][:self.batch_size]
                    if states[index].data_ptr() != target.data_ptr():
                        target.copy_(states[index])
        self._bind()

    def snapshot(self, row, tokens):
        tokens = tuple(tokens)
        tensors = {}
        length = self.get_seq_length()
        if len(tokens) != length:
            raise ValueError("Mamba state must be captured at the evaluated prefix boundary")
        for name, tensor in self.storage.items():
            value = tensor[row:row + 1]
            if name.endswith((".key", ".value")):
                value = value[:, :, length - len(tokens):length]
            tensors[name] = value.clone().contiguous()
        return HybridState(tokens, tensors)

    def validate(self, state):
        if set(state.tensors) != set(self.storage) or len(state.tokens) > self.capacity:
            raise ValueError("Invalid hybrid checkpoint keys or length")
        for name, tensor in state.tensors.items():
            shape = list(self.storage[name].shape)
            shape[0] = 1
            if name.endswith((".key", ".value")):
                shape[2] = len(state.tokens)
            if tuple(tensor.shape) != tuple(shape) or tensor.dtype != self.storage[name].dtype:
                raise ValueError(f"Invalid hybrid checkpoint tensor: {name}")

    def load(self, states):
        for state in states:
            self.validate(state)
        self.reset(len(states))
        width = max(len(state.tokens) for state in states)
        mask = torch.zeros((len(states), width), dtype=torch.long, device=self.device)
        for name, target in self.storage.items():
            if name.endswith((".key", ".value")):
                target[:len(states), :, :width].zero_()
        for row, state in enumerate(states):
            start = width - len(state.tokens)
            mask[row, start:] = 1
            for name, tensor in state.tensors.items():
                target = self.storage[name][row:row + 1]
                if name.endswith((".key", ".value")):
                    target = target[:, :, start:width]
                target.copy_(tensor, non_blocking=tensor.is_pinned())
        for index in self.transformer_layers:
            self.lengths[index] = width
        self.has_previous_state = width > 0
        self._bind()
        return mask

    def select(self, rows):
        indices = torch.tensor(rows, dtype=torch.long, device=self.device)
        for name, tensor in self.storage.items():
            target = tensor
            if name.endswith((".key", ".value")):
                target = tensor[:, :, :self.get_seq_length()]
            target[:len(rows)].copy_(target[:self.batch_size].index_select(0, indices))
        self.batch_size = len(rows)
        self._bind()
