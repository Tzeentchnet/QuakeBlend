"""Tests for Q3 Bezier patch tessellation and patchDef2 parsing."""

from __future__ import annotations

import math

import pytest

from quakeblend.formats import patch as patch_mod
from quakeblend.formats.common import Vec3


def _flat_3x3(z: float = 0.0) -> patch_mod.Patch:
    controls = []
    for j in range(3):
        for i in range(3):
            x = float(i)
            y = float(j)
            u = i / 2.0
            v = j / 2.0
            controls.append(patch_mod.Control(Vec3(x, y, z), (u, v)))
    return patch_mod.Patch(width=3, height=3, controls=controls)


def test_flat_patch_vertex_count_and_corners() -> None:
    level = 5
    tess = patch_mod.tessellate(_flat_3x3(), level=level)
    expected = (2 * level + 1) ** 2 // 1  # one subpatch
    # Single 3×3 subpatch → (level+1)² = 36 verts.
    assert len(tess.vertices) == (level + 1) ** 2
    # Corner vertices should match the four corner controls.
    corners = {(0, 0), (2, 0), (0, 2), (2, 2)}
    found = {(round(v.x), round(v.y)) for v in tess.vertices
             if (round(v.x), round(v.y)) in corners}
    assert corners == found


def test_curved_patch_midpoint_lifted() -> None:
    # Centre control lifted in Z; midpoint of the surface should rise.
    p = _flat_3x3()
    centre = p.controls[4]
    p.controls[4] = patch_mod.Control(Vec3(centre.pos.x, centre.pos.y, 1.0), centre.uv)
    tess = patch_mod.tessellate(p, level=2)
    # Find vertex near the centre of the parameter domain (1, 1) in xy.
    middle = min(tess.vertices, key=lambda v: (v.x - 1.0) ** 2 + (v.y - 1.0) ** 2)
    # Bicubic Bezier with only the centre control = 1.0 evaluates to
    # B_1(0.5)² = 0.5² = 0.25 at the parameter centre.
    assert math.isclose(middle.z, 0.25, abs_tol=1e-6)


def test_parse_patch_def2_block() -> None:
    payload = """
    common/clip
    ( 3 3 0 0 0 )
    (
      ( ( 0 0 0 0 0 ) ( 1 0 0 0.5 0 ) ( 2 0 0 1 0 ) )
      ( ( 0 1 0 0 0.5 ) ( 1 1 1 0.5 0.5 ) ( 2 1 0 1 0.5 ) )
      ( ( 0 2 0 0 1 ) ( 1 2 0 0.5 1 ) ( 2 2 0 1 1 ) )
    )
    """
    name, p = patch_mod.parse_patch_def2_block(payload)
    assert name == "common/clip"
    assert p.width == 3 and p.height == 3
    assert len(p.controls) == 9
    centre = p.controls[4]
    assert math.isclose(centre.pos.z, 1.0)
    assert centre.uv == (0.5, 0.5)


def test_parse_patch_def2_missing_closing_paren_raises() -> None:
    payload = """
    common/clip
    ( 3 3 0 0 0 )
    (
      ( ( 0 0 0 0 0 ) ( 1 0 0 0.5 0 ) ( 2 0 0 1 0 ) )
      ( ( 0 1 0 0 0.5 ) ( 1 1 1 0.5 0.5 ) ( 2 1 0 1 0.5 ) )
      ( ( 0 2 0 0 1 ) ( 1 2 0 0.5 1 ) ( 2 2 0 1 1 ) )
    """
    with pytest.raises(ValueError):
        patch_mod.parse_patch_def2_block(payload)


def test_tessellate_rejects_level_below_one() -> None:
    with pytest.raises(ValueError):
        patch_mod.tessellate(_flat_3x3(), level=0)


def test_tessellate_minimum_valid_patch() -> None:
    tess = patch_mod.tessellate(_flat_3x3(), level=1)
    assert len(tess.vertices) == 4
    assert len(tess.quads) == 1
    assert tess.quads == [(0, 1, 3, 2)]


def test_parse_patch_def2_zero_sized_grid() -> None:
    name, p = patch_mod.parse_patch_def2_block(
        """
        common/clip
        ( 0 0 0 0 0 )
        (
        )
        """
    )
    assert name == "common/clip"
    assert p.width == 0 and p.height == 0
    assert p.controls == []
    with pytest.raises(ValueError):
        patch_mod.tessellate(p)
