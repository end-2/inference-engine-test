#!/usr/bin/env python3
"""Reproduce the CPU HPA scale-out-only experiment."""

from hpa_test.runner import main


if __name__ == "__main__":
    main("scale-out")
