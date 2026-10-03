"""Serve the serial Jamba baseline through the shared HTTP and SSE API."""

from dataclasses import dataclass

from huggingface.runtime import server
from .model import EngineSettings, TorchEngine


@dataclass(frozen=True)
class Settings(server.Settings):
    served_model_name: str = "jamba-hybrid"
    mamba_kernels: str = "auto"

    def engine_settings(self):
        return EngineSettings(**vars(super().engine_settings()), mamba_kernels=self.mamba_kernels)


def create_app(settings=None, engine_factory=TorchEngine):
    return server.create_app(settings or Settings(), engine_factory)


def main():
    parser = server.create_parser(__doc__)
    parser.set_defaults(served_model_name=Settings.served_model_name)
    parser.add_argument("--mamba-kernels", choices=("auto", "off", "required"), default="auto")
    server.run_server(parser, Settings, TorchEngine)
