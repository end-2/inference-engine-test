"""Serve CUDA inference with batch-wide token sampling."""

from dataclasses import dataclass

from huggingface.llama import serving as server
from huggingface.llama.batch.server import Settings as BatchSettings

from .engine import EngineSettings, TorchEngine


@dataclass(frozen=True)
class Settings(BatchSettings):
    device: str = "cuda"

    def engine_settings(self):
        return EngineSettings(**vars(super().engine_settings()))


def create_parser():
    parser = server.create_parser(__doc__)
    parser.add_argument("--max-parallel", type=server.api.positive_int, default=4)
    parser.add_argument("--batch-wait-ms", type=float, default=5)
    parser.set_defaults(device="cuda")
    return parser


def main():
    server.run_server(create_parser(), Settings, TorchEngine)


if __name__ == "__main__":
    main()
