#!/usr/bin/env python3
"""Run the CPU HPA scale-out and scale-in scenario."""

from hpa_test.runner import main


if __name__ == "__main__":
    main("scale-out-in")
