"""Serve local Mamba weights through the shared chat API."""

from dataclasses import dataclass
import logging

from transformer.base import server
from .engine import TorchEngine


@dataclass(frozen=True)
class Settings(server.Settings):
    served_model_name: str = "state-spaces/mamba-130m-hf"


def create_app(settings=None, engine_factory=TorchEngine):
    return server.create_app(settings or Settings(), engine_factory)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = server.create_parser(__doc__)
    parser.set_defaults(served_model_name=Settings.served_model_name)
    server.run_server(parser, Settings, TorchEngine)


if __name__ == "__main__":
    main()
