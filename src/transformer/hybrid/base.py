"""Serial Jamba baseline using Transformers generate and per-request dynamic state."""

from dataclasses import dataclass

from transformer.base.engine import EngineSettings as BaseSettings
from transformer.mamba.engine import TorchEngine as MambaEngine


@dataclass(frozen=True)
class EngineSettings(BaseSettings):
    mamba_kernels: str = "auto"

    def __post_init__(self):
        super().__post_init__()
        if self.mamba_kernels not in {"auto", "off", "required"}:
            raise ValueError("mamba_kernels must be auto, off or required")


class TorchEngine(MambaEngine):
    def _load_model(self, config):
        from transformers import JambaForCausalLM
        from transformers.models.jamba import modeling_jamba

        if config.model_type != "jamba" or set(config.layers_block_type) != {"mamba", "attention"}:
            raise ValueError("Hybrid engine requires a Jamba model with Mamba and attention layers")
        if self.settings.n_ctx > config.max_position_embeddings:
            raise ValueError("n_ctx exceeds the model context length")
        fast = self.settings.device == "cuda" and modeling_jamba.is_fast_path_available
        if self.settings.mamba_kernels == "required" and not fast:
            raise ValueError("Required Mamba CUDA kernels are unavailable")
        config.use_mamba_kernels = fast and self.settings.mamba_kernels != "off"
        self.kernel_backend = "mamba-cuda" if config.use_mamba_kernels else "pytorch"
        return JambaForCausalLM.from_pretrained(
            self.settings.model_path, config=config, local_files_only=True, trust_remote_code=False,
            use_safetensors=True, dtype=getattr(self.torch, self.settings.dtype),
            attn_implementation="sdpa",
        ).to(self.settings.device).eval()
