"""Tests for the brushDef3 parser/serializer."""

from __future__ import annotations

import math

import pytest

from quakeblend.formats import brushdef3, map_q1
from quakeblend.formats.common import Plane, Vec3


CUBE_BRUSHDEF3 = """
( 0 0 1 0 ) ( ( 0.03125 0 0 ) ( 0 0.03125 0 ) ) common/caulk 0 0 0
( 0 0 -1 -16 ) ( ( 0.03125 0 0 ) ( 0 0.03125 0 ) ) common/caulk 0 0 0
( 1 0 0 0 ) ( ( 0.03125 0 0 ) ( 0 0.03125 0 ) ) common/caulk 0 0 0
( -1 0 0 -16 ) ( ( 0.03125 0 0 ) ( 0 0.03125 0 ) ) common/caulk 0 0 0
( 0 1 0 0 ) ( ( 0.03125 0 0 ) ( 0 0.03125 0 ) ) common/caulk 0 0 0
( 0 -1 0 -16 ) ( ( 0.03125 0 0 ) ( 0 0.03125 0 ) ) common/caulk 0 0 0
"""


def test_parse_brushdef3_six_faces() -> None:
    brush = brushdef3.parse_brushdef3_block(CUBE_BRUSHDEF3)
    assert brush.raw_kind == "brushDef3"
    assert len(brush.faces) == 6
    for face in brush.faces:
        assert face.tex.name == "common/caulk"
        assert face.tex.is_brushdef3
        assert face.tex.tex_matrix is not None


def test_parse_brushdef3_plane_normals_match() -> None:
    brush = brushdef3.parse_brushdef3_block(CUBE_BRUSHDEF3)
    expected = [
        Vec3(0, 0, 1), Vec3(0, 0, -1),
        Vec3(1, 0, 0), Vec3(-1, 0, 0),
        Vec3(0, 1, 0), Vec3(0, -1, 0),
    ]
    for face, want in zip(brush.faces, expected):
        got = face.plane.normal
        assert math.isclose(got.x, want.x, abs_tol=1e-4), got
        assert math.isclose(got.y, want.y, abs_tol=1e-4), got
        assert math.isclose(got.z, want.z, abs_tol=1e-4), got


def test_serialize_brushdef3_round_trip() -> None:
    brush = brushdef3.parse_brushdef3_block(CUBE_BRUSHDEF3)
    text = brushdef3.serialize_brushdef3(brush)
    # Strip outer ``brushDef3 { ... }`` wrapper for re-parse.
    inner = "\n".join(text.splitlines()[2:-1])
    again = brushdef3.parse_brushdef3_block(inner)
    assert len(again.faces) == 6
    for f1, f2 in zip(brush.faces, again.faces):
        assert f1.tex.name == f2.tex.name
        assert f1.tex.tex_matrix == f2.tex.tex_matrix
        # Plane equation should match.
        n1, n2 = f1.plane.normal, f2.plane.normal
        assert math.isclose(n1.x, n2.x, abs_tol=1e-4)
        assert math.isclose(n1.y, n2.y, abs_tol=1e-4)
        assert math.isclose(n1.z, n2.z, abs_tol=1e-4)
        assert math.isclose(f1.plane.dist, f2.plane.dist, abs_tol=1e-4)


def test_to_standard_brush_from_raw_payload() -> None:
    """A brush straight from the top-level tokenizer (only raw_payload set,
    no parsed faces) should be reparsed and converted to Standard faces."""
    raw = map_q1.MapBrush(raw_kind="brushDef3", raw_payload=CUBE_BRUSHDEF3)
    converted = brushdef3.to_standard_brush(raw)
    assert converted.raw_kind == "standard"
    assert converted.raw_payload == ""
    assert len(converted.faces) == 6
    for face in converted.faces:
        assert face.tex.name == "common/caulk"
        assert not face.tex.is_brushdef3
        assert face.tex.tex_matrix is None


def test_to_standard_brush_matches_parse_then_convert() -> None:
    """Whether called on an already-parsed brush or a raw-payload-only one,
    the shared helper (used by both map_convert and the MAP import runner)
    must produce identical Standard faces."""
    parsed = brushdef3.parse_brushdef3_block(CUBE_BRUSHDEF3)
    direct = brushdef3.to_standard_brush(parsed)
    from_raw = brushdef3.to_standard_brush(
        map_q1.MapBrush(raw_kind="brushDef3", raw_payload=CUBE_BRUSHDEF3)
    )
    assert len(direct.faces) == len(from_raw.faces) == 6
    for f1, f2 in zip(direct.faces, from_raw.faces):
        assert f1.tex == f2.tex


def test_to_standard_face_decomposes_identity_matrix() -> None:
    brush = brushdef3.parse_brushdef3_block(CUBE_BRUSHDEF3)
    std = brushdef3.to_standard_face(brush.faces[0])
    # 0.03125 = 1/32, so xscale/yscale should be 32.
    assert math.isclose(std.tex.xscale, 32.0, rel_tol=1e-4)
    assert math.isclose(std.tex.yscale, 32.0, rel_tol=1e-4)
    assert math.isclose(std.tex.rotation, 0.0, abs_tol=1e-4)
    assert std.tex.tex_matrix is None  # decomposed away


def test_three_points_round_trip_plane() -> None:
    """Synthesised three points reconstruct the original plane."""
    brush = brushdef3.parse_brushdef3_block(CUBE_BRUSHDEF3)
    for face in brush.faces:
        recovered = Plane.from_points(face.p1, face.p2, face.p3)
        assert math.isclose(recovered.normal.dot(face.plane.normal), 1.0,
                            abs_tol=1e-4)
        assert math.isclose(recovered.dist, face.plane.dist, abs_tol=1e-4)


def test_parse_brushdef3_empty_input() -> None:
    brush = brushdef3.parse_brushdef3_block("")
    assert brush.raw_kind == "brushDef3"
    assert brush.faces == []


def test_parse_brushdef3_truncated_face_raises() -> None:
    payload = "( 0 0 1 0 ) ( ( 0.03125 0 0 ) ( 0 0.03125"
    with pytest.raises(ValueError):
        brushdef3.parse_brushdef3_block(payload)


def test_parse_brushdef3_invalid_plane_float_raises() -> None:
    payload = """
    ( nope 0 1 0 ) ( ( 0.03125 0 0 ) ( 0 0.03125 0 ) ) common/caulk 0 0 0
    """
    with pytest.raises(ValueError):
        brushdef3.parse_brushdef3_block(payload)


def test_parse_brushdef3_missing_parenthesis_raises() -> None:
    payload = """
    ( 0 0 1 0 ( ( 0.03125 0 0 ) ( 0 0.03125 0 ) ) common/caulk 0 0 0
    """
    with pytest.raises(ValueError):
        brushdef3.parse_brushdef3_block(payload)


def test_parse_brushdef3_ignores_trailing_tokens() -> None:
    payload = (
        "( 0 0 1 0 ) ( ( 0.03125 0 0 ) ( 0 0.03125 0 ) ) common/caulk 0 0 0 "
        "trailing junk tokens"
    )
    brush = brushdef3.parse_brushdef3_block(payload)
    assert len(brush.faces) == 1
    assert brush.faces[0].tex.name == "common/caulk"
