"""Smoke test for the Quake 1 BSP reader using a tiny synthetic file.

Builds the smallest legal v29 BSP we can: empty geometry lumps + a one-entity
entity lump. This exercises header parsing, lump dispatch and entity decoding.
"""

from __future__ import annotations

import io
import struct

import pytest

from quakeblend.formats import bsp_q1


def _make_minimal_bsp(entity_text: bytes) -> bytes:
    return _make_bsp({bsp_q1.LUMP_ENTITIES: entity_text})


def _make_bsp(
    lumps: dict[int, bytes],
    *,
    overrides: dict[int, tuple[int, int]] | None = None,
) -> bytes:
    header_size = 4 + bsp_q1.NUM_LUMPS * 8
    cursor = header_size
    parts = [struct.pack("<i", bsp_q1.BSP_VERSION)]
    for i in range(bsp_q1.NUM_LUMPS):
        blob = lumps.get(i, b"")
        if i in lumps:
            offset, size = overrides.get(i, (cursor, len(blob))) if overrides else (cursor, len(blob))
            parts.append(struct.pack("<ii", offset, size))
            cursor += len(blob)
        else:
            parts.append(struct.pack("<ii", header_size, 0))
    return b"".join(parts) + b"".join(lumps[i] for i in range(bsp_q1.NUM_LUMPS) if i in lumps)


def test_minimal_bsp_parses_entities() -> None:
    text = b'{ "classname" "worldspawn" }\n{ "classname" "info_player_start" "origin" "1 2 3" }\n\x00'
    blob = _make_minimal_bsp(text)
    bsp = bsp_q1.read(io.BytesIO(blob))
    assert bsp.version == bsp_q1.BSP_VERSION
    assert len(bsp.entities) == 2
    assert bsp.entities[0]["classname"] == "worldspawn"
    assert bsp.entities[1]["origin"] == "1 2 3"
    assert bsp.vertices == []
    assert bsp.faces == []


def test_wrong_version_rejected() -> None:
    bad = struct.pack("<i", 99) + b"\x00" * (bsp_q1.NUM_LUMPS * 8)
    with pytest.raises(ValueError):
        bsp_q1.read(io.BytesIO(bad))


def test_face_polygon_rejects_invalid_ledge_index() -> None:
    bsp = bsp_q1.Bsp()
    face = bsp_q1.Face(
        plane_id=0, side=0,
        ledge_id=0, ledge_num=1,
        texinfo_id=0,
        typelight=0, baselight=0, light0=0, light1=0,
        lightmap_offset=0,
    )
    with pytest.raises(ValueError, match=r"corrupt BSP: ledge index 0 out of range"):
        bsp.face_polygon(face)


def test_face_polygon_rejects_invalid_edge_index() -> None:
    bsp = bsp_q1.Bsp(ledges=[3], edges=[bsp_q1.Edge(0, 1)])
    face = bsp_q1.Face(
        plane_id=0, side=0,
        ledge_id=0, ledge_num=1,
        texinfo_id=0,
        typelight=0, baselight=0, light0=0, light1=0,
        lightmap_offset=0,
    )
    with pytest.raises(ValueError, match=r"corrupt BSP: edge index 3 out of range"):
        bsp.face_polygon(face)


def test_warns_on_trailing_lump_bytes() -> None:
    with pytest.warns(UserWarning, match=r"trailing bytes"):
        verts = bsp_q1._read_vertices(b"\x00" * 13)
    assert len(verts) == 1


def test_decodes_face_and_texinfo_lumps() -> None:
    texinfo_blob = struct.pack(
        "<8fII",
        1.0, 0.0, 0.0, 16.0,
        0.0, 1.0, 0.0, 32.0,
        7, 9,
    )
    face_blob = struct.pack("<HHiHHBBBBi", 3, 1, 11, 2, 5, 6, 7, 8, 9, 1234)

    bsp = bsp_q1.read(io.BytesIO(_make_bsp({
        bsp_q1.LUMP_TEXINFO: texinfo_blob,
        bsp_q1.LUMP_FACES: face_blob,
    })))

    assert bsp.texinfos == [bsp_q1.TexInfo(
        s_axis=bsp_q1.Vec3(1.0, 0.0, 0.0),
        s_offset=16.0,
        t_axis=bsp_q1.Vec3(0.0, 1.0, 0.0),
        t_offset=32.0,
        miptex_index=7,
        flags=9,
    )]
    assert bsp.faces == [bsp_q1.Face(
        plane_id=3,
        side=1,
        ledge_id=11,
        ledge_num=2,
        texinfo_id=5,
        typelight=6,
        baselight=7,
        light0=8,
        light1=9,
        lightmap_offset=1234,
    )]


def test_rejects_lump_offset_past_eof() -> None:
    blob = _make_bsp(
        {bsp_q1.LUMP_VERTICES: struct.pack("<fff", 1.0, 2.0, 3.0)},
        overrides={bsp_q1.LUMP_VERTICES: (4096, 12)},
    )

    with pytest.raises(ValueError, match=r"offset 4096 beyond end of file"):
        bsp_q1.read(io.BytesIO(blob))


def test_rejects_truncated_lump_data() -> None:
    blob = _make_bsp(
        {bsp_q1.LUMP_VERTICES: struct.pack("<ff", 1.0, 2.0)},
        overrides={bsp_q1.LUMP_VERTICES: (4 + bsp_q1.NUM_LUMPS * 8, 12)},
    )

    with pytest.raises(EOFError, match=r"truncated BSP lump"):
        bsp_q1.read(io.BytesIO(blob))


def test_round_trips_vertex_and_edge_lumps() -> None:
    vertices_blob = struct.pack("<fff", 1.0, 2.0, 3.0) + struct.pack("<fff", 4.0, 5.0, 6.0)
    edges_blob = struct.pack("<HH", 0, 1)
    ledges_blob = struct.pack("<i", 0)
    face_blob = struct.pack("<HHiHHBBBBi", 0, 0, 0, 1, 0, 0, 0, 0, 0, -1)

    bsp = bsp_q1.read(io.BytesIO(_make_bsp({
        bsp_q1.LUMP_VERTICES: vertices_blob,
        bsp_q1.LUMP_EDGES: edges_blob,
        bsp_q1.LUMP_LEDGES: ledges_blob,
        bsp_q1.LUMP_FACES: face_blob,
    })))

    assert bsp.vertices == [bsp_q1.Vec3(1.0, 2.0, 3.0), bsp_q1.Vec3(4.0, 5.0, 6.0)]
    assert bsp.edges == [bsp_q1.Edge(0, 1)]
    assert bsp.ledges == [0]
    assert bsp.face_polygon(bsp.faces[0]) == [0]
