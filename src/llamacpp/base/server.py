"""Serve a local GGUF model through the shared chat API."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from inference import api
from inference.api import positive_int
from .engine import EngineSettings, LlamaEngine


@dataclass(frozen=True)
class Settings:
    model: Path = Path("/model/model.gguf")
    served_model_name: str = "Qwen/Qwen2.5-0.5B-Instruct"
    n_ctx: int = 1024
    n_batch: int = 512
    n_threads: int = 4
    n_gpu_layers: int = 0
    max_input_tokens: int = 768
    max_output_tokens: int = 128
    default_output_tokens: int = 32

    def __post_init__(self):
        for name in ("n_ctx", "n_batch", "n_threads", "max_input_tokens",
                     "max_output_tokens", "default_output_tokens"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be greater than zero")
        if self.default_output_tokens > self.max_output_tokens:
            raise ValueError("default_output_tokens must not exceed max_output_tokens")
        if self.n_gpu_layers < -1:
            raise ValueError("n_gpu_layers must be -1 or greater")
        self.engine_settings()

    def engine_settings(self):
        return EngineSettings(
            model_path=self.model, n_ctx=self.n_ctx,
            n_batch=self.n_batch, n_threads=self.n_threads, n_gpu_layers=self.n_gpu_layers,
        )

    def create_executor(self):
        # Cancellation does not stop a native worker; serialize until it exits.
        return ThreadPoolExecutor(max_workers=1, thread_name_prefix="llama")


def create_app(settings=None, engine_factory=LlamaEngine):
    settings = settings or Settings()
    device = "GPU" if settings.n_gpu_layers else "CPU"
    return api.create_app(settings, engine_factory, title=f"llama.cpp {device} inference API")


def create_parser(description=__doc__):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--model", type=Path, default=Path("/model/model.gguf"))
    parser.add_argument("--served-model-name", default="Qwen/Qwen2.5-0.5B-Instruct")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=positive_int, default=8000)
    parser.add_argument("--n-ctx", type=positive_int, default=2048)
    parser.add_argument("--n-batch", type=positive_int, default=512)
    parser.add_argument("--n-threads", type=positive_int, default=4)
    parser.add_argument("--n-gpu-layers", type=int, default=0)
    parser.add_argument("--max-input-tokens", type=positive_int, default=2048)
    parser.add_argument("--max-output-tokens", type=positive_int, default=1024)
    parser.add_argument("--default-output-tokens", type=positive_int, default=128)
    return parser


def run_server(parser, settings_type=Settings, engine_factory=LlamaEngine):
    args = parser.parse_args()
    options = vars(args).copy()
    host, port = options.pop("host"), options.pop("port")
    try:
        settings = settings_type(**options)
    except ValueError as exc:
        parser.error(str(exc))
    import uvicorn

    uvicorn.run(create_app(settings, engine_factory), host=host, port=port, workers=1)


def main():
    run_server(create_parser())


if __name__ == "__main__":
    main()
