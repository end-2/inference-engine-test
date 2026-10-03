"""Serve local models with queued CPU batching."""

from dataclasses import dataclass

from huggingface.llama import serving as server
from huggingface.runtime.server import BatchSettings
from .engine import TorchEngine


@dataclass(frozen=True)
class Settings(BatchSettings):
    served_model_name: str = server.Settings.served_model_name


def create_app(settings=None, engine_factory=TorchEngine):
    return server.create_app(settings or Settings(), engine_factory)


def main():
    parser = server.create_parser(__doc__)
    parser.add_argument("--max-parallel", type=server.api.positive_int, default=4)
    parser.add_argument("--batch-wait-ms", type=float, default=5)
    server.run_server(parser, Settings, TorchEngine)


if __name__ == "__main__":
    main()
