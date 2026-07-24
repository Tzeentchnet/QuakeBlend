"""Tests for the CSG plane-intersection brush builder."""

from __future__ import annotations

import pytest

from quakeblend.formats.common import Plane, Vec3
from quakeblend.formats.csg import brush_faces_from_planes


def _axis_aligned_cube(size: float = 1.0):
    """Return six planes whose intersection is the cube [-size, size]^3."""
    s = size
    return [
        Plane(Vec3(+1, 0, 0), s),  # x <= +s
        Plane(Vec3(-1, 0, 0), s),  # x >= -s
        Plane(Vec3(0, +1, 0), s),
        Plane(Vec3(0, -1, 0), s),
        Plane(Vec3(0, 0, +1), s),
        Plane(Vec3(0, 0, -1), s),
    ]


def test_cube_yields_six_quads_with_eight_unique_vertices() -> None:
    rings = brush_faces_from_planes(_axis_aligned_cube(1.0))
    assert len(rings) == 6
    for ring in rings:
        assert len(ring) == 4, "each cube face should be a quad"

    # Collect unique vertices.
    flat = [v for ring in rings for v in ring]
    unique: list[Vec3] = []
    for v in flat:
        if not any((v - u).dot(v - u) < 1e-6 for u in unique):
            unique.append(v)
    assert len(unique) == 8


def test_pyramid_yields_five_vertices() -> None:
    # Square base + four slanted faces meeting at a single apex.
    apex = Vec3(0, 0, 2)
    base_corners = [Vec3(1, 1, 0), Vec3(-1, 1, 0), Vec3(-1, -1, 0), Vec3(1, -1, 0)]
    planes = [Plane(Vec3(0, 0, -1), 0.0)]   # base: z >= 0
    # Each slanted face: built from apex + two adjacent base corners.
    for i in range(4):
        a = base_corners[i]
        b = base_corners[(i + 1) % 4]
        # Outward normal of the half-space (normal · p <= dist):
        # use (a - apex) x (b - apex) so the normal points away from the
        # opposite base corner.
        n = (a - apex).cross(b - apex).normalized()
        d = n.dot(apex)
        planes.append(Plane(n, d))

    rings = brush_faces_from_planes(planes, epsilon=0.05)
    flat = [v for ring in rings for v in ring]
    unique: list[Vec3] = []
    for v in flat:
        if not any((v - u).dot(v - u) < 1e-3 for u in unique):
            unique.append(v)
    assert len(unique) == 5
    # Base ring must be a quad.
    assert len(rings[0]) == 4
    # Each slanted ring must be a triangle.
    for ring in rings[1:]:
        assert len(ring) == 3


def test_duplicate_planes_do_not_duplicate_vertices() -> None:
    # Mappers frequently leave coincident planes behind; the extra copies must
    # not add phantom vertices to the neighbouring rings.
    planes = _axis_aligned_cube(1.0)
    planes.append(Plane(Vec3(+1, 0, 0), 1.0))
    rings = brush_faces_from_planes(planes)
    for ring in rings:
        if not ring:
            continue
        assert len(ring) == 4
        for i, v in enumerate(ring):
            for u in ring[i + 1:]:
                assert (v - u).dot(v - u) > 1e-6


def test_parallel_non_coincident_planes_clip_the_brush() -> None:
    # A second x <= 0.5 plane must shrink the brush rather than confuse it.
    planes = _axis_aligned_cube(1.0)
    planes.append(Plane(Vec3(+1, 0, 0), 0.5))
    rings = brush_faces_from_planes(planes)
    xs = [v.x for ring in rings for v in ring]
    assert max(xs) == pytest.approx(0.5)
    assert min(xs) == pytest.approx(-1.0)


def test_chamfered_cube_yields_octagons_and_triangles() -> None:
    # Cube with all eight corners cut off: every original face becomes an
    # octagon and every corner becomes a triangle.
    planes = _axis_aligned_cube(1.0)
    for sx in (+1, -1):
        for sy in (+1, -1):
            for sz in (+1, -1):
                n = Vec3(sx, sy, sz).normalized()
                planes.append(Plane(n, n.dot(Vec3(sx, sy, sz)) * 0.9))
    rings = brush_faces_from_planes(planes)
    non_empty = [r for r in rings if r]
    assert len(non_empty) == 14
    assert sum(1 for r in non_empty if len(r) == 3) == 8
    assert sum(1 for r in non_empty if len(r) == 8) == 6


def test_plane_through_a_single_corner_keeps_the_cube_intact() -> None:
    # Four planes meet exactly at (1, 1, 1); the extra plane touches the brush
    # without removing volume, so the cube must survive unchanged.
    planes = _axis_aligned_cube(1.0)
    n = Vec3(1, 1, 1).normalized()
    planes.append(Plane(n, n.dot(Vec3(1, 1, 1))))
    rings = brush_faces_from_planes(planes)
    assert sum(1 for r in rings if len(r) == 4) == 6
    unique: list[Vec3] = []
    for v in (v for ring in rings for v in ring):
        if not any((v - u).dot(v - u) < 1e-6 for u in unique):
            unique.append(v)
    assert len(unique) == 8


def test_open_plane_set_yields_no_geometry() -> None:
    # Three planes cannot bound a closed volume; the builder must return empty
    # rings instead of raising or emitting unbounded polygons.
    planes = [
        Plane(Vec3(+1, 0, 0), 1.0),
        Plane(Vec3(0, +1, 0), 1.0),
        Plane(Vec3(0, 0, +1), 1.0),
    ]
    rings = brush_faces_from_planes(planes)
    assert len(rings) == 3
    assert all(len(ring) == 0 for ring in rings)


def test_degenerate_brush_with_contradictory_planes_is_empty() -> None:
    # x <= -2 and x >= 2 cannot both hold: no vertices survive the inside test.
    planes = _axis_aligned_cube(1.0)
    planes.append(Plane(Vec3(+1, 0, 0), -2.0))
    rings = brush_faces_from_planes(planes)
    assert all(len(ring) == 0 for ring in rings)
