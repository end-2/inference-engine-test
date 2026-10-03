"""Common serving settings and CLI for Hugging Face engines."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from inference import api

from .engine import EngineSettings
from .batching import EngineSettings as BatchEngineSettings


@dataclass(frozen=True)
class Settings:
    model: Path = Path("/model")
    served_model_name: str = "local-model"
    n_ctx: int = 1024
    n_threads: int = 4
    dtype: str | None = None
    device: str = "cpu"
    max_input_tokens: int = 768
    max_output_tokens: int = 128
    default_output_tokens: int = 32

    def __post_init__(self):
        if min(self.max_input_tokens, self.max_output_tokens, self.default_output_tokens) < 1:
            raise ValueError("Token limits must be positive")
        if self.default_output_tokens > self.max_output_tokens:
            raise ValueError("default_output_tokens must not exceed max_output_tokens")
        self.engine_settings()

    def engine_settings(self):
        return EngineSettings(model_path=self.model, n_ctx=self.n_ctx,
                              n_threads=self.n_threads, dtype=self.dtype, device=self.device)

    def create_executor(self):
        return ThreadPoolExecutor(max_workers=1, thread_name_prefix="torch")


def create_app(settings, engine_factory):
    return api.create_app(settings, engine_factory,
                          title=f"Transformers {settings.device.upper()} inference API")


def create_parser(description=__doc__):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--model", type=Path, default=Path("/model"))
    parser.add_argument("--served-model-name", default=Settings.served_model_name)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=api.positive_int, default=8000)
    parser.add_argument("--n-ctx", type=api.positive_int, default=1024)
    parser.add_argument("--n-threads", type=api.positive_int, default=4)
    parser.add_argument("--dtype", choices=("float32", "bfloat16", "float16"))
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--max-input-tokens", type=api.positive_int, default=768)
    parser.add_argument("--max-output-tokens", type=api.positive_int, default=128)
    parser.add_argument("--default-output-tokens", type=api.positive_int, default=32)
    return parser


def run_server(parser, settings_type, engine_factory):
    options = vars(parser.parse_args())
    host, port = options.pop("host"), options.pop("port")
    try:
        settings = settings_type(**options)
    except ValueError as exc:
        parser.error(str(exc))
    import uvicorn

    uvicorn.run(create_app(settings, engine_factory), host=host, port=port, workers=1)


@dataclass(frozen=True)
class BatchSettings(Settings):
    max_parallel: int = 4
    batch_wait_ms: float = 5

    def engine_settings(self):
        return BatchEngineSettings(**vars(super().engine_settings()),
                              max_parallel=self.max_parallel, batch_wait_ms=self.batch_wait_ms)

    def create_executor(self):
        return ThreadPoolExecutor(max_workers=2 * self.max_parallel + 1,
                                  thread_name_prefix="torch-batch-client")
