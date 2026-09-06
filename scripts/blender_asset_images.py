"""Decode the pinned PNG subset using Blender without importing a level."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from array import array
from pathlib import Path

import bpy


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-root", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    asset = json.loads(
        (Path(__file__).resolve().parents[1] / "tests" / "assets" /
         "librequake-textures.json").read_text(encoding="utf-8")
    )["assets"][0]
    root = (args.cache_root / asset["cache_directory"]).resolve()
    decoded = 0
    for entry in asset["files"]:
        path = (root / entry["path"]).resolve()
        assert path.is_relative_to(root)
        data = path.read_bytes()
        assert len(data) == entry["bytes"]
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
        if "texture_name" not in entry:
            continue
        image = bpy.data.images.load(str(path), check_existing=False)
        try:
            assert tuple(image.size) == (entry["width"], entry["height"]), path
            pixels = array("f", [0.0]) * (entry["width"] * entry["height"] * 4)
            assert len(image.pixels) == len(pixels), path
            image.pixels.foreach_get(pixels)
            assert all(math.isfinite(value) for value in pixels), path
            assert any(pixels[3::4]), path
            decoded += 1
        finally:
            bpy.data.images.remove(image)
    assert decoded == len(asset["coverage"]["exact"]) == 71
    print(f"QUAKEBLEND_ASSET_IMAGES_OK decoded={decoded} blender={bpy.app.version_string}")


if __name__ == "__main__":
    main()
