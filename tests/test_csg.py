"""Tests for the CSG plane-intersection brush builder."""

from __future__ import annotations

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
