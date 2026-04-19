"""Tests for the Quake .map text parser."""

from __future__ import annotations

from quakeblend.formats import map_q1


CUBE_MAP = """
{
"classname" "worldspawn"
{
( -64 -64 -16 ) ( -64 -63 -16 ) ( -64 -64 -15 ) BRICK1 0 0 0 1 1
( -64 -64 -16 ) ( -64 -64 -15 ) ( -63 -64 -16 ) BRICK1 0 0 0 1 1
( -64 -64 -16 ) ( -63 -64 -16 ) ( -64 -63 -16 ) BRICK1 0 0 0 1 1
( 64 64 16 )    ( 64 64 17 )    ( 64 65 16 )    BRICK1 0 0 0 1 1
( 64 64 16 )    ( 65 64 16 )    ( 64 64 17 )    BRICK1 0 0 0 1 1
( 64 64 16 )    ( 64 65 16 )    ( 65 64 16 )    BRICK1 0 0 0 1 1
}
}
{
"classname" "info_player_start"
"origin" "0 0 24"
}
"""


def test_parse_basic_map() -> None:
    mf = map_q1.parse(CUBE_MAP)
    assert len(mf.entities) == 2
    ws = mf.entities[0]
    assert ws.properties["classname"] == "worldspawn"
    assert len(ws.brushes) == 1
    brush = ws.brushes[0]
    assert brush.raw_kind == "standard"
    assert len(brush.faces) == 6
    for face in brush.faces:
        assert face.tex.name == "BRICK1"
        assert not face.tex.is_valve220

    pls = mf.entities[1]
    assert pls.properties["classname"] == "info_player_start"
    assert pls.properties["origin"] == "0 0 24"


VALVE_FACE = """
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


def test_valve220_detection() -> None:
    mf = map_q1.parse(VALVE_FACE)
    brush = mf.entities[0].brushes[0]
    assert all(f.tex.is_valve220 for f in brush.faces)
    assert brush.faces[0].tex.s_axis is not None


Q3_PATCH_MAP = """
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
}
"""


def test_q3_patch_captured_verbatim() -> None:
    mf = map_q1.parse(Q3_PATCH_MAP)
    brush = mf.entities[0].brushes[0]
    assert brush.raw_kind == "patchDef2"
    assert "common/clip" in brush.raw_payload
