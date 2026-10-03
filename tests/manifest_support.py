"""Render repository Helm profiles for manifest contract tests."""

from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def render(profile, *options):
    import yaml

    output = subprocess.check_output(
        [str(ROOT / "scripts/render-k8s.sh"), str(profile), *options], text=True
    )
    return list(yaml.safe_load_all(output))
