"""Quake 2 WAL texture loader.

WAL header (100 bytes):

    char[32]  name
    uint32    width, height
    uint32    offsets[4]   (relative to start of file)
    char[32]  next_name    (animation chain)
    uint32    flags        (SURF_*)
    uint32    contents     (CONTENTS_*)
    uint32    value        (light value or similar)

Pixel data follows; 4 mip levels, 8-bit palette indices into the Q2 palette.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from ..utils.constants import MAX_TEXTURE_DIMENSION, MAX_TEXTURE_PIXELS
from .common import BinaryReader, read_exact

WAL_HEADER_SIZE = 100


# ----- Q2 surface flags (subset we actually care about) ---------------------
SURF_LIGHT       = 0x0001
SURF_SLICK       = 0x0002
SURF_SKY         = 0x0004
SURF_WARP        = 0x0008
SURF_TRANS33     = 0x0010
SURF_TRANS66     = 0x0020
SURF_FLOWING     = 0x0040
SURF_NODRAW      = 0x0080


@dataclass(frozen=True)
class Wal:
    name: str
    width: int
    height: int
    pixels: bytes
    mip_pixels: tuple[bytes, bytes, bytes, bytes]
    next_name: str
    flags: int
    contents: int
    value: int


def read_wal(stream: BinaryIO) -> Wal:
    original_position = stream.tell()
    stream.seek(0, 2)
    file_size = stream.tell()
    stream.seek(original_position)
    r = BinaryReader(stream)
    name = r.fixed_string(32)
    width = r.u32()
    height = r.u32()
    offsets = [r.u32() for _ in range(4)]
    next_name = r.fixed_string(32)
    flags = r.u32()
    contents = r.u32()
    value = r.u32()
    if width == 0 or height == 0:
        raise ValueError(f"WAL dimensions must be positive, got {width}×{height}")
    if width > MAX_TEXTURE_DIMENSION or height > MAX_TEXTURE_DIMENSION:
        raise ValueError(
            f"WAL dimensions exceed {MAX_TEXTURE_DIMENSION}: {width}×{height}"
        )
    if width * height > MAX_TEXTURE_PIXELS:
        raise ValueError(f"WAL pixel count is too large: {width}×{height}")

    mips: list[bytes] = []
    for level, off in enumerate(offsets):
        w = max(1, width >> level)
        h = max(1, height >> level)
        if off < WAL_HEADER_SIZE:
            raise ValueError(f"WAL mip {level} offset {off} points inside the header")
        if off + w * h > file_size:
            raise EOFError(
                f"WAL mip {level} exceeds file bounds: "
                f"offset={off}, size={w * h}, file_size={file_size}"
            )
        stream.seek(off)
        mips.append(read_exact(stream, w * h))

    return Wal(
        name=name,
        width=width,
        height=height,
        pixels=mips[0],
        mip_pixels=tuple(mips),  # type: ignore[arg-type]
        next_name=next_name,
        flags=flags,
        contents=contents,
        value=value,
    )


def read_wal_path(path: str | Path) -> Wal:
    with open(path, "rb") as fh:
        return read_wal(io.BytesIO(fh.read()))
