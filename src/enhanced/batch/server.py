"""Serve the shared chat API with continuous batching and chunked prefill."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from base import server

from .engine import EngineSettings, LlamaEngine


@dataclass(frozen=True)
class Settings(server.Settings):
    n_threads_batch: int | None = None
    n_ubatch: int = 512
    max_parallel: int = 8
    prefill_chunk: int = 64

    def engine_settings(self):
        return EngineSettings(
            **vars(super().engine_settings()),
            n_threads_batch=self.n_threads_batch, n_ubatch=self.n_ubatch,
            max_parallel=self.max_parallel, prefill_chunk=self.prefill_chunk,
        )

    def create_executor(self):
        # HTTP threads wait for the scheduler; its owner alone accesses the model.
        return ThreadPoolExecutor(max_workers=2 * self.max_parallel + 1,
                                  thread_name_prefix="batch-client")


def create_app(settings=None, engine_factory=LlamaEngine):
    return server.create_app(settings or Settings(), engine_factory)


def main():
    parser = server.create_parser(__doc__)
    parser.add_argument("--n-threads-batch", type=server.positive_int)
    parser.add_argument("--n-ubatch", type=server.positive_int, default=512)
    parser.add_argument("--max-parallel", type=server.positive_int, default=8)
    parser.add_argument("--prefill-chunk", type=server.positive_int, default=64)
    server.run_server(parser, Settings, LlamaEngine)


if __name__ == "__main__":
    main()
