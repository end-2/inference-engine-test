"""Serve the serial llama baseline."""

from ..serving import Settings, create_app, main
from ..serving import create_parser, run_server


if __name__ == "__main__":
    main()
