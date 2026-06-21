"""Smoke test for the Quake 3 BSP reader."""

from __future__ import annotations

import io
import struct

import pytest

from quakeblend.formats import bsp_q3


def _make_minimal_bsp(entity_text: bytes) -> bytes:
    return _make_bsp({bsp_q3.LUMP_ENTITIES: entity_text})


def _make_bsp(
    lumps: dict[int, bytes],
    *,
    overrides: dict[int, tuple[int, int]] | None = None,
) -> bytes:
    header_size = 8 + bsp_q3.NUM_LUMPS * 8
    parts = [b"IBSP", struct.pack("<i", 46)]
    cursor = header_size
    for i in range(bsp_q3.NUM_LUMPS):
        blob = lumps.get(i, b"")
        if i in lumps:
            offset, size = overrides.get(i, (cursor, len(blob))) if overrides else (cursor, len(blob))
            parts.append(struct.pack("<ii", offset, size))
            cursor += len(blob)
        else:
            parts.append(struct.pack("<ii", header_size, 0))
    return b"".join(parts) + b"".join(lumps[i] for i in range(bsp_q3.NUM_LUMPS) if i in lumps)


def test_minimal_q3_bsp_parses_entities() -> None:
    text = b'{ "classname" "worldspawn" "music" "music/sonic5" }\n\x00'
    blob = _make_minimal_bsp(text)
    bsp = bsp_q3.read(io.BytesIO(blob))
    assert bsp.version == 46
    assert bsp.entities[0]["music"] == "music/sonic5"
    assert bsp.textures == []
    assert bsp.faces == []
    assert bsp.lightmaps == []


def test_q3_rejects_q2_signature() -> None:
    blob = b"IBSP" + struct.pack("<i", 38) + b"\x00" * (bsp_q3.NUM_LUMPS * 8)
    with pytest.raises(ValueError):
        bsp_q3.read(io.BytesIO(blob))


def test_warns_on_trailing_lump_bytes() -> None:
    with pytest.warns(UserWarning, match=r"trailing bytes"):
        meshverts = bsp_q3._read_meshverts(b"\x00" * 5)
    assert meshverts == [0]


def test_decodes_face_and_texture_lumps() -> None:
    texture_blob = b"textures/base_wall/concrete".ljust(64, b"\x00") + struct.pack("<ii", 3, 5)
    face_blob = b"".join((
        struct.pack("<8i", 1, 2, bsp_q3.FACE_TYPE_MESH, 4, 5, 6, 7, 8),
        struct.pack("<2i", 9, 10),
        struct.pack("<2i", 11, 12),
        struct.pack("<3f", 1.0, 2.0, 3.0),
        struct.pack("<3f", 4.0, 5.0, 6.0),
        struct.pack("<3f", 7.0, 8.0, 9.0),
        struct.pack("<3f", -1.0, -2.0, -3.0),
        struct.pack("<2i", 13, 14),
    ))

    bsp = bsp_q3.read(io.BytesIO(_make_bsp({
        bsp_q3.LUMP_TEXTURES: texture_blob,
        bsp_q3.LUMP_FACES: face_blob,
    })))

    assert bsp.textures == [bsp_q3.Texture("textures/base_wall/concrete", 3, 5)]
    assert bsp.faces == [bsp_q3.Face(
        texture=1,
        effect=2,
        type=bsp_q3.FACE_TYPE_MESH,
        vertex=4,
        n_vertexes=5,
        meshvert=6,
        n_meshverts=7,
        lm_index=8,
        lm_start=(9, 10),
        lm_size=(11, 12),
        lm_origin=bsp_q3.Vec3(1.0, 2.0, 3.0),
        lm_vec0=bsp_q3.Vec3(4.0, 5.0, 6.0),
        lm_vec1=bsp_q3.Vec3(7.0, 8.0, 9.0),
        normal=bsp_q3.Vec3(-1.0, -2.0, -3.0),
        size=(13, 14),
    )]


def test_rejects_lump_offset_past_eof() -> None:
    blob = _make_bsp(
        {bsp_q3.LUMP_VERTEXES: b"x" * 44},
        overrides={bsp_q3.LUMP_VERTEXES: (4096, 44)},
    )

    with pytest.raises(ValueError, match=r"offset 4096 beyond end of file"):
        bsp_q3.read(io.BytesIO(blob))


def test_rejects_truncated_lump_data() -> None:
    header_size = 8 + bsp_q3.NUM_LUMPS * 8
    blob = _make_bsp(
        {bsp_q3.LUMP_FACES: b"x" * 60},
        overrides={bsp_q3.LUMP_FACES: (header_size, 104)},
    )

    with pytest.raises(EOFError, match=r"truncated BSP lump"):
        bsp_q3.read(io.BytesIO(blob))


def test_round_trips_vertex_and_meshvert_lumps() -> None:
    vertex_blob = struct.pack(
        "<10f4B",
        1.0, 2.0, 3.0,
        0.25, 0.5,
        0.75, 1.0,
        0.0, 0.0, 1.0,
        10, 20, 30, 40,
    )
    meshvert_blob = struct.pack("<i", 2)

    bsp = bsp_q3.read(io.BytesIO(_make_bsp({
        bsp_q3.LUMP_VERTEXES: vertex_blob,
        bsp_q3.LUMP_MESHVERTS: meshvert_blob,
    })))

    assert bsp.vertices == [bsp_q3.Vertex(
        pos=bsp_q3.Vec3(1.0, 2.0, 3.0),
        tex_uv=(0.25, 0.5),
        lm_uv=(0.75, 1.0),
        normal=bsp_q3.Vec3(0.0, 0.0, 1.0),
        color=(10, 20, 30, 40),
    )]
    assert bsp.meshverts == [2]
