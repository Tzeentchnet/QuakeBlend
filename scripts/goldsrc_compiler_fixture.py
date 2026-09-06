"""Generate original connected GoldSrc MAPs and a WAD3 for compiler validation."""

from __future__ import annotations

import argparse
import struct
from dataclasses import replace
from pathlib import Path

from quakeblend.formats import map_q1, map_writer
from scripts.q1_compiler_fixture import box, fixture_level as q1_fixture_level


TEXTURE_NAMES = ("qb_wall", "qb_high", "{qb_mask", "origin", "aaatrigger", "skip")
MAP_NAMES = ("qb_gold_a", "qb_gold_b")
VARIANTS = ("embedded", "external")
DOOR_ORIGIN = (64, 0, -16)
DOOR_MINIMUM = (56, -24, -48)
DOOR_MAXIMUM = (72, 24, 16)


def fixture_level(name: str) -> map_q1.MapFile:
    if name not in MAP_NAMES:
        raise ValueError(f"Unknown fixture map: {name}")
    level = q1_fixture_level()
    world = level.entities[0]
    world.properties["wad"] = "fixture.wad"
    world.brushes[6] = map_q1.MapBrush([
        replace(face, tex=replace(face.tex, name="qb_high")) for face in world.brushes[6].faces
    ])
    level.entities[1].properties["angles"] = "0 90 0"
    level.entities[2].properties = {"classname": "light", "origin": "0 0 96", "_light": "255 128 0 200"}
    door = box(DOOR_MINIMUM, DOOR_MAXIMUM, "{qb_mask")
    pivot = box((60, -4, -20), (68, 4, -12), "origin")
    landmark_x = 96 if name == MAP_NAMES[0] else -96
    other = MAP_NAMES[1] if name == MAP_NAMES[0] else MAP_NAMES[0]
    level.entities.extend([
        map_q1.MapEntity({"classname": "func_door", "targetname": "fixture_door", "speed": "100"},
                         [door, pivot]),
        map_q1.MapEntity({"classname": "info_landmark", "targetname": "join",
                         "origin": f"{landmark_x} 0 0"}),
        map_q1.MapEntity({"classname": "trigger_changelevel", "map": other, "landmark": "join"},
                         [box((landmark_x - 8, -16, -32), (landmark_x + 8, 16, 32), "aaatrigger")]),
    ])
    return level


def fixture_palette() -> bytes:
    return bytes(component for index in range(255)
                 for component in (index, index * 3 % 256, 255 - index)) + bytes((0, 0, 255))


def fixture_wad() -> bytes:
    payloads = []
    directory = []
    offset = 12
    for name in TEXTURE_NAMES:
        encoded = name.encode("ascii").ljust(16, b"\0")
        levels = []
        offsets = []
        mip_offset = 40
        for mip in range(4):
            width, height = 64 >> mip, 32 >> mip
            pixels = bytes(
                255 if name.startswith("{") and column < width // 2 else
                224 + ((column << mip) // 8 + 3 * ((row << mip) // 8)) % 31
                for row in range(height) for column in range(width)
            )
            offsets.append(mip_offset)
            levels.append(pixels)
            mip_offset += len(pixels)
        payload = (encoded + struct.pack("<6I", 64, 32, *offsets) + b"".join(levels)
                   + struct.pack("<H", 256) + fixture_palette() + bytes(2))
        payloads.append(payload)
        directory.append(struct.pack("<iiiBBBB16s", offset, len(payload), len(payload),
                                     0x43, 0, 0, 0, encoded))
        offset += len(payload)
    return b"WAD3" + struct.pack("<ii", len(payloads), offset) + b"".join(payloads + directory)


def fixture_text(name: str) -> str:
    level = fixture_level(name)
    for entity in level.entities:
        for brush in entity.brushes:
            brush.faces[:] = [replace(face, tex=replace(face.tex, name=map_writer._quote(face.tex.name)))
                              for face in brush.faces]
    return map_writer.serialize(level, projection="valve220")


def write_fixture(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "fixture.wad").write_bytes(fixture_wad())
    for variant in VARIANTS:
        target = directory / variant
        target.mkdir()
        for name in MAP_NAMES:
            (target / f"{name}.map").write_text(fixture_text(name), encoding="ascii")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    write_fixture(args.output_dir)
    print(args.output_dir.resolve())


if __name__ == "__main__":
    main()
