"""Local Mamba inference with one recurrent state per request."""

import logging

from huggingface.runtime.engine import EngineSettings, SerialEngine
from huggingface.runtime.prompts import PlainTextPrompts


class TorchEngine(PlainTextPrompts, SerialEngine):
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
