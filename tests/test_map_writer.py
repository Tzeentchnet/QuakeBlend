"""Tests for the MAP text writer (``map_writer.serialize`` / ``serialize_path``)."""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

import pytest

from quakeblend.formats import brushdef3, map_q1, map_writer


CUBE_Q1 = """
{
"classname" "worldspawn"
{
( -64 -64 -16 ) ( -64 -63 -16 ) ( -64 -64 -15 ) BRICK1 0 0 0 1 1
( -64 -64 -16 ) ( -64 -64 -15 ) ( -63 -64 -16 ) BRICK1 0 0 0 1 1
( -64 -64 -16 ) ( -63 -64 -16 ) ( -64 -63 -16 ) BRICK1 0 0 0 1 1
( 64 64 16 ) ( 64 64 17 ) ( 64 65 16 ) BRICK1 0 0 0 1 1
( 64 64 16 ) ( 65 64 16 ) ( 64 64 17 ) BRICK1 0 0 0 1 1
( 64 64 16 ) ( 64 65 16 ) ( 65 64 16 ) BRICK1 0 0 0 1 1
}
}
{
"classname" "info_player_start"
"origin" "0 0 24"
}
"""

CUBE_Q2 = """
{
"classname" "worldspawn"
{
( -64 -64 -16 ) ( -64 -63 -16 ) ( -64 -64 -15 ) e1u1/wall 0 0 0 1 1 1 2 3
( -64 -64 -16 ) ( -64 -64 -15 ) ( -63 -64 -16 ) e1u1/wall 0 0 0 1 1 0 0 0
( -64 -64 -16 ) ( -63 -64 -16 ) ( -64 -63 -16 ) e1u1/wall 0 0 0 1 1 4 5 6
( 64 64 16 ) ( 64 64 17 ) ( 64 65 16 ) e1u1/wall 0 0 0 1 1 7 8 9
( 64 64 16 ) ( 65 64 16 ) ( 64 64 17 ) e1u1/wall 0 0 0 1 1 10 11 12
( 64 64 16 ) ( 64 65 16 ) ( 65 64 16 ) e1u1/wall 0 0 0 1 1 13 14 15
}
}
"""

VALVE220 = """
{
"classname" "worldspawn"
{
( 0 0 0 ) ( 0 1 0 ) ( 1 0 0 ) BASE1 [ 1 0 0 0 ] [ 0 -1 0 0 ] 0 1 1
( 0 0 0 ) ( 1 0 0 ) ( 0 0 1 ) BASE1 [ 1 0 0 0 ] [ 0 0 -1 0 ] 0 1 1
( 0 0 0 ) ( 0 0 1 ) ( 0 1 0 ) BASE1 [ 0 1 0 0 ] [ 0 0 -1 0 ] 0 1 1
( 1 1 1 ) ( 1 2 1 ) ( 2 1 1 ) BASE1 [ 1 0 0 0 ] [ 0 -1 0 0 ] 0 1 1
}
}
"""


def _planes_close(a, b, *, tol: float = 1e-3) -> bool:
    if not math.isclose(a.normal.dot(b.normal), 1.0, abs_tol=tol):
        return False
    return math.isclose(a.dist, b.dist, abs_tol=tol)


def _assert_face_round_trip(expected, actual) -> None:
    assert expected.tex.name == actual.tex.name
    assert math.isclose(expected.tex.xoffset, actual.tex.xoffset, abs_tol=1e-6)
    assert math.isclose(expected.tex.yoffset, actual.tex.yoffset, abs_tol=1e-6)
    assert math.isclose(expected.tex.rotation, actual.tex.rotation, abs_tol=1e-6)
    assert math.isclose(expected.tex.xscale, actual.tex.xscale, abs_tol=1e-6)
    assert math.isclose(expected.tex.yscale, actual.tex.yscale, abs_tol=1e-6)
    assert _planes_close(expected.plane, actual.plane)


def _assert_brush_round_trip(expected, actual) -> None:
    assert len(expected.faces) == len(actual.faces)
    for expected_face, actual_face in zip(expected.faces, actual.faces):
        _assert_face_round_trip(expected_face, actual_face)


MULTI_BRUSH_Q1 = """
{
"classname" "worldspawn"
{
( -64 -64 -16 ) ( -64 -63 -16 ) ( -64 -64 -15 ) BRICK1 8 -4 15 0.5 1.25
( -64 -64 -16 ) ( -64 -64 -15 ) ( -63 -64 -16 ) METAL2 -16 12 45 1.5 0.75
( -64 -64 -16 ) ( -63 -64 -16 ) ( -64 -63 -16 ) FLOOR3 3 7 90 2 2.5
( 64 64 16 ) ( 64 64 17 ) ( 64 65 16 ) CEIL4 -2 -8 135 0.25 4
( 64 64 16 ) ( 65 64 16 ) ( 64 64 17 ) TRIM5 11 13 -30 1 0.5
( 64 64 16 ) ( 64 65 16 ) ( 65 64 16 ) LIGHT6 -9 5 270 3 1
}
{
( 96 -64 -16 ) ( 96 -63 -16 ) ( 96 -64 -15 ) STONE1 0 0 0 1 1
( 96 -64 -16 ) ( 96 -64 -15 ) ( 97 -64 -16 ) STONE1 0 0 0 1 1
( 96 -64 -16 ) ( 97 -64 -16 ) ( 96 -63 -16 ) STONE1 0 0 0 1 1
( 160 64 16 ) ( 160 64 17 ) ( 160 65 16 ) STONE1 0 0 0 1 1
( 160 64 16 ) ( 161 64 16 ) ( 160 64 17 ) STONE1 0 0 0 1 1
( 160 64 16 ) ( 160 65 16 ) ( 161 64 16 ) STONE1 0 0 0 1 1
}
}
"""


MULTI_ENTITY_Q1 = """
{
"classname" "worldspawn"
{
( -64 -64 -16 ) ( -64 -63 -16 ) ( -64 -64 -15 ) BRICK1 0 0 0 1 1
( -64 -64 -16 ) ( -64 -64 -15 ) ( -63 -64 -16 ) BRICK1 0 0 0 1 1
( -64 -64 -16 ) ( -63 -64 -16 ) ( -64 -63 -16 ) BRICK1 0 0 0 1 1
( 64 64 16 ) ( 64 64 17 ) ( 64 65 16 ) BRICK1 0 0 0 1 1
( 64 64 16 ) ( 65 64 16 ) ( 64 64 17 ) BRICK1 0 0 0 1 1
( 64 64 16 ) ( 64 65 16 ) ( 65 64 16 ) BRICK1 0 0 0 1 1
}
}
{
"classname" "func_door"
"targetname" "door1"
{
( 96 -64 -16 ) ( 96 -63 -16 ) ( 96 -64 -15 ) METAL1 0 0 0 1 1
( 96 -64 -16 ) ( 96 -64 -15 ) ( 97 -64 -16 ) METAL1 0 0 0 1 1
( 96 -64 -16 ) ( 97 -64 -16 ) ( 96 -63 -16 ) METAL1 0 0 0 1 1
( 160 64 16 ) ( 160 64 17 ) ( 160 65 16 ) METAL1 0 0 0 1 1
( 160 64 16 ) ( 161 64 16 ) ( 160 64 17 ) METAL1 0 0 0 1 1
( 160 64 16 ) ( 160 65 16 ) ( 161 64 16 ) METAL1 0 0 0 1 1
}
{
( 192 -64 -16 ) ( 192 -63 -16 ) ( 192 -64 -15 ) METAL2 0 0 0 1 1
( 192 -64 -16 ) ( 192 -64 -15 ) ( 193 -64 -16 ) METAL2 0 0 0 1 1
( 192 -64 -16 ) ( 193 -64 -16 ) ( 192 -63 -16 ) METAL2 0 0 0 1 1
( 256 64 16 ) ( 256 64 17 ) ( 256 65 16 ) METAL2 0 0 0 1 1
( 256 64 16 ) ( 257 64 16 ) ( 256 64 17 ) METAL2 0 0 0 1 1
( 256 64 16 ) ( 256 65 16 ) ( 257 64 16 ) METAL2 0 0 0 1 1
}
}
{
"classname" "trigger_once"
{
( 320 -64 -16 ) ( 320 -63 -16 ) ( 320 -64 -15 ) TRIGGER1 0 0 0 1 1
( 320 -64 -16 ) ( 320 -64 -15 ) ( 321 -64 -16 ) TRIGGER1 0 0 0 1 1
( 320 -64 -16 ) ( 321 -64 -16 ) ( 320 -63 -16 ) TRIGGER1 0 0 0 1 1
( 384 64 16 ) ( 384 64 17 ) ( 384 65 16 ) TRIGGER1 0 0 0 1 1
( 384 64 16 ) ( 385 64 16 ) ( 384 64 17 ) TRIGGER1 0 0 0 1 1
( 384 64 16 ) ( 384 65 16 ) ( 385 64 16 ) TRIGGER1 0 0 0 1 1
}
}
{
"classname" "info_player_start"
"origin" "0 0 24"
}
"""


def test_q1_round_trip_structural() -> None:
    mf = map_q1.parse(CUBE_Q1)
    text = map_writer.serialize(mf, dialect="q1")
    mf2 = map_q1.parse(text)
    assert len(mf2.entities) == 2
    ws = mf2.entities[0]
    assert ws.properties["classname"] == "worldspawn"
    assert len(ws.brushes[0].faces) == 6
    for f1, f2 in zip(mf.entities[0].brushes[0].faces, ws.brushes[0].faces):
        assert f1.tex.name == f2.tex.name
        assert _planes_close(f1.plane, f2.plane)
    assert mf2.entities[1].properties["origin"] == "0 0 24"


def test_entity_property_escapes_round_trip() -> None:
    source = '{\n"classname" "worldspawn"\n"message" "line 1\\nquote: \\"ok\\" path: c:\\\\quake"\n}\n'
    parsed = map_q1.parse(source)
    assert parsed.entities[0].properties["message"] == 'line 1\nquote: "ok" path: c:\\quake'

    reparsed = map_q1.parse(map_writer.serialize(parsed, dialect="q1"))
    assert reparsed.entities[0].properties == parsed.entities[0].properties


def test_q1_round_trip_multi_brush_entity_preserves_all_brushes() -> None:
    mf = map_q1.parse(MULTI_BRUSH_Q1)
    text = map_writer.serialize(mf, dialect="q1")
    mf2 = map_q1.parse(text)
    expected_entity = mf.entities[0]
    actual_entity = mf2.entities[0]
    assert len(actual_entity.brushes) == len(expected_entity.brushes)
    for expected_brush, actual_brush in zip(expected_entity.brushes, actual_entity.brushes):
        _assert_brush_round_trip(expected_brush, actual_brush)


def test_q1_round_trip_multiple_entities_preserves_brush_counts() -> None:
    mf = map_q1.parse(MULTI_ENTITY_Q1)
    text = map_writer.serialize(mf, dialect="q1")
    mf2 = map_q1.parse(text)
    assert len(mf2.entities) == len(mf.entities)
    assert [ent.properties["classname"] for ent in mf2.entities] == [
        ent.properties["classname"] for ent in mf.entities
    ]
    assert [len(ent.brushes) for ent in mf2.entities] == [len(ent.brushes) for ent in mf.entities]
    assert mf2.entities[1].properties["targetname"] == "door1"
    assert mf2.entities[-1].properties["origin"] == "0 0 24"


def test_q2_round_trip_preserves_trailing_fields() -> None:
    mf = map_q1.parse(CUBE_Q2)
    text = map_writer.serialize(mf, dialect="q2")
    mf2 = map_q1.parse(text)
    brush = mf2.entities[0].brushes[0]
    expected_trailing = [
        (1, 2, 3),
        (0, 0, 0),
        (4, 5, 6),
        (7, 8, 9),
        (10, 11, 12),
        (13, 14, 15),
    ]
    for face, (contents, surface_flags, value) in zip(brush.faces, expected_trailing):
        assert face.tex.contents == contents
        assert face.tex.surface_flags == surface_flags
        assert face.tex.value == value


def test_q1_dialect_strips_q2_trailing_via_writer_round_trip() -> None:
    mf = map_q1.parse(CUBE_Q2)
    # Q1 dialect should NOT emit trailing ints.
    text = map_writer.serialize(mf, dialect="q1")
    assert " 1 2 3" not in text
    mf2 = map_q1.parse(text)
    f0 = mf2.entities[0].brushes[0].faces[0]
    assert f0.tex.contents == 0
    assert f0.tex.surface_flags == 0
    assert f0.tex.value == 0


def test_valve220_round_trip() -> None:
    mf = map_q1.parse(VALVE220)
    text = map_writer.serialize(mf, dialect="q1")
    assert "[ 1 0 0 0 ]" in text
    mf2 = map_q1.parse(text)
    brush = mf2.entities[0].brushes[0]
    assert all(f.tex.is_valve220 for f in brush.faces)


def test_force_standard_strips_valve220() -> None:
    mf = map_q1.parse(VALVE220)
    text = map_writer.serialize(mf, dialect="q1", projection="standard")
    assert "[" not in text


def test_force_valve220_converts_standard_faces() -> None:
    mf = map_q1.parse(MULTI_BRUSH_Q1)
    text = map_writer.serialize(mf, dialect="q1", projection="valve220")
    reparsed = map_q1.parse(text)
    assert all(
        face.tex.is_valve220
        for brush in reparsed.entities[0].brushes
        for face in brush.faces
    )


def test_forced_projection_round_trip_preserves_standard_parameters() -> None:
    original = map_q1.parse(MULTI_BRUSH_Q1)
    valve_text = map_writer.serialize(original, dialect="q1", projection="valve220")
    valve = map_q1.parse(valve_text)
    standard_text = map_writer.serialize(valve, dialect="q1", projection="standard")
    reparsed = map_q1.parse(standard_text)

    expected = original.entities[0].brushes[0].faces[0].tex
    actual = reparsed.entities[0].brushes[0].faces[0].tex
    assert math.isclose(actual.xoffset, expected.xoffset, abs_tol=1e-5)
    assert math.isclose(actual.yoffset, expected.yoffset, abs_tol=1e-5)
    assert math.isclose(actual.rotation, expected.rotation, abs_tol=1e-5)
    assert math.isclose(actual.xscale, expected.xscale, abs_tol=1e-5)
    assert math.isclose(actual.yscale, expected.yscale, abs_tol=1e-5)


def test_forced_standard_reports_sheared_valve220_projection() -> None:
    mf = map_q1.parse(MULTI_BRUSH_Q1)
    face = map_writer._as_valve220(mf.entities[0].brushes[0].faces[0])
    assert face.tex.s_axis is not None and face.tex.t_axis is not None
    face = replace(
        face,
        tex=replace(face.tex, t_axis=face.tex.t_axis + face.tex.s_axis * 0.25),
    )
    mf.entities[0].brushes[0].faces[0] = face

    messages = map_writer.projection_conversion_warnings(mf, "standard")

    assert len(messages) == 1
    assert "entity 0 brush 0 face 0" in messages[0]
    assert "not exactly representable" in messages[0]


Q3_PATCH_AND_BRUSHDEF3 = """
{
"classname" "worldspawn"
{
patchDef2
{
common/clip
( 3 3 0 0 0 )
(
( ( 0 0 0 0 0 ) ( 1 0 0 0.5 0 ) ( 2 0 0 1 0 ) )
( ( 0 1 0 0 0.5 ) ( 1 1 1 0.5 0.5 ) ( 2 1 0 1 0.5 ) )
( ( 0 2 0 0 1 ) ( 1 2 0 0.5 1 ) ( 2 2 0 1 1 ) )
)
}
}
{
brushDef3
{
( 0 0 1 0 ) ( ( 0.03125 0 0 ) ( 0 0.03125 0 ) ) common/caulk 0 0 0
( 0 0 -1 -16 ) ( ( 0.03125 0 0 ) ( 0 0.03125 0 ) ) common/caulk 0 0 0
( 1 0 0 0 ) ( ( 0.03125 0 0 ) ( 0 0.03125 0 ) ) common/caulk 0 0 0
( -1 0 0 -16 ) ( ( 0.03125 0 0 ) ( 0 0.03125 0 ) ) common/caulk 0 0 0
( 0 1 0 0 ) ( ( 0.03125 0 0 ) ( 0 0.03125 0 ) ) common/caulk 0 0 0
( 0 -1 0 -16 ) ( ( 0.03125 0 0 ) ( 0 0.03125 0 ) ) common/caulk 0 0 0
}
}
}
"""


def test_q3_round_trip_preserves_kinds() -> None:
    mf = map_q1.parse(Q3_PATCH_AND_BRUSHDEF3)
    text = map_writer.serialize(mf, dialect="q3")
    mf2 = map_q1.parse(text)
    kinds = [b.raw_kind for b in mf2.entities[0].brushes]
    assert "patchDef2" in kinds
    assert "brushDef3" in kinds
    brush = next(b for b in mf2.entities[0].brushes if b.raw_kind == "brushDef3")
    assert len(brushdef3.parse_brushdef3_block(brush.raw_payload).faces) == 6


def test_q3_patch_raw_payload_preserves_header_comments_and_precision() -> None:
    source = """
    {
    "classname" "worldspawn"
    {
    patchDef2
    {
    // Preserve editor-specific header fields and precision.
    textures/test/patch
    ( 3 3 7 8 9 )
    (
    ( ( 0.123456789 0 0 0 0 ) ( 1 0 0 0.5 0 ) ( 2 0 0 1 0 ) )
    ( ( 0 1 0 0 0.5 ) ( 1 1 1 0.5 0.5 ) ( 2 1 0 1 0.5 ) )
    ( ( 0 2 0 0 1 ) ( 1 2 0 0.5 1 ) ( 2 2 0 1 1 ) )
    )
    }
    }
    }
    """

    output = map_writer.serialize(map_q1.parse(source), dialect="q3")

    assert "// Preserve editor-specific header fields and precision." in output
    assert "( 3 3 7 8 9 )" in output
    assert "0.123456789" in output


def test_serialize_path_does_not_partially_overwrite_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "output.map"
    destination.write_text("existing map", encoding="utf-8")
    original_write_text = Path.write_text

    def fail_after_partial_write(path: Path, text: str, **kwargs) -> int:
        original_write_text(path, text[:8], **kwargs)
        raise OSError("simulated write failure")

    monkeypatch.setattr(Path, "write_text", fail_after_partial_write)

    with pytest.raises(OSError, match="simulated write failure"):
        map_writer.serialize_path(map_q1.parse(CUBE_Q1), destination, dialect="q1")

    assert destination.read_text(encoding="utf-8") == "existing map"
