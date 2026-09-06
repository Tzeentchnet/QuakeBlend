"""Offline manifest checks and opt-in tests against pinned public source maps."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path, PurePosixPath

import pytest

from quakeblend.formats import map_q1


MANIFEST = json.loads(
    (Path(__file__).parent / "assets" / "manifest.json").read_text(encoding="utf-8")
)


def test_asset_manifest() -> None:
    assert MANIFEST["schema_version"] == 1
    assets = MANIFEST["assets"]
    assert assets
    assert len({asset["id"] for asset in assets}) == len(assets)
    assert len({asset["cache_directory"] for asset in assets}) == len(assets)
    for asset in assets:
        assert re.fullmatch(r"[a-z0-9-]+", asset["cache_directory"])
        assert re.fullmatch(r"[0-9a-f]{40}", asset["revision"])
        assert asset["source_base_url"].startswith(
            "https://raw.githubusercontent.com/ericwa/ericw-tools/"
            + asset["revision"] + "/"
        )
        assert asset["source_base_url"].endswith("/")
        assert asset["qualification"] == "source-parser-only"
        assert asset["format"] == "q1-valve220-map"
        paths = {entry["path"] for entry in asset["files"]}
        assert len(paths) == len(asset["files"])
        assert {asset["map_path"], "docs/COPYING", "docs/CREDITS",
                "docs/README-IMPORTANT-LICENCE-INFO"} <= paths
        for entry in asset["files"]:
            path = PurePosixPath(entry["path"])
            assert not path.is_absolute()
            assert ".." not in path.parts
            assert re.fullmatch(r"[A-Za-z0-9_./-]+", entry["path"])
            assert isinstance(entry["bytes"], int) and entry["bytes"] > 0
            assert re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])


@pytest.mark.parametrize("asset", MANIFEST["assets"], ids=lambda asset: asset["id"])
def test_public_source_map(asset: dict) -> None:
    cache = os.environ.get("QB_TEST_ASSET_ROOT")
    if not cache:
        pytest.skip("Set QB_TEST_ASSET_ROOT to opt into external asset validation")
    root = (Path(cache) / asset["cache_directory"]).resolve()
    for entry in asset["files"]:
        path = (root / entry["path"]).resolve()
        assert path.is_relative_to(root), f"Asset path escapes cache: {path}"
        assert path.is_file(), f"Requested asset file is missing: {path}"
        data = path.read_bytes()
        assert len(data) == entry["bytes"], f"Asset size mismatch: {path}"
        assert hashlib.sha256(data).hexdigest() == entry["sha256"], (
            f"Asset hash mismatch: {path}"
        )

    level = map_q1.parse_path(root / asset["map_path"])
    brushes = [brush for entity in level.entities for brush in entity.brushes]
    faces = [face for brush in brushes for face in brush.faces]
    classes = Counter(entity.properties.get("classname", "") for entity in level.entities)
    observed = {
        "entities": len(level.entities),
        "brushes": len(brushes),
        "faces": len(faces),
        "valve220_faces": sum(face.tex.is_valve220 for face in faces),
        "func_door": classes["func_door"],
        "light": classes["light"],
    }
    assert observed == asset["expected"]
    worldspawn = level.entities[0].properties
    assert worldspawn["classname"] == "worldspawn"
    assert worldspawn["message"] == asset["title"]
    assert worldspawn["credits"] == asset["author"]
    assert [PurePosixPath(name).name for name in worldspawn["wad"].split(";")] == (
        asset["missing_wads"]
    )


@pytest.mark.parametrize("failure", ["missing", "size", "hash"])
def test_requested_cache_fails_closed(tmp_path: Path, monkeypatch, failure: str) -> None:
    asset = MANIFEST["assets"][0]
    entry = asset["files"][0]
    path = tmp_path / asset["cache_directory"] / entry["path"]
    path.parent.mkdir(parents=True)
    if failure != "missing":
        path.write_bytes(b"x" * (entry["bytes"] if failure == "hash" else 1))
    monkeypatch.setenv("QB_TEST_ASSET_ROOT", str(tmp_path))
    with pytest.raises(AssertionError, match=failure):
        test_public_source_map(asset)


@pytest.mark.parametrize("failure", ["size", "hash"])
def test_downloader_preserves_changed_cache(tmp_path: Path, failure: str) -> None:
    powershell = shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell is needed to test the asset downloader")
    asset = MANIFEST["assets"][0]
    entry = asset["files"][0]
    path = tmp_path / asset["cache_directory"] / entry["path"]
    path.parent.mkdir(parents=True)
    original = b"x" * (entry["bytes"] if failure == "hash" else 1)
    path.write_bytes(original)
    script = Path(__file__).resolve().parents[1] / "scripts" / "fetch_test_assets.ps1"
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-File", str(script),
         "-CacheRoot", str(tmp_path), "-AssetId", asset["id"]],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert ("SHA256 mismatch" if failure == "hash" else "size mismatch") in result.stderr
    assert path.read_bytes() == original
    assert [item for item in tmp_path.rglob("*") if item.is_file()] == [path]
