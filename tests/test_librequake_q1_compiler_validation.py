from __future__ import annotations

from dataclasses import replace

import pytest

from quakeblend.formats import bsp_q1, map_q1, map_writer
from quakeblend.formats.common import Vec3
from quakeblend.formats.csg import brush_faces_from_planes
from scripts.q1_compiler_fixture import fixture_level
from scripts.validate_librequake_q1_compiler import (
    EXPECTED_WADS,
    EXPECTED_WARNING,
    TARGET_ENTITY_INDEX,
    TRANSLATION,
    _warning_summary,
    verify_target_bsp,
)


def _source_and_bsp(*, target_present: bool):
    fixture = map_q1.parse(map_writer.serialize(fixture_level(), projection="valve220"))
    brush = fixture.entities[0].brushes[6]
    entities = [map_q1.MapEntity({"classname": "info_null"})
                for _ in range(TARGET_ENTITY_INDEX)]
    entities.append(map_q1.MapEntity({"classname": "func_detail_wall"}, [brush]))
    source = map_q1.MapFile(entities)
    model = bsp_q1.Model(Vec3(-64, -64, -64), Vec3(64, 64, 64), Vec3(0, 0, 0), 0, 0)
    bsp = bsp_q1.Bsp(models=[model, model])
    if not target_present:
        return source, bsp
    rings = brush_faces_from_planes([face.plane for face in brush.faces])
    for source_face, ring in zip(brush.faces, rings):
        assert source_face.tex.s_axis is not None and source_face.tex.t_axis is not None
        moved = [point + TRANSLATION for point in ring]
        start = len(bsp.vertices)
        bsp.vertices.extend(moved)
        first_ledge = len(bsp.ledges)
        for index in range(len(moved)):
            bsp.ledges.append(len(bsp.edges))
            bsp.edges.append(bsp_q1.Edge(start + index, start + (index + 1) % len(moved)))
        s_axis = source_face.tex.s_axis * (1 / source_face.tex.xscale)
        t_axis = source_face.tex.t_axis * (1 / source_face.tex.yscale)
        texinfo_index = len(bsp.texinfos)
        bsp.texinfos.append(bsp_q1.TexInfo(
            s_axis,
            source_face.tex.s_offset - s_axis.dot(TRANSLATION),
            t_axis,
            source_face.tex.t_offset - t_axis.dot(TRANSLATION),
            0,
            0,
        ))
        bsp.faces.append(bsp_q1.Face(
            0, 0, first_ledge, len(moved), texinfo_index, 0, 0, 0, 0, -1
        ))
    return source, bsp


def _warnings(textures: set[str]) -> list[str]:
    lines = [
        f"fs::addArchive: WARNING: archive 'C:/missing/{wad}' not found"
        for wad in EXPECTED_WADS
        for _ in range(2)
    ]
    lines.append("WARNING: No valid WAD filenames in worldmodel")
    for index in range(14):
        lines.append(
            f"WARNING: source.map[line {index + 1}]: brush has multiple face contents "
            "(SOLID vs WATER | TRANSLUCENT | DETAIL), the former will be used."
        )
        lines.append(
            f"WARNING: source.map[line {index + 101}]: brush has multiple face contents "
            "(WATER | TRANSLUCENT | DETAIL vs SOLID), the former will be used."
        )
    lines.extend(f"WARNING: unable to find texture {name}" for name in sorted(textures))
    lines.append("WARNING: 19 sides not found (use -verbose to display)")
    lines.append(EXPECTED_WARNING)
    return lines


def test_warning_summary_accepts_exact_source_categories():
    textures = {f"texture_{index}" for index in range(83)}
    result = _warning_summary("\n".join(_warnings(textures)), textures)
    assert result["total"] == 134
    assert result["unmatched_sides"] == [19]
    assert result["multiple_face_contents"] == {
        "SOLID vs WATER | TRANSLUCENT | DETAIL": 14,
        "WATER | TRANSLUCENT | DETAIL vs SOLID": 14,
    }


@pytest.mark.parametrize("defect", ["unknown", "missing_texture", "sides"])
def test_warning_summary_rejects_changed_categories(defect):
    textures = {f"texture_{index}" for index in range(83)}
    lines = _warnings(textures)
    if defect == "unknown":
        lines.append("WARNING: unexpected compiler behavior")
    elif defect == "missing_texture":
        lines.remove("WARNING: unable to find texture texture_0")
    else:
        lines[lines.index("WARNING: 19 sides not found (use -verbose to display)")] = (
            "WARNING: 20 sides not found (use -verbose to display)"
        )
    with pytest.raises(AssertionError):
        _warning_summary("\n".join(lines), textures)


@pytest.mark.parametrize("target_present", [False, True])
def test_bsp_target_acceptance_recognizes_expected_presence(
    tmp_path, monkeypatch, target_present
):
    source, bsp = _source_and_bsp(target_present=target_present)
    path = tmp_path / "sample.bsp"
    path.write_bytes(b"hash input")
    monkeypatch.setattr(bsp_q1, "read_path", lambda path: bsp)
    result = verify_target_bsp(path, source, expect_present=target_present)
    assert result["target_faces"] == (6 if target_present else 0)
    assert result["maximum_geometry_error_game_units"] == 0
    assert result["maximum_uv_error_pixels"] < 1e-12


@pytest.mark.parametrize("defect", ["uv", "geometry", "missing_face", "version"])
def test_bsp_target_acceptance_rejects_wrong_output(tmp_path, monkeypatch, defect):
    source, bsp = _source_and_bsp(target_present=True)
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
        verify_target_bsp(tmp_path / "sample.bsp", source, expect_present=True)


def test_bsp_baseline_rejects_target_in_moved_volume(tmp_path, monkeypatch):
    source, bsp = _source_and_bsp(target_present=True)
    monkeypatch.setattr(bsp_q1, "read_path", lambda path: bsp)
    with pytest.raises(AssertionError):
        verify_target_bsp(tmp_path / "sample.bsp", source, expect_present=False)
