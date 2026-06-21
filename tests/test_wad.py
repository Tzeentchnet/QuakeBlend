"""Tests for the WAD2 / WAD3 readers using hand-built fixtures."""

from __future__ import annotations

import io
import struct

import pytest

from quakeblend.formats import wad


def _make_miptex_payload(name: str, w: int, h: int, fill: int = 7,
                         *, palette: bytes | None = None) -> bytes:
    """Build a contiguous miptex (mip0..mip3) for testing."""
    name_b = name.encode("ascii").ljust(16, b"\x00")
    sizes = [(max(1, w >> i), max(1, h >> i)) for i in range(4)]
    pixel_blocks = [bytes([fill + i] * (sw * sh)) for i, (sw, sh) in enumerate(sizes)]

    # Layout: header(40) + 4 mip blocks contiguous.
    header_size = 40
    offsets = []
    cursor = header_size
    for block in pixel_blocks:
        offsets.append(cursor)
        cursor += len(block)

    header = name_b + struct.pack("<II", w, h) + struct.pack("<IIII", *offsets)
    payload = header + b"".join(pixel_blocks)
    if palette is not None:
        payload += struct.pack("<H", 256) + palette
    return payload


def _build_wad2(textures: list[tuple[str, int, int]]) -> bytes:
    """Construct a minimal WAD2 in-memory."""
    miptex_blobs: list[bytes] = []
    for name, w, h in textures:
        miptex_blobs.append(_make_miptex_payload(name, w, h))

    header_size = 12
    cursor = header_size
    entries_meta = []
    for blob in miptex_blobs:
        entries_meta.append((cursor, len(blob)))
        cursor += len(blob)
    diroffset = cursor

    body = b"WAD2" + struct.pack("<ii", len(textures), diroffset)
    body += b"".join(miptex_blobs)
    for (offset, size), (name, _w, _h) in zip(entries_meta, textures):
        body += struct.pack("<iii", offset, size, size)
        body += bytes([0x44, 0])           # type=miptex, compression=0
        body += b"\x00\x00"                # padding
        body += name.encode("ascii").ljust(16, b"\x00")
    return body


def _build_wad3(textures: list[tuple[str, int, int]]) -> bytes:
    """Construct a minimal WAD3 in-memory."""
    miptex_blobs: list[bytes] = []
    for index, (name, w, h) in enumerate(textures):
        palette = bytes([(index + i) % 256 for i in range(768)])
        miptex_blobs.append(_make_miptex_payload(name, w, h, palette=palette))

    header_size = 12
    cursor = header_size
    entries_meta = []
    for blob in miptex_blobs:
        entries_meta.append((cursor, len(blob)))
        cursor += len(blob)
    diroffset = cursor

    body = b"WAD3" + struct.pack("<ii", len(textures), diroffset)
    body += b"".join(miptex_blobs)
    for (offset, size), (name, _w, _h) in zip(entries_meta, textures):
        body += struct.pack("<iii", offset, size, size)
        body += bytes([0x44, 0])
        body += b"\x00\x00"
        body += name.encode("ascii").ljust(16, b"\x00")
    return body


def test_read_wad2_three_textures() -> None:
    data = _build_wad2([("alpha", 16, 16), ("brick", 32, 8), ("ceil", 8, 8)])
    parsed = wad.read_wad(io.BytesIO(data))
    assert parsed.flavour == "WAD2"
    assert len(parsed.entries) == 3
    assert len(parsed.textures) == 3

    by_name = {t.name: t for t in parsed.textures}
    assert by_name["alpha"].width == 16 and by_name["alpha"].height == 16
    assert by_name["brick"].width == 32 and by_name["brick"].height == 8
    assert len(by_name["alpha"].pixels) == 16 * 16
    assert all(b == 7 for b in by_name["alpha"].pixels)
    # Mip 1 of "alpha" is 8x8 with fill 8.
    assert len(by_name["alpha"].mip_pixels[1]) == 8 * 8
    assert all(b == 8 for b in by_name["alpha"].mip_pixels[1])
    # WAD2 entries must not carry a per-texture palette.
    assert by_name["alpha"].palette is None


def test_read_wad_rejects_bad_magic() -> None:
    with pytest.raises(ValueError):
        wad.read_wad(io.BytesIO(b"NOPE" + b"\x00" * 8))


def test_read_wad3_reads_palette() -> None:
    data = _build_wad3([("metal", 8, 8)])
    parsed = wad.read_wad(io.BytesIO(data))
    assert parsed.flavour == "WAD3"
    assert len(parsed.textures) == 1
    assert parsed.textures[0].palette is not None
    assert len(parsed.textures[0].palette) == 768
    assert parsed.textures[0].palette[:4] == bytes([0, 1, 2, 3])


def test_read_wad_raises_on_truncated_mip_pixels() -> None:
    name_b = b"alpha".ljust(16, b"\x00")
    width = height = 16
    offsets = (40, 296, 360, 376)
    mip_header = name_b + struct.pack("<II", width, height) + struct.pack("<IIII", *offsets)
    payload = mip_header + bytes([7] * 100)
    entry_offset = 12 + 32
    full_size = 40 + 256 + 64 + 16 + 4
    directory = (
        struct.pack("<iii", entry_offset, full_size, full_size)
        + bytes([0x44, 0])
        + b"\x00\x00"
        + b"alpha".ljust(16, b"\x00")
    )
    data = b"WAD2" + struct.pack("<ii", 1, 12) + directory + payload
    with pytest.raises(EOFError):
        wad.read_wad(io.BytesIO(data))


def test_read_wad_raises_on_directory_offset_past_eof() -> None:
    data = b"WAD2" + struct.pack("<ii", 1, 4096)
    with pytest.raises(EOFError):
        wad.read_wad(io.BytesIO(data))


def test_read_wad_raises_on_entry_offset_past_eof() -> None:
    directory = (
        struct.pack("<iii", 4096, 64, 64)
        + bytes([0x44, 0])
        + b"\x00\x00"
        + b"ghost".ljust(16, b"\x00")
    )
    data = b"WAD2" + struct.pack("<ii", 1, 12) + directory
    with pytest.raises(EOFError):
        wad.read_wad(io.BytesIO(data))
