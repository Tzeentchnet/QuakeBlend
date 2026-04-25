"""Tests for the MAP text writer (``map_writer.serialize`` / ``serialize_path``)."""

from __future__ import annotations

import math

from quakeblend.formats import map_q1, map_writer


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
( -64 -64 -16 ) ( -63 -64 -16 ) ( -64 -63 -16 ) e1u1/wall 0 0 0 1 1 4 0 0
( 64 64 16 ) ( 64 64 17 ) ( 64 65 16 ) e1u1/wall 0 0 0 1 1 0 0 0
( 64 64 16 ) ( 65 64 16 ) ( 64 64 17 ) e1u1/wall 0 0 0 1 1 0 0 0
( 64 64 16 ) ( 64 65 16 ) ( 65 64 16 ) e1u1/wall 0 0 0 1 1 0 0 0
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


def test_q2_round_trip_preserves_trailing_fields() -> None:
    mf = map_q1.parse(CUBE_Q2)
    text = map_writer.serialize(mf, dialect="q2")
    mf2 = map_q1.parse(text)
    f0 = mf2.entities[0].brushes[0].faces[0]
    assert f0.tex.contents == 1
    assert f0.tex.surface_flags == 2
    assert f0.tex.value == 3
    f2 = mf2.entities[0].brushes[0].faces[2]
    assert f2.tex.contents == 4


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
