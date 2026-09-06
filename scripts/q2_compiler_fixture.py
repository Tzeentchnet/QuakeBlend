"""Generate an original sealed Q2 MAP and WALs for compiler acceptance checks."""

from __future__ import annotations

import argparse
import struct
from dataclasses import replace
from pathlib import Path

from quakeblend.formats import map_q2, map_writer
from scripts.q1_compiler_fixture import fixture_level as q1_fixture_level


TEXTURE_NAMES = ("qb_wall", "qb_grid")


def fixture_level() -> map_q2.MapFile:
    level = q1_fixture_level()
    level.entities[0].properties.pop("wad")
    for brush_index, brush in enumerate(level.entities[0].brushes):
        level.entities[0].brushes[brush_index] = map_q2.MapBrush([
            replace(face, tex=replace(
                face.tex, name=f"quakeblend/{face.tex.name}", contents=1,
                surface_flags=2 if brush_index == 6 else 0,
                value=37 if brush_index == 6 else 0,
            )) for face in brush.faces
        ])
    return level


def fixture_wal(name: str) -> bytes:
    encoded = ("skip" if name == "skip" else f"quakeblend/{name}").encode("ascii")
    if name not in (*TEXTURE_NAMES, "skip"):
        raise ValueError(f"Unknown fixture texture: {name}")
    levels = []
    offsets = []
    offset = 100
    for mip in range(4):
        width, height = 64 >> mip, 32 >> mip
        pixels = bytes(
            15 if column == 0 or row == 0 else
            32 + ((column << mip) // 8 + 3 * ((row << mip) // 8)) % 12
            for row in range(height) for column in range(width)
        )
        offsets.append(offset)
        levels.append(pixels)
        offset += len(pixels)
    return struct.pack("<32s6I32s3I", encoded, 64, 32, *offsets, b"", 0, 1, 0) + b"".join(levels)


def write_fixture(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=False)
    textures = directory / "textures" / "quakeblend"
    textures.mkdir(parents=True)
    for name in TEXTURE_NAMES:
        (textures / f"{name}.wal").write_bytes(fixture_wal(name))
    (directory / "textures" / "skip.wal").write_bytes(fixture_wal("skip"))
    map_writer.serialize_path(fixture_level(), directory / "source.map",
                              dialect="q2", projection="valve220")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    write_fixture(args.output_dir)
    print(args.output_dir.resolve())


if __name__ == "__main__":
    main()
