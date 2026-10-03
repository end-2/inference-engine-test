"""Llama model defaults for the shared serving runtime."""

from dataclasses import dataclass

from inference import api
from huggingface.runtime import server
from .model import TorchEngine


@dataclass(frozen=True)
class Settings(server.Settings):
    served_model_name: str = "HuggingFaceTB/SmolLM2-135M-Instruct"


def create_app(settings=None, engine_factory=TorchEngine):
    return server.create_app(settings or Settings(), engine_factory)


def create_parser(description=__doc__):
    parser = server.create_parser(description)
    parser.set_defaults(served_model_name=Settings.served_model_name)
    return parser


def run_server(parser, settings_type=Settings, engine_factory=TorchEngine):
    server.run_server(parser, settings_type, engine_factory)


def main():
    run_server(create_parser())
