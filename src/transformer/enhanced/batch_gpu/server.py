"""Serve CUDA inference with batch-wide token sampling."""

from dataclasses import dataclass

from transformer.base import server
from transformer.enhanced.batch.engine import TorchEngine as BatchEngine
from transformer.enhanced.batch.server import Settings as BatchSettings

from .backend import GPUBatchBackend


@dataclass(frozen=True)
class Settings(BatchSettings):
    device: str = "cuda"

    def __post_init__(self):
        super().__post_init__()
        if self.device != "cuda":
            raise ValueError("GPU batch requires device=cuda")


class TorchEngine(BatchEngine):
    def __init__(self, settings, backend_factory=GPUBatchBackend):
        if settings.device != "cuda":
            raise ValueError("GPU batch requires device=cuda")
        super().__init__(settings, backend_factory=backend_factory)


def main():
    parser = server.create_parser(__doc__)
    parser.add_argument("--max-parallel", type=server.api.positive_int, default=4)
    parser.add_argument("--batch-wait-ms", type=float, default=5)
    parser.set_defaults(device="cuda")
    server.run_server(parser, Settings, TorchEngine)


if __name__ == "__main__":
    main()
