"""Cross-file invariants for extension packaging metadata."""

from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_project_and_extension_versions_match() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    manifest = tomllib.loads(
        (ROOT / "blender_manifest.toml").read_text(encoding="utf-8")
    )

    assert project["project"]["version"] == manifest["version"]