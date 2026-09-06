"""Public repository documentation and publication invariants."""

from __future__ import annotations

from pathlib import Path
import re
from urllib.parse import unquote

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_FILES = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
LINK_PATTERN = re.compile(r"!?\[[^]]*]\(([^)]+)\)")
PUBLIC_TEXT_ROOTS = [ROOT / ".github", ROOT / "docs", ROOT / "quakeblend", ROOT / "scripts", ROOT / "tests"]
PUBLIC_TEXT_SUFFIXES = {".gitignore", ".json", ".md", ".ps1", ".py", ".toml", ".yaml", ".yml"}
FORBIDDEN_PUBLIC_TEXT = (
    "kenn" + "pet",
    "C:" + "\\Users\\",
    "file" + "://",
    "vscode" + "://",
    "QB_TEST_" + "Q2_MAP",
    "QB_TEST_" + "Q3_ROOT",
    "Outer" + " Base",
    "Arena" + " Gate",
    "q3" + "dm1",
    "q2-" + "outer-base",
    "q3-" + "shader-status",
    "editable-" + "geometry-feasibility",
    "blender_" + "private_q",
)
REMOVED_PUBLIC_PATHS = (
    ROOT / "THIRD_PARTY_NOTICES.md",
    ROOT / "LICENSES" / "librequake",
    ROOT / "docs" / "images" / "librequake-e3m4.png",
    ROOT / "scripts" / "blender_publication_hero.py",
)


def test_public_markdown_links_resolve() -> None:
    failures = []
    for document in MARKDOWN_FILES:
        text = document.read_text(encoding="utf-8")
        for raw_target in LINK_PATTERN.findall(text):
            target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
            if not target or target.startswith("#") or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
                continue
            relative = unquote(target.split("#", 1)[0])
            resolved = (document.parent / relative).resolve()
            if not resolved.is_relative_to(ROOT) or not resolved.exists():
                failures.append(f"{document.relative_to(ROOT)} -> {target}")
    assert not failures, failures


def test_public_text_has_no_private_fixture_or_home_path_references() -> None:
    files = [ROOT / ".gitignore", ROOT / "README.md", ROOT / "pyproject.toml"]
    for directory in PUBLIC_TEXT_ROOTS:
        files.extend(
            path
            for path in directory.rglob("*")
            if path.is_file() and path.suffix in PUBLIC_TEXT_SUFFIXES
        )
    failures = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_PUBLIC_TEXT:
            if forbidden.casefold() in text.casefold():
                failures.append(f"{path.relative_to(ROOT)}: {forbidden}")
    assert not failures, failures


def test_documentation_images_are_metadata_free() -> None:
    expected = {
        ROOT / "docs/images/q3-bsp-import.png": (1280, 720),
        ROOT / "docs/images/import-options.png": (1600, 900),
    }
    for path, dimensions in expected.items():
        with Image.open(path) as image:
            image.load()
            assert image.size == dimensions
            assert image.mode == "RGB"
            assert not image.info
            extrema = image.getextrema()
            assert any(low != high for low, high in extrema)


def test_test_only_librequake_media_and_notices_are_not_redistributed() -> None:
    present = [str(path.relative_to(ROOT)) for path in REMOVED_PUBLIC_PATHS if path.exists()]
    assert not present, present
