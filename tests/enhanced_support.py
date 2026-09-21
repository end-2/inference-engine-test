"""Import image packages from the shared source root."""

import importlib
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def load_variant(variant, module="engine"):
    name = variant.removesuffix("-llamacpp")
    package = "llamacpp.base" if name == "base" else name.replace("enhanced-", "llamacpp.enhanced.")
    return importlib.import_module(f"{package}.{module}")
