"""WAD2 (Quake 1) and WAD3 (Half-Life) texture archive parsers.

Layout (little-endian):

    Header
        char[4] magic  = "WAD2" or "WAD3"
        int32   numentries
        int32   diroffset
    Directory entries (32 bytes each, at diroffset)
        int32   offset
        int32   dsize        (compressed size)
        int32   size         (uncompressed size; equal to dsize for type 0x44)
        int8    type         (0x44 = miptex for both WAD2/WAD3)
        int8    compression  (0 for Quake)
        int16   padding
        char[16] name (null-padded ASCII, lowercased by convention)

Miptex payload (referenced by entry.offset):

    char[16] name
    uint32   width, height
    uint32   offsets[4]   (relative to start of miptex payload)
    uint8    pixels[...]  (4 mip levels, contiguous; mip0 = width*height)

WAD3 differs from WAD2 only in that each miptex is followed by a per-texture
256-entry palette (2 bytes pad + 768 palette bytes) after the smallest mip.
The :class:`MipTexture` returned here always exposes mip0 raw indices; the
embedded palette (if any) is exposed via ``MipTexture.palette``.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from ..utils.constants import (
    MAX_TEXTURE_DIMENSION, MAX_TEXTURE_PIXELS,
    WAD2_MAGIC, WAD3_MAGIC, WAD_TYPE_MIPTEX,
)
from .common import BinaryReader, read_exact


@dataclass(frozen=True)
class WadEntry:
    name: str
    type: int
    offset: int
    size: int
    disk_size: int
    compression: int


@dataclass(frozen=True)
class MipTexture:
    name: str
    width: int
    height: int
    pixels: bytes              # mip-0 indices (width * height bytes)
    mip_pixels: tuple[bytes, bytes, bytes, bytes]  # all four mip levels
    palette: bytes | None      # 768 bytes for WAD3 entries; None for WAD2


@dataclass(frozen=True)
class Wad:
    flavour: str               # "WAD2" or "WAD3"
    entries: tuple[WadEntry, ...]
    textures: tuple[MipTexture, ...]


# -------------------------------------------------------------------- header


def _read_header(r: BinaryReader) -> tuple[str, int, int]:
    magic = r.read(4)
    if magic == WAD2_MAGIC:
        flavour = "WAD2"
    elif magic == WAD3_MAGIC:
        flavour = "WAD3"
    else:
        raise ValueError(f"not a WAD2/WAD3 file (magic={magic!r})")
    numentries = r.s32()
    diroffset = r.s32()
    return flavour, numentries, diroffset


def _read_directory(r: BinaryReader, count: int) -> list[WadEntry]:
    entries: list[WadEntry] = []
    for _ in range(count):
        offset, dsize, size, etype, compression = r.unpack("iiibb")
        r.read(2)  # padding
        name = r.fixed_string(16)
        entries.append(
            WadEntry(
                name=name,
                type=etype,
                offset=offset,
                size=size,
                disk_size=dsize,
                compression=compression,
            )
        )
    return entries


# -------------------------------------------------------------------- miptex


def read_miptex(stream: BinaryIO, *, base_offset: int, payload_size: int,
                expect_palette: bool) -> MipTexture:
    """Read one miptex from ``stream`` at ``base_offset``.

    ``payload_size`` is the directory-entry size; only used to detect a
    trailing per-texture palette in WAD3.
    """
    stream.seek(base_offset)
    r = BinaryReader(stream)
    name = r.fixed_string(16)
    width = r.u32()
    height = r.u32()
    offsets = [r.u32() for _ in range(4)]
    if width == 0 or height == 0:
        raise ValueError(f"miptex dimensions must be positive, got {width}×{height}")
    if width > MAX_TEXTURE_DIMENSION or height > MAX_TEXTURE_DIMENSION:
        raise ValueError(
            f"miptex dimensions exceed {MAX_TEXTURE_DIMENSION}: {width}×{height}"
        )
    if width * height > MAX_TEXTURE_PIXELS:
        raise ValueError(f"miptex pixel count is too large: {width}×{height}")
    if payload_size < 40:
        raise EOFError(f"miptex payload is too short: {payload_size} bytes")

    mip_pixels: list[bytes] = []
    for level, off in enumerate(offsets):
        w = max(1, width >> level)
        h = max(1, height >> level)
        if off == 0:
            if level == 0:
                raise ValueError("primary mip offset must be nonzero")
            mip_pixels.append(b"")
            continue
        if off < 40:
            raise ValueError(f"mip {level} offset {off} points inside the miptex header")
        if off + w * h > payload_size:
            raise EOFError(
                f"mip {level} exceeds miptex payload: "
                f"offset={off}, size={w * h}, payload_size={payload_size}"
            )
        stream.seek(base_offset + off)
        mip_pixels.append(read_exact(stream, w * h))

    palette: bytes | None = None
    if expect_palette:
        # Smallest mip ends at base + offsets[3] + (w/8)*(h/8); WAD3 stores
        # a 2-byte palette-size field then 768 palette bytes immediately after.
        end_mip3 = base_offset + offsets[3] + max(1, width >> 3) * max(1, height >> 3)
        # Some files are 2-byte-aligned; clamp to the directory-declared size.
        max_end = base_offset + payload_size
        stream.seek(end_mip3)
        if stream.tell() + 2 <= max_end:
            (count,) = BinaryReader(stream).unpack("H")
            if count == 256 and stream.tell() + 768 <= max_end:
                palette = read_exact(stream, 768)

    return MipTexture(
        name=name,
        width=width,
        height=height,
        pixels=mip_pixels[0],
        mip_pixels=tuple(mip_pixels),  # type: ignore[arg-type]
        palette=palette,
    )


# -------------------------------------------------------------------- top level


def read_wad(stream: BinaryIO) -> Wad:
    original_position = stream.tell()
    stream.seek(0, 2)
    file_size = stream.tell()
    stream.seek(original_position)
    r = BinaryReader(stream)
    flavour, numentries, diroffset = _read_header(r)
    if numentries < 0:
        raise ValueError(f"WAD directory entry count must be nonnegative, got {numentries}")
    if diroffset < 12:
        raise ValueError(f"WAD directory offset points inside the header: {diroffset}")
    directory_end = diroffset + numentries * 32
    if diroffset > file_size or directory_end > file_size:
        raise EOFError(
            f"WAD directory exceeds file bounds: offset={diroffset}, "
            f"entries={numentries}, file_size={file_size}"
        )
    stream.seek(diroffset)
    entries = _read_directory(r, numentries)

    textures: list[MipTexture] = []
    for entry in entries:
        if entry.offset < 0 or entry.disk_size < 0 or entry.size < 0:
            raise ValueError(
                f"invalid WAD entry bounds for {entry.name!r}: "
                f"offset={entry.offset}, disk_size={entry.disk_size}, size={entry.size}"
            )
        if entry.offset + entry.disk_size > file_size:
            raise EOFError(
                f"WAD entry {entry.name!r} exceeds file bounds: "
                f"offset={entry.offset}, size={entry.disk_size}, file_size={file_size}"
            )
        if entry.type != WAD_TYPE_MIPTEX:
            continue
        if entry.compression != 0:
            raise ValueError(
                f"compressed WAD miptex {entry.name!r} is not supported "
                f"(compression={entry.compression})"
            )
        textures.append(
            read_miptex(
                stream,
                base_offset=entry.offset,
                payload_size=entry.disk_size,
                expect_palette=(flavour == "WAD3"),
            )
        )

    return Wad(flavour=flavour, entries=tuple(entries), textures=tuple(textures))


def read_wad_path(path: str | Path) -> Wad:
    with open(path, "rb") as fh:
        # Buffer the file: we seek around heavily.
        return read_wad(io.BytesIO(fh.read()))
