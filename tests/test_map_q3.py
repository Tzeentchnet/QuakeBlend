"""End-to-end test: Q3 ``.map`` text → patches via map_q3 + patch parser."""

from __future__ import annotations

from quakeblend.formats import map_q3, patch as patch_mod


Q3_MAP = """
// Game: Quake 3
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


def test_map_q3_patches_iterate() -> None:
    mf = map_q3.parse(Q3_MAP)
    assert map_q3.detect_game(mf) == "q3"
    assert len(mf.entities) == 1
    brushes = mf.entities[0].brushes
    assert {b.raw_kind for b in brushes} == {"patchDef2", "brushDef3"}

    found = list(map_q3.iter_patches(mf))
    assert len(found) == 1
    _ei, _bi, name, p = found[0]
    assert name == "common/clip"
    assert p.width == 3 and p.height == 3
    assert len(p.controls) == 9


def test_map_q3_patch_tessellates() -> None:
    mf = map_q3.parse(Q3_MAP)
    _, _, _, p = next(iter(map_q3.iter_patches(mf)))
    tess = patch_mod.tessellate(p, level=4)
    assert len(tess.vertices) == 25      # (level+1)² for one 3×3 subpatch
    assert len(tess.quads) == 16         # level² quads
