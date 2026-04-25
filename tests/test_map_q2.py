"""Tests for Quake 2 ``.map`` trailing fields (contents flags value)."""

from __future__ import annotations

from quakeblend.formats import map_q2


Q2_MAP = """
{
"classname" "worldspawn"
{
( 0 0 0 ) ( 0 1 0 ) ( 1 0 0 ) e1u1/floor 0 0 0 1 1 1 2 3
( 0 0 0 ) ( 1 0 0 ) ( 0 0 1 ) e1u1/wall  0 0 0 1 1 0 0 0
( 0 0 0 ) ( 0 0 1 ) ( 0 1 0 ) e1u1/sky   0 0 0 1 1 8 4 0
( 1 1 1 ) ( 1 2 1 ) ( 2 1 1 ) e1u1/lava  0 0 0 1 1 9 16 200
}
}
"""


def test_q2_trailing_fields_in_canonical_order() -> None:
    """Quake 2 face syntax stores ``contents flags value`` after the standard fields."""
    mf = map_q2.parse(Q2_MAP)
    brush = mf.entities[0].brushes[0]
    f0, f1, f2, f3 = brush.faces

    # ``1 2 3`` -> contents=1, surface_flags=2, value=3
    assert f0.tex.contents == 1
    assert f0.tex.surface_flags == 2
    assert f0.tex.value == 3

    # All zeros stay zero (and don't get mis-shuffled).
    assert f1.tex.contents == 0
    assert f1.tex.surface_flags == 0
    assert f1.tex.value == 0

    # ``8 4 0`` -> contents=8 (e.g. CONTENTS_LAVA bit), flags=4, value=0.
    assert f2.tex.contents == 8
    assert f2.tex.surface_flags == 4
    assert f2.tex.value == 0

    # Larger value field survives intact.
    assert f3.tex.contents == 9
    assert f3.tex.surface_flags == 16
    assert f3.tex.value == 200


Q2_NO_TRAILING = """
{
"classname" "worldspawn"
{
( 0 0 0 ) ( 0 1 0 ) ( 1 0 0 ) e1u1/floor 0 0 0 1 1
( 0 0 0 ) ( 1 0 0 ) ( 0 0 1 ) e1u1/wall  0 0 0 1 1
( 0 0 0 ) ( 0 0 1 ) ( 0 1 0 ) e1u1/sky   0 0 0 1 1
}
}
"""


def test_q2_trailing_fields_optional() -> None:
    """Faces without trailing tokens default to zero for all three fields."""
    mf = map_q2.parse(Q2_NO_TRAILING)
    for face in mf.entities[0].brushes[0].faces:
        assert face.tex.contents == 0
        assert face.tex.surface_flags == 0
        assert face.tex.value == 0
