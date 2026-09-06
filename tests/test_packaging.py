"""Cross-file invariants for extension packaging metadata."""

from __future__ import annotations

import shutil
import subprocess
import tomllib
import zipfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TOP_LEVEL = {
    "LICENSE",
    "__init__.py",
    "blender",
    "blender_manifest.toml",
    "data",
    "formats",
    "utils",
}
FORBIDDEN_PARTS = {
    ".github",
    ".private",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "LICENSES",
    "docs",
    "env",
    "htmlcov",
    "scripts",
    "tests",
    "venv",
}


def test_project_and_extension_versions_match() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    manifest = tomllib.loads(
        (ROOT / "blender_manifest.toml").read_text(encoding="utf-8")
    )

    assert project["project"]["version"] == manifest["version"]


def test_fallback_archive_contains_only_extension_files(tmp_path: Path) -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is required to exercise the extension builder")

    subprocess.run(
        [
            pwsh,
            "-NoProfile",
            "-File",
            str(ROOT / "scripts" / "build_extension.ps1"),
            "-OutputDir",
            str(tmp_path),
            "-BlenderExe",
            "",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    archives = list(tmp_path.glob("quakeblend-*.zip"))
    assert len(archives) == 1

    with zipfile.ZipFile(archives[0]) as archive:
        members = {
            name.replace("\\", "/").strip("/")
            for name in archive.namelist()
            if name.strip("/\\")
        }

    top_level = {name.split("/", 1)[0] for name in members}
    assert top_level == EXPECTED_TOP_LEVEL
    forbidden = sorted(
        name
        for name in members
        if FORBIDDEN_PARTS.intersection(name.split("/"))
        or name.endswith((".egg-info", ".pyc"))
        or "/__pycache__/" in f"/{name}/"
        or name in {".coverage", "README.md", "THIRD_PARTY_NOTICES.md"}
    )
    assert not forbidden
