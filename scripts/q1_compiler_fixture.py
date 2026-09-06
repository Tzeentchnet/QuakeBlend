"""Generate an original sealed Q1 MAP and WAD2 for compiler acceptance checks."""

from __future__ import annotations

import argparse
import struct
from pathlib import Path

from quakeblend.formats import map_q1, map_writer
from quakeblend.formats.common import Plane, Vec3
from quakeblend.formats.csg import brush_faces_from_planes


def box(minimum: tuple, maximum: tuple, texture: str) -> map_q1.MapBrush:
    planes = [Plane(normal, distance) for normal, distance in (
        (Vec3(1, 0, 0), maximum[0]), (Vec3(-1, 0, 0), -minimum[0]),
        (Vec3(0, 1, 0), maximum[1]), (Vec3(0, -1, 0), -minimum[1]),
        (Vec3(0, 0, 1), maximum[2]), (Vec3(0, 0, -1), -minimum[2]),
    )]
    faces = []
    for plane, ring in zip(planes, brush_faces_from_planes(planes)):
        first, second, third = ring[:3]
        if Plane.from_points(first, second, third).normal.dot(plane.normal) < 0:
            second, third = third, second
        faces.append(map_q1.MapFace(first, second, third, map_q1.TexInfo(texture)))
    return map_q1.MapBrush(faces)


def fixture_level() -> map_q1.MapFile:
    bounds = [
        ((-144, -144, -144), (-128, 144, 144)),
        ((128, -144, -144), (144, 144, 144)),
        ((-128, -144, -144), (128, -128, 144)),
        ((-128, 128, -144), (128, 144, 144)),
        ((-128, -128, -144), (128, 128, -128)),
        ((-128, -128, 128), (128, 128, 144)),
    ]
    brushes = [box(minimum, maximum, "qb_wall") for minimum, maximum in bounds]
    brushes.append(box((-16, -16, -16), (16, 16, 16), "qb_grid"))
    return map_q1.MapFile([
        map_q1.MapEntity({"classname": "worldspawn", "wad": "fixture.wad", "mapversion": "220"}, brushes),
        map_q1.MapEntity({"classname": "info_player_start", "origin": "64 64 -80"}),
        map_q1.MapEntity({"classname": "light", "origin": "0 0 96", "light": "200"}),
    ])


def fixture_wad() -> bytes:
    payloads = []
    directory = []
    offset = 12
    for name in ("qb_wall", "qb_grid", "skip"):
        encoded = name.encode("ascii").ljust(16, b"\0")
        levels = []
        offsets = []
        mip_offset = 40
        for mip in range(4):
            width, height = 64 >> mip, 32 >> mip
            pixels = bytes(
                15 if column == 0 or row == 0 else
                32 + ((column << mip) // 8 + 3 * ((row << mip) // 8)) % 12
                for row in range(height) for column in range(width)
            )
            offsets.append(mip_offset)
            levels.append(pixels)
            mip_offset += len(pixels)
        payload = encoded + struct.pack("<6I", 64, 32, *offsets) + b"".join(levels)
        payloads.append(payload)
        directory.append(struct.pack("<iiiBBBB16s", offset, len(payload), len(payload),
                                     0x44, 0, 0, 0, encoded))
        offset += len(payload)
    return b"WAD2" + struct.pack("<ii", len(payloads), offset) + b"".join(payloads + directory)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "fixture.wad").write_bytes(fixture_wad())
    map_writer.serialize_path(fixture_level(), args.output_dir / "source.map", projection="valve220")
    print(args.output_dir.resolve())


if __name__ == "__main__":
    main()
