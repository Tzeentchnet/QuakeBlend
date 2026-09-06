from __future__ import annotations

from dataclasses import replace

import pytest

from quakeblend.formats import bsp_q1, map_q1, map_writer
from quakeblend.formats.common import Vec3
from quakeblend.formats.csg import brush_faces_from_planes
from scripts.q1_compiler_fixture import fixture_level
from scripts.validate_q1_compiler import verify_bsp


def _sample(transformed: bool):
    source = map_q1.parse(map_writer.serialize(fixture_level(), projection="valve220"))
    brush = source.entities[0].brushes[6]
    bsp = bsp_q1.Bsp(
        entities=[{"classname": "info_player_start"}],
        models=[bsp_q1.Model(Vec3(-144, -144, -144), Vec3(144, 144, 144), Vec3(0, 0, 0), 0, 6)],
        miptextures=[bsp_q1.MipTexture("qb_grid", 64, 32, bytes(2048))],
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
        first_ledge = len(bsp.ledges)
        for index in range(len(ring)):
            bsp.ledges.append(len(bsp.edges))
            bsp.edges.append(bsp_q1.Edge(start + index, start + (index + 1) % len(ring)))
        texinfo_index = len(bsp.texinfos)
        bsp.texinfos.append(bsp_q1.TexInfo(axes[0], offsets[0], axes[1], offsets[1], 0, 0))
        bsp.faces.append(bsp_q1.Face(0, 0, first_ledge, len(ring), texinfo_index, 0, 0, 0, 0, -1))
    return source, bsp


@pytest.mark.parametrize("transformed", [False, True])
def test_bsp_acceptance_recognizes_known_geometry_and_uv(tmp_path, monkeypatch, transformed):
    source, bsp = _sample(transformed)
    path = tmp_path / "sample.bsp"
    path.write_bytes(b"hash input")
    monkeypatch.setattr(bsp_q1, "read_path", lambda path: bsp)
    result = verify_bsp(path, source, transformed=transformed)
    assert result["grid_faces"] == 6
    assert result["maximum_geometry_error_game_units"] == 0
    assert result["maximum_uv_error_pixels"] < 1e-12


@pytest.mark.parametrize("defect", ["uv", "geometry", "missing_face", "version"])
def test_bsp_acceptance_rejects_wrong_output(tmp_path, monkeypatch, defect):
    source, bsp = _sample(True)
    if defect == "uv":
        bsp.texinfos[0] = replace(bsp.texinfos[0], s_offset=bsp.texinfos[0].s_offset + 1)
    elif defect == "geometry":
        bsp.vertices[0] = bsp.vertices[0] + Vec3(1, 0, 0)
    elif defect == "missing_face":
        bsp.faces.pop()
    else:
        bsp.version = 30
    monkeypatch.setattr(bsp_q1, "read_path", lambda path: bsp)
    with pytest.raises(AssertionError):
        verify_bsp(tmp_path / "sample.bsp", source, transformed=True)
