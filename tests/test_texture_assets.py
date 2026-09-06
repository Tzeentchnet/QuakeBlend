from __future__ import annotations

import hashlib
import json
import os
import re
import struct
from pathlib import Path, PurePosixPath

import pytest

from quakeblend.formats import map_q1
from quakeblend.utils.paths import TextureRootIndex
from scripts.catalog_texture_subset import NOTICES, build_catalog


ASSET = json.loads(
    (Path(__file__).parent / "assets" / "librequake-textures.json").read_text(encoding="utf-8")
)["assets"][0]


def test_texture_catalog() -> None:
    assert ASSET["repository"] == "lavenderdotpet/LibreQuake"
    assert re.fullmatch(r"[0-9a-f]{40}", ASSET["revision"])
    assert ASSET["source_base_url"] == (
        f"https://raw.githubusercontent.com/{ASSET['repository']}/{ASSET['revision']}/"
    )
    coverage = ASSET["coverage"]
    assert coverage["revision"] == ASSET["revision"]
    assert len(coverage["exact"]) == 71
    assert len(coverage["ambiguous"]) == 3
    assert len(coverage["encoded_candidates"]) == 9
    assert coverage["missing"] == []
    groups = [set(coverage[key]) for key in
              ("exact", "ambiguous", "encoded_candidates", "missing")]
    assert len(set().union(*groups)) == sum(map(len, groups)) == coverage["required_textures"]
    paths = {entry["path"] for entry in ASSET["files"]}
    assert len(paths) == len(ASSET["files"]) == 76
    assert paths == set(NOTICES) | set(coverage["exact"].values())
    for entry in ASSET["files"]:
        assert re.fullmatch(r"[A-Za-z0-9_./-]+", entry["path"])
        path = PurePosixPath(entry["path"])
        assert not path.is_absolute() and ".." not in path.parts
        assert re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
        assert entry["bytes"] > 0
        if "texture_name" in entry:
            assert coverage["exact"][entry["texture_name"]] == entry["path"]
            assert entry["width"] > 0 and entry["height"] > 0


def test_public_texture_subset() -> None:
    cache = os.environ.get("QB_TEST_ASSET_ROOT")
    if not cache:
        pytest.skip("Set QB_TEST_ASSET_ROOT to validate the acquired texture subset")
    root = (Path(cache) / ASSET["cache_directory"]).resolve()
    index = TextureRootIndex(root)
    for entry in ASSET["files"]:
        path = (root / entry["path"]).resolve()
        assert path.is_relative_to(root)
        assert path.is_file(), f"Requested asset file is missing: {path}"
        data = path.read_bytes()
        assert len(data) == entry["bytes"]
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
        if "texture_name" in entry:
            assert data[:8] == b"\x89PNG\r\n\x1a\n"
            assert struct.unpack(">II", data[16:24]) == (entry["width"], entry["height"])
            assert index.resolve(entry["texture_name"].upper(), kind="image") == (path, "image")
    coverage = ASSET["coverage"]
    for name in [*coverage["ambiguous"], *coverage["encoded_candidates"]]:
        assert index.resolve(name) is None
    source = json.loads(
        (Path(__file__).parent / "assets" / "manifest.json").read_text(encoding="utf-8")
    )["assets"][0]
    level = map_q1.parse_path(Path(cache) / source["cache_directory"] / source["map_path"])
    names = {face.tex.name for entity in level.entities
             for brush in entity.brushes for face in brush.faces}
    assert names == set(coverage["exact"]) | set(coverage["ambiguous"]) | set(coverage["encoded_candidates"])


def test_catalog_generator_checks_git_blobs(tmp_path: Path) -> None:
    relative = "texture-wads/example/brick.png"
    image = b"\x89PNG\r\n\x1a\n" + struct.pack(">I4sII", 13, b"IHDR", 32, 64)
    tree = {"sha": "revision", "truncated": False, "tree": []}
    for name in [*NOTICES, relative]:
        data = image if name == relative else b"notice"
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        tree["tree"].append({"path": name, "sha": hashlib.sha1(
            f"blob {len(data)}\0".encode("ascii") + data
        ).hexdigest()})
    audit = {"revision": "revision", "exact": {"brick": relative}}
    result = build_catalog(audit, tree, tmp_path)["assets"][0]
    assert result["files"][-1]["width"] == 32
    assert result["files"][-1]["height"] == 64
    (tmp_path / relative).write_bytes(image + b"changed")
    with pytest.raises(ValueError, match="Git blob mismatch"):
        build_catalog(audit, tree, tmp_path)


def test_catalog_generator_rejects_revision_mismatch(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="same revision"):
        build_catalog({"revision": "old"}, {"sha": "new", "truncated": False}, tmp_path)
