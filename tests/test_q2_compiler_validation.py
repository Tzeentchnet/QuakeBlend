from __future__ import annotations

import struct
from dataclasses import replace

import pytest

from quakeblend.formats import bsp_q2, map_q2, map_writer
from quakeblend.formats.common import Vec3
from quakeblend.formats.csg import brush_faces_from_planes
from scripts.q2_compiler_fixture import fixture_level
from scripts.validate_q2_compiler import verify_bsp, verify_contents, verify_export


def _contents_blob() -> bytes:
    header = bytearray(b"IBSP" + struct.pack("<i", 38) + bytes(19 * 8))
    brushes = b"".join(struct.pack("<iii", index * 6, 6, 1) for index in range(7))
    sides = b"".join(struct.pack("<Hh", 0, index if brush == 6 else 6)
                     for brush in range(7) for index in range(6))
    struct.pack_into("<ii", header, 8 + bsp_q2.LUMP_BRUSHES * 8, len(header), len(brushes))
    struct.pack_into("<ii", header, 8 + bsp_q2.LUMP_BRUSHSIDES * 8, len(header) + len(brushes), len(sides))
    return bytes(header) + brushes + sides


def _sample(transformed: bool):
    source = map_q2.parse(map_writer.serialize(fixture_level(), dialect="q2", projection="valve220"))
    brush = source.entities[0].brushes[6]
    bsp = bsp_q2.Bsp(
        entities=[{"classname": "info_player_start"}],
        models=[bsp_q2.Model(Vec3(-144, -144, -144), Vec3(144, 144, 144), Vec3(0, 0, 0), 0, 6)],
    )
    for original, ring in zip(brush.faces, brush_faces_from_planes([face.plane for face in brush.faces])):
        texture = original.tex
        axes = [texture.s_axis, texture.t_axis]
        offsets = [texture.s_offset, texture.t_offset]
        if transformed:
            axes = [Vec3(-axis.y / 0.5, axis.x / 1.5, axis.z / 1.25) for axis in axes]
            offsets = [offset - axis.dot(Vec3(24, -16, 8)) for axis, offset in zip(axes, offsets)]
            ring = [Vec3(-point.y * 0.5 + 24, point.x * 1.5 - 16, point.z * 1.25 + 8) for point in ring]
        start = len(bsp.vertices)
        bsp.vertices.extend(ring)
        first_edge = len(bsp.surfedges)
        for index in range(len(ring)):
            bsp.surfedges.append(len(bsp.edges))
            bsp.edges.append(bsp_q2.Edge(start + index, start + (index + 1) % len(ring)))
        texinfo_index = len(bsp.texinfos)
        bsp.texinfos.append(bsp_q2.TexInfo(axes[0], offsets[0], axes[1], offsets[1],
                                        2, 37, "quakeblend/qb_grid", -1))
        bsp.faces.append(bsp_q2.Face(0, 0, first_edge, len(ring), texinfo_index, bytes(4), -1))
    bsp.texinfos.append(bsp_q2.TexInfo(Vec3(1, 0, 0), 0, Vec3(0, 1, 0), 0,
                                    0, 0, "quakeblend/qb_wall", -1))
    return source, bsp


@pytest.mark.parametrize("transformed", [False, True])
def test_q2_bsp_acceptance_geometry_uv_and_metadata(tmp_path, monkeypatch, transformed):
    source, bsp = _sample(transformed)
    path = tmp_path / "sample.bsp"
    path.write_bytes(_contents_blob())
    monkeypatch.setattr(bsp_q2, "read_path", lambda path: bsp)
    result = verify_bsp(path, source, transformed=transformed)
    assert result["grid_faces"] == 6 and result["grid_brushes"] == 1
    assert result["maximum_geometry_error_game_units"] == 0
    assert result["maximum_uv_error_pixels"] < 1e-12


@pytest.mark.parametrize("defect", ["uv", "geometry", "missing_face", "duplicate_face", "version", "flags", "value"])
def test_q2_bsp_acceptance_rejects_wrong_output(tmp_path, monkeypatch, defect):
    source, bsp = _sample(True)
    if defect == "uv":
        bsp.texinfos[0] = replace(bsp.texinfos[0], u_offset=bsp.texinfos[0].u_offset + 1)
    elif defect == "geometry":
        bsp.vertices[0] = bsp.vertices[0] + Vec3(1, 0, 0)
    elif defect == "missing_face":
        bsp.faces.pop()
    elif defect == "duplicate_face":
        bsp.faces.append(bsp.faces[0])
    elif defect == "version":
        bsp.version = 29
    elif defect == "flags":
        bsp.texinfos[0] = replace(bsp.texinfos[0], flags=1)
    else:
        bsp.texinfos[0] = replace(bsp.texinfos[0], value=0)
    monkeypatch.setattr(bsp_q2, "read_path", lambda path: bsp)
    with pytest.raises(AssertionError):
        verify_bsp(tmp_path / "sample.bsp", source, transformed=True)


@pytest.mark.parametrize("defect", ["contents", "bounds", "truncated", "texinfo"])
def test_q2_contents_rejects_wrong_records(defect):
    _, bsp = _sample(False)
    data = bytearray(_contents_blob())
    if defect == "contents":
        struct.pack_into("<i", data, 8 + 19 * 8 + 8, 2)
    elif defect == "bounds":
        struct.pack_into("<i", data, 8 + bsp_q2.LUMP_BRUSHES * 8, -1)
    elif defect == "texinfo":
        struct.pack_into("<h", data, 8 + 19 * 8 + 7 * 12 + 2, 300)
    else:
        data.pop()
    with pytest.raises(AssertionError):
        verify_contents(bytes(data), bsp.texinfos)


@pytest.mark.parametrize("field", ["contents", "surface_flags", "value", "name"])
def test_q2_export_rejects_changed_face_metadata(field):
    source, _ = _sample(False)
    exported, _ = _sample(False)
    verify_export(source, exported)
    face = exported.entities[0].brushes[6].faces[0]
    exported.entities[0].brushes[6].faces[0] = replace(
        face, tex=replace(face.tex, **{field: "wrong" if field == "name" else 999}),
    )
    with pytest.raises(AssertionError):
        verify_export(source, exported)
