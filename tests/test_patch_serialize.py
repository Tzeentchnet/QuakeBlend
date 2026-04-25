"""Round-trip tests for the patchDef2 serializer."""

from __future__ import annotations

import math

from quakeblend.formats import patch as patch_mod


PATCH_BLOCK = """
common/clip
( 3 3 0 0 0 )
(
( ( 0 0 0 0 0 ) ( 1 0 0 0.5 0 ) ( 2 0 0 1 0 ) )
( ( 0 1 0 0 0.5 ) ( 1 1 1 0.5 0.5 ) ( 2 1 0 1 0.5 ) )
( ( 0 2 0 0 1 ) ( 1 2 0 0.5 1 ) ( 2 2 0 1 1 ) )
)
"""


def test_patch_def2_round_trip() -> None:
    name, p = patch_mod.parse_patch_def2_block(PATCH_BLOCK)
    serialized = patch_mod.serialize_patch_def2(name, p)
    # Strip outer ``patchDef2 { ... }`` wrapper for re-parse.
    inner = "\n".join(serialized.splitlines()[2:-1])
    name2, p2 = patch_mod.parse_patch_def2_block(inner)
    assert name == name2 == "common/clip"
    assert p.width == p2.width == 3
    assert p.height == p2.height == 3
    for c1, c2 in zip(p.controls, p2.controls):
        assert math.isclose(c1.pos.x, c2.pos.x, abs_tol=1e-4)
        assert math.isclose(c1.pos.y, c2.pos.y, abs_tol=1e-4)
        assert math.isclose(c1.pos.z, c2.pos.z, abs_tol=1e-4)
        assert math.isclose(c1.uv[0], c2.uv[0], abs_tol=1e-4)
        assert math.isclose(c1.uv[1], c2.uv[1], abs_tol=1e-4)
