"""Smoke test for the Quake 2 BSP reader using a tiny synthetic file."""

from __future__ import annotations

import io
import struct

import pytest

from quakeblend.formats import bsp_q2


def _make_minimal_bsp(entity_text: bytes) -> bytes:
    return _make_bsp({bsp_q2.LUMP_ENTITIES: entity_text})


def _make_bsp(
    lumps: dict[int, bytes],
    *,
    overrides: dict[int, tuple[int, int]] | None = None,
) -> bytes:
    header_size = 8 + bsp_q2.NUM_LUMPS * 8  # IBSP + version + lumps
    parts = [b"IBSP", struct.pack("<i", bsp_q2.BSP_VERSION_Q2 if False else 38)]
    cursor = header_size
    for i in range(bsp_q2.NUM_LUMPS):
        blob = lumps.get(i, b"")
        if i in lumps:
            offset, size = overrides.get(i, (cursor, len(blob))) if overrides else (cursor, len(blob))
            parts.append(struct.pack("<ii", offset, size))
            cursor += len(blob)
        else:
            parts.append(struct.pack("<ii", header_size, 0))
    return b"".join(parts) + b"".join(lumps[i] for i in range(bsp_q2.NUM_LUMPS) if i in lumps)


def test_minimal_q2_bsp_parses_entities() -> None:
    text = b'{ "classname" "worldspawn" "sky" "unit1_" }\n{ "classname" "info_player_start" "origin" "0 0 24" }\n\x00'
    blob = _make_minimal_bsp(text)
    bsp = bsp_q2.read(io.BytesIO(blob))
    assert bsp.version == 38
    assert len(bsp.entities) == 2
    assert bsp.entities[0]["classname"] == "worldspawn"
    assert bsp.entities[0]["sky"] == "unit1_"
    assert bsp.entities[1]["origin"] == "0 0 24"


def test_q2_rejects_q1_signature() -> None:
    blob = struct.pack("<i", 29) + b"\x00" * (15 * 8)
    with pytest.raises(ValueError):
        bsp_q2.read(io.BytesIO(blob))


def test_face_polygon_rejects_invalid_surfedge_index() -> None:
    bsp = bsp_q2.Bsp()
    face = bsp_q2.Face(
        plane_id=0, side=0,
        first_edge=0, num_edges=1,
        texinfo_id=0, styles=b"\x00" * 4, lightmap_offset=0,
    )
    with pytest.raises(ValueError, match=r"corrupt BSP: surfedge index 0 out of range"):
        bsp.face_polygon(face)


def test_face_polygon_rejects_invalid_edge_index() -> None:
    bsp = bsp_q2.Bsp(surfedges=[4], edges=[bsp_q2.Edge(0, 1)])
    face = bsp_q2.Face(
        plane_id=0, side=0,
        first_edge=0, num_edges=1,
        texinfo_id=0, styles=b"\x00" * 4, lightmap_offset=0,
    )
    with pytest.raises(ValueError, match=r"corrupt BSP: edge index 4 out of range"):
        bsp.face_polygon(face)


def test_validate_rejects_face_texinfo_out_of_range() -> None:
    bsp = bsp_q2.Bsp(faces=[bsp_q2.Face(
        plane_id=0,
        side=0,
        first_edge=0,
        num_edges=0,
        texinfo_id=0,
        styles=b"\x00" * 4,
        lightmap_offset=-1,
    )])
    with pytest.raises(ValueError, match=r"face 0 texinfo 0 out of range"):
        bsp.validate()


def test_validate_rejects_non_finite_vertex() -> None:
    bsp = bsp_q2.Bsp(vertices=[bsp_q2.Vec3(float("inf"), 0.0, 0.0)])
    with pytest.raises(ValueError, match=r"vertex 0.*finite"):
        bsp.validate()


def test_warns_on_trailing_lump_bytes() -> None:
    with pytest.warns(UserWarning, match=r"trailing bytes"):
        surfedges = bsp_q2._read_surfedges(b"\x00" * 5)
    assert surfedges == [0]


def test_decodes_face_and_texinfo_lumps() -> None:
    texinfo_blob = (
        struct.pack(
            "<8fii",
            1.0, 0.0, 0.0, 8.0,
            0.0, 1.0, 0.0, 12.0,
            3, 4,
        )
        + b"brick/wall".ljust(32, b"\x00")
        + struct.pack("<i", 5)
    )
    face_blob = struct.pack("<HHiHH", 7, 1, 9, 2, 11) + b"\x01\x02\x03\x04" + struct.pack("<i", 123)

    bsp = bsp_q2.read(io.BytesIO(_make_bsp({
        bsp_q2.LUMP_TEXINFO: texinfo_blob,
        bsp_q2.LUMP_FACES: face_blob,
    })))

    assert bsp.texinfos == [bsp_q2.TexInfo(
        u_axis=bsp_q2.Vec3(1.0, 0.0, 0.0),
        u_offset=8.0,
        v_axis=bsp_q2.Vec3(0.0, 1.0, 0.0),
        v_offset=12.0,
        flags=3,
        value=4,
        texture_name="brick/wall",
        next_texinfo=5,
    )]
    assert bsp.faces == [bsp_q2.Face(
        plane_id=7,
        side=1,
        first_edge=9,
        num_edges=2,
        texinfo_id=11,
        styles=b"\x01\x02\x03\x04",
        lightmap_offset=123,
    )]


def test_rejects_lump_offset_past_eof() -> None:
    blob = _make_bsp(
        {bsp_q2.LUMP_TEXINFO: b"x" * 76},
        overrides={bsp_q2.LUMP_TEXINFO: (4096, 76)},
    )

    with pytest.raises(ValueError, match=r"offset 4096 beyond end of file"):
        bsp_q2.read(io.BytesIO(blob))


def test_rejects_truncated_lump_data() -> None:
    header_size = 8 + bsp_q2.NUM_LUMPS * 8
    blob = _make_bsp(
        {bsp_q2.LUMP_TEXINFO: b"x" * 40},
        overrides={bsp_q2.LUMP_TEXINFO: (header_size, 76)},
    )

    with pytest.raises(EOFError, match=r"truncated BSP lump"):
        bsp_q2.read(io.BytesIO(blob))


def test_round_trips_vertex_and_edge_lumps() -> None:
    vertices_blob = struct.pack("<fff", 1.0, 2.0, 3.0) + struct.pack("<fff", 4.0, 5.0, 6.0)
    edges_blob = struct.pack("<HH", 0, 1)
    surfedges_blob = struct.pack("<i", 0)
    face_blob = struct.pack("<HHiHH", 0, 0, 0, 1, 0) + b"\x00" * 4 + struct.pack("<i", -1)

    bsp = bsp_q2.read(io.BytesIO(_make_bsp({
        bsp_q2.LUMP_VERTICES: vertices_blob,
        bsp_q2.LUMP_EDGES: edges_blob,
        bsp_q2.LUMP_SURFEDGES: surfedges_blob,
        bsp_q2.LUMP_FACES: face_blob,
    })))

    assert bsp.vertices == [bsp_q2.Vec3(1.0, 2.0, 3.0), bsp_q2.Vec3(4.0, 5.0, 6.0)]
    assert bsp.edges == [bsp_q2.Edge(0, 1)]
    assert bsp.surfedges == [0]
    assert bsp.face_polygon(bsp.faces[0]) == [0]
