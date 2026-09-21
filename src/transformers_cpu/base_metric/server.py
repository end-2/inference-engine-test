"""Serve the Transformers CPU chat API with request and generation metrics at /metrics."""

from inference_metrics import create_instrumented_app
from transformers_cpu.base.engine import TorchEngine
from transformers_cpu.base.server import Settings, create_app as create_base_app, create_parser


def create_app(settings=None, engine_factory=TorchEngine):
    return create_instrumented_app(create_base_app, settings, engine_factory, "transformers")


def main():
    parser = create_parser(__doc__)
    options = vars(parser.parse_args())
    host, port = options.pop("host"), options.pop("port")
    try:
        settings = Settings(**options)
    except ValueError as exc:
        parser.error(str(exc))
    import uvicorn

    uvicorn.run(create_app(settings), host=host, port=port, workers=1)


if __name__ == "__main__":
    main()
