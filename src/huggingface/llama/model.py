"""Load Llama-family checkpoints for serial, batch and distributed inference."""

from huggingface.runtime.engine import EngineSettings, SerialEngine


class TorchEngine(SerialEngine):
    def _load_model(self, config):
        from transformers import LlamaForCausalLM

        if config.model_type != "llama":
            raise ValueError("SmolLM2 requires a Llama model configuration")
        if self.settings.n_ctx > config.max_position_embeddings:
            raise ValueError("n_ctx exceeds the model context length")
        self.head_dim = config.hidden_size // config.num_attention_heads
        return LlamaForCausalLM.from_pretrained(
            self.settings.model_path, config=config, local_files_only=True,
            use_safetensors=True, dtype=getattr(self.torch, self.settings.dtype),
            attn_implementation="sdpa",
        ).to(self.settings.device).eval()
