"""GoldSrc BSP fixtures with embedded, external and absent textures."""

from __future__ import annotations

import io
import struct

import pytest

from quakeblend.formats import bsp_goldsrc, bsp_q1
from quakeblend.formats.common import Vec3


def _bsp(lumps: dict[int, bytes]) -> bytes:
    cursor = 124
    header = [struct.pack("<i", 30)]
    for index in range(15):
        blob = lumps.get(index, b"")
        header.append(struct.pack("<ii", cursor, len(blob)))
        cursor += len(blob)
    return b"".join(header) + b"".join(lumps.get(index, b"") for index in range(15))


def _texture(*, external: bool = False) -> bytes:
    header = b"{masked".ljust(16, b"\x00") + struct.pack("<2I", 8, 8)
    if external:
        return header + bytes(16)
    return (header + struct.pack("<4I", 40, 104, 120, 124)
            + bytes((224, 255)) * 32 + bytes(21)
            + struct.pack("<H", 256) + bytes((51, 102, 153)) * 256)


def _textures(*payloads: bytes | None) -> bytes:
    cursor = 4 + len(payloads) * 4
    offsets = []
    for payload in payloads:
        offsets.append(cursor if payload is not None else -1)
        cursor += len(payload) if payload is not None else 0
    return (struct.pack("<i", len(payloads))
            + b"".join(struct.pack("<i", offset) for offset in offsets)
            + b"".join(payload for payload in payloads if payload is not None))


def test_embedded_external_and_missing_slots() -> None:
    parsed = bsp_goldsrc.read(io.BytesIO(_bsp({
        0: b'{ "classname" "worldspawn" "wad" "C:\\old\\halflife.wad" }\x00',
        2: _textures(_texture(), _texture(external=True), None),
        8: bytes((10, 20, 30)),
    })))
    assert parsed.version == 30
    assert parsed.entities[0]["classname"] == "worldspawn"
    assert parsed.lighting == bytes((10, 20, 30))
    assert len(parsed.miptextures) == 3
    assert parsed.miptextures[0].pixels == bytes((224, 255)) * 32
    assert parsed.miptextures[1] == bsp_q1.MipTexture("{masked", 8, 8, b"")
    assert parsed.miptextures[2] is None
    assert set(parsed.embedded_textures) == {0}
    assert parsed.embedded_textures[0].palette == bytes((51, 102, 153)) * 256


def test_signed_edges_and_face_styles() -> None:
    parsed = bsp_goldsrc.read(io.BytesIO(_bsp({
        2: _textures(_texture(external=True)),
        3: struct.pack("<9f", 0, 0, 0, 8, 0, 0, 0, 8, 0),
        6: struct.pack("<8f2I", 1, 0, 0, 0, 0, 1, 0, 0, 0, 0),
        7: struct.pack("<HHiHH4Bi", 0, 0, 0, 3, 0, 1, 2, 255, 255, -1),
        12: struct.pack("<8H", 0, 0, 0, 1, 2, 1, 2, 0),
        13: struct.pack("<3i", 1, -2, 3),
        14: struct.pack("<9f7i", 0, 0, 0, 8, 8, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1),
    })))
    assert parsed.face_polygon(parsed.faces[0]) == [0, 1, 2]
    assert parsed.faces[0].typelight == 1
    assert parsed.faces[0].baselight == 2
    assert parsed.models[0].face_count == 1


@pytest.mark.parametrize("version", [29, 38, 46])
def test_rejects_other_versions(version: int) -> None:
    with pytest.raises(ValueError, match="not a GoldSrc"):
        bsp_goldsrc.read(io.BytesIO(struct.pack("<i", version) + bytes(120)))


@pytest.mark.parametrize("blob", [b"", bytes(3), struct.pack("<i", 30) + bytes(119)])
def test_truncated_header(blob: bytes) -> None:
    with pytest.raises(EOFError):
        bsp_goldsrc.read(io.BytesIO(blob))


@pytest.mark.parametrize("count", [-1, 1000000000])
def test_bad_texture_count(count: int) -> None:
    with pytest.raises((ValueError, EOFError)):
        bsp_goldsrc.read(io.BytesIO(_bsp({2: struct.pack("<i", count)})))


@pytest.mark.parametrize("offset", [-2, 0, 4, 10000])
def test_bad_texture_offset(offset: int) -> None:
    with pytest.raises((ValueError, EOFError)):
        bsp_goldsrc.read(io.BytesIO(_bsp({2: struct.pack("<2i", 1, offset) + _texture()})))


@pytest.mark.parametrize("dimensions", [(0, 8), (8, 0), (65536, 65536)])
def test_invalid_dimensions(dimensions: tuple[int, int]) -> None:
    payload = bytearray(_texture(external=True))
    struct.pack_into("<2I", payload, 16, *dimensions)
    with pytest.raises(ValueError, match="dimensions"):
        bsp_goldsrc.read(io.BytesIO(_bsp({2: _textures(bytes(payload))})))


def test_embedded_palette_cannot_read_next_texture() -> None:
    with pytest.raises(ValueError, match="palette"):
        bsp_goldsrc.read(io.BytesIO(_bsp({2: _textures(_texture()[:-20], _texture())})))


@pytest.mark.parametrize("offsets", [(0, 104, 120, 124), (20, 104, 120, 124), (40, 41, 120, 124)])
def test_partial_or_overlapping_mip_levels(offsets: tuple) -> None:
    payload = bytearray(_texture())
    struct.pack_into("<4I", payload, 24, *offsets)
    with pytest.raises(ValueError):
        bsp_goldsrc.read(io.BytesIO(_bsp({2: _textures(bytes(payload))})))


def test_pixels_cannot_read_next_texture() -> None:
    with pytest.raises(EOFError):
        bsp_goldsrc.read(io.BytesIO(_bsp({2: _textures(_texture()[:50], _texture())})))


@pytest.mark.parametrize("offset, size", [(-1, 1), (4, 1), (10000, 1), (124, 10000)])
def test_validates_unused_lump_bounds(offset: int, size: int) -> None:
    blob = bytearray(_bsp({0: b"{}"}))
    struct.pack_into("<2i", blob, 4 + 4 * 8, offset, size)
    with pytest.raises((ValueError, EOFError)):
        bsp_goldsrc.read(io.BytesIO(blob))


def test_rejects_overlapping_lumps() -> None:
    blob = bytearray(_bsp({0: b"{}"}))
    struct.pack_into("<2i", blob, 4 + 8 * 8, 124, 2)
    with pytest.raises(ValueError, match="overlapping"):
        bsp_goldsrc.read(io.BytesIO(blob))


def test_rejects_partial_geometry_record() -> None:
    with pytest.raises(ValueError, match="incomplete"):
        bsp_goldsrc.read(io.BytesIO(_bsp({3: bytes(13)})))


@pytest.mark.parametrize("model", ["*bad", "*-1", "*0", "*99"])
def test_invalid_entity_model_reference(model: str) -> None:
    entity = ('{ "classname" "func_door" "model" "' + model + '" }').encode("ascii")
    with pytest.raises(ValueError, match="model reference"):
        bsp_goldsrc.read(io.BytesIO(_bsp({0: entity})))


def test_model_origin_must_be_finite() -> None:
    parsed = bsp_goldsrc.Bsp(models=[bsp_q1.Model(
        Vec3(0, 0, 0), Vec3(1, 1, 1), Vec3(float("nan"), 0, 0), 0, 0,
    )])
    with pytest.raises(ValueError, match="finite"):
        parsed.validate()
