"""Serve local models with queued CPU batching."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from transformers_cpu.base import server
from .engine import EngineSettings, TorchEngine


@dataclass(frozen=True)
class Settings(server.Settings):
    max_parallel: int = 4
    batch_wait_ms: float = 5

    def engine_settings(self):
        return EngineSettings(**vars(super().engine_settings()),
                              max_parallel=self.max_parallel, batch_wait_ms=self.batch_wait_ms)

    def create_executor(self):
        return ThreadPoolExecutor(max_workers=2 * self.max_parallel + 1,
                                  thread_name_prefix="torch-batch-client")


def create_app(settings=None, engine_factory=TorchEngine):
    return server.create_app(settings or Settings(), engine_factory)


def main():
    parser = server.create_parser(__doc__)
    parser.add_argument("--max-parallel", type=server.api.positive_int, default=4)
    parser.add_argument("--batch-wait-ms", type=float, default=5)
    server.run_server(parser, Settings, TorchEngine)


if __name__ == "__main__":
    main()
