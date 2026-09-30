"""Local Mamba inference with one recurrent state per request."""

import logging

from transformer.base.engine import EngineSettings, TorchEngine as BaseEngine


class TorchEngine(BaseEngine):
    def _load_model(self, config):
        from transformers import MambaForCausalLM
        from transformers.models.mamba import modeling_mamba

        if config.model_type != "mamba":
            raise ValueError("Mamba requires model_type=mamba")
        model = MambaForCausalLM.from_pretrained(
            self.settings.model_path, config=config, local_files_only=True,
            use_safetensors=True, dtype=getattr(self.torch, self.settings.dtype),
        ).to(self.settings.device).eval()
        conv_update, conv_forward = modeling_mamba._lazy_load_causal_conv1d()
        fast = self.settings.device == "cuda" and all((
            modeling_mamba.selective_state_update, modeling_mamba.selective_scan_fn,
            modeling_mamba.mamba_inner_fn, conv_update, conv_forward,
        ))
        self.kernel_backend = "mamba-cuda" if fast else "pytorch"
        logging.info("Mamba kernel backend: %s; device=%s", self.kernel_backend, self.settings.device)
        return model

    def prepare_prompt(self, messages):
        if self.tokenizer.chat_template:
            return super().prepare_prompt(messages)
        # The base checkpoint has no chat template. A single user message is raw text.
        if len(messages) == 1 and messages[0]["role"] == "user":
            text = messages[0]["content"]
        else:
            text = "\n".join(f"{message['role'].capitalize()}: {message['content']}"
                             for message in messages) + "\nAssistant:"
        with self.tokenizer_lock:
            return self.tokenizer.encode(text, add_special_tokens=False)
