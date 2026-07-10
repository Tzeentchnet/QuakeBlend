"""Tests for the WAL reader using a hand-built fixture."""

from __future__ import annotations

import io
import struct

import pytest

from quakeblend.formats import wal


def _build_wal(name: str, w: int, h: int, *, flags: int = 0, contents: int = 0,
               value: int = 0, next_name: str = "") -> bytes:
    sizes = [(max(1, w >> i), max(1, h >> i)) for i in range(4)]
    blocks = [bytes([10 + i] * (sw * sh)) for i, (sw, sh) in enumerate(sizes)]
    header_size = wal.WAL_HEADER_SIZE
    offsets = []
    cursor = header_size
    for blk in blocks:
        offsets.append(cursor)
        cursor += len(blk)

    name_b = name.encode("ascii").ljust(32, b"\x00")
    next_b = next_name.encode("ascii").ljust(32, b"\x00")
    header = (
        name_b
        + struct.pack("<II", w, h)
        + struct.pack("<IIII", *offsets)
        + next_b
        + struct.pack("<III", flags, contents, value)
    )
    assert len(header) == header_size
    return header + b"".join(blocks)


def test_read_wal_basic() -> None:
    data = _build_wal("textures/base/floor", 32, 16,
                      flags=wal.SURF_LIGHT, contents=0x1, value=300,
                      next_name="textures/base/floor2")
    parsed = wal.read_wal(io.BytesIO(data))
    assert parsed.name == "textures/base/floor"
    assert parsed.width == 32 and parsed.height == 16
    assert len(parsed.pixels) == 32 * 16
    assert parsed.pixels[0] == 10
    # mip 2: w=8, h=4, fill=12
    assert len(parsed.mip_pixels[2]) == 8 * 4
    assert all(b == 12 for b in parsed.mip_pixels[2])
    assert parsed.flags & wal.SURF_LIGHT
    assert parsed.next_name == "textures/base/floor2"
    assert parsed.value == 300


def test_read_wal_raises_on_truncated_mip_pixels() -> None:
    data = _build_wal("textures/base/floor", 16, 16)[:-1]
    with pytest.raises(EOFError):
        wal.read_wal(io.BytesIO(data))


def test_read_wal_rejects_zero_dimensions() -> None:
    data = _build_wal("textures/base/zero", 0, 0)
    with pytest.raises(ValueError, match="dimensions must be positive"):
        wal.read_wal(io.BytesIO(data))


def test_read_wal_raises_on_offset_past_eof() -> None:
    data = bytearray(_build_wal("textures/base/floor", 16, 16))
    struct.pack_into("<I", data, 40, len(data) + 64)
    with pytest.raises(EOFError):
        wal.read_wal(io.BytesIO(data))


def test_read_wal_rejects_mip_offset_inside_header() -> None:
    data = bytearray(_build_wal("textures/base/floor", 16, 16))
    struct.pack_into("<I", data, 40, 4)
    with pytest.raises(ValueError, match="inside the header"):
        wal.read_wal(io.BytesIO(data))


def test_read_wal_rejects_oversized_dimensions() -> None:
    data = bytearray(_build_wal("textures/base/floor", 16, 16))
    struct.pack_into("<I", data, 32, 4097)
    with pytest.raises(ValueError, match="dimensions exceed"):
        wal.read_wal(io.BytesIO(data))
