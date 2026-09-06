"""Crop, resize, and strip metadata from a publication PNG."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image


def _crop_box(source: tuple[int, int], target: tuple[int, int]) -> tuple[int, int, int, int]:
    source_width, source_height = source
    target_width, target_height = target
    if min(source_width, source_height, target_width, target_height) <= 0:
        raise ValueError("Image dimensions must be positive")
    source_ratio = source_width / source_height
    target_ratio = target_width / target_height
    if source_ratio > target_ratio:
        crop_width = round(source_height * target_ratio)
        left = (source_width - crop_width) // 2
        return left, 0, left + crop_width, source_height
    crop_height = round(source_width / target_ratio)
    top = (source_height - crop_height) // 2
    return 0, top, source_width, top + crop_height


def prepare_image(source: Path, output: Path, size: tuple[int, int]) -> dict:
    if output.exists():
        raise FileExistsError(output)
    with Image.open(source) as image:
        image.load()
        source_size = image.size
        crop_box = _crop_box(source_size, size)
        fitted = image.convert("RGB").crop(crop_box).resize(size, Image.Resampling.LANCZOS)
    clean = Image.new("RGB", size)
    clean.paste(fitted)
    output.parent.mkdir(parents=True, exist_ok=True)
    clean.save(output, format="PNG", optimize=True, compress_level=9)
    with Image.open(output) as result:
        result.load()
        if result.size != size or result.mode != "RGB" or result.info:
            raise ValueError("Prepared image failed dimensions, color mode, or metadata check")
    return {
        "source": str(source),
        "source_size": list(source_size),
        "crop_box": list(crop_box),
        "output": str(output),
        "output_size": list(size),
        "bytes": output.stat().st_size,
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    args = parser.parse_args()
    report = prepare_image(args.source, args.output, (args.width, args.height))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
