"""Serve local SmolLM2 weights on CPU through the shared chat API."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from llamacpp.base import server as api

from .engine import EngineSettings, TorchEngine


@dataclass(frozen=True)
class Settings:
    model: Path = Path("/model")
    served_model_name: str = "HuggingFaceTB/SmolLM2-135M-Instruct"
    n_ctx: int = 1024
    n_threads: int = 4
    dtype: str = "float32"
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
                              n_threads=self.n_threads, dtype=self.dtype)

    def create_executor(self):
        return ThreadPoolExecutor(max_workers=1, thread_name_prefix="torch")


def create_app(settings=None, engine_factory=TorchEngine):
    app = api.create_app(settings or Settings(), engine_factory)
    app.title = "Transformers CPU inference API"
    return app


def create_parser(description=__doc__):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--model", type=Path, default=Path("/model"))
    parser.add_argument("--served-model-name", default=Settings.served_model_name)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=api.positive_int, default=8000)
    parser.add_argument("--n-ctx", type=api.positive_int, default=1024)
    parser.add_argument("--n-threads", type=api.positive_int, default=4)
    parser.add_argument("--dtype", choices=("float32", "bfloat16"), default="float32")
    parser.add_argument("--max-input-tokens", type=api.positive_int, default=768)
    parser.add_argument("--max-output-tokens", type=api.positive_int, default=128)
    parser.add_argument("--default-output-tokens", type=api.positive_int, default=32)
    return parser


def run_server(parser, settings_type=Settings, engine_factory=TorchEngine):
    options = vars(parser.parse_args())
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
