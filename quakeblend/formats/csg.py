"""Convex Solid Geometry (CSG) → mesh.

A Quake brush is the intersection of N half-spaces. To convert it to a
renderable polygon mesh:

1. Compute every triple-plane intersection point.
2. Discard points that lie outside any half-space (epsilon-tolerant).
3. For each plane, keep the surviving points whose signed distance to that
   plane is ≈ 0; sort them around the plane's normal to produce a convex
   polygon (one face per plane).

This algorithm is the textbook approach used by every Quake map compiler
since 1996. It does not require an external convex-hull library.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, List, Sequence

from ..utils.constants import CSG_EPSILON
from .common import Plane, Vec3


@dataclass(frozen=True)
class BrushFace:
    """One face of a brush solid: an ordered ring of vertices."""
    plane: Plane
    vertices: tuple[Vec3, ...]
    texture: str = ""
    # Optional per-face metadata propagated from the source format:
    metadata: dict | None = None


# ------------------------------------------------------------- triple solve


def _intersect_three_planes(a: Plane, b: Plane, c: Plane) -> Vec3 | None:
    """Solve the 3×3 linear system; return ``None`` if planes are parallel."""
    n1, n2, n3 = a.normal, b.normal, c.normal
    d1, d2, d3 = a.dist, b.dist, c.dist
    cross23 = n2.cross(n3)
    denom = n1.dot(cross23)
    if abs(denom) < 1e-9:
        return None
    cross31 = n3.cross(n1)
    cross12 = n1.cross(n2)
    p = (cross23 * d1) + (cross31 * d2) + (cross12 * d3)
    return Vec3(p.x / denom, p.y / denom, p.z / denom)


# ----------------------------------------------------------- main converter


def brush_faces_from_planes(planes: Sequence[Plane], *,
                            epsilon: float = CSG_EPSILON) -> List[List[Vec3]]:
    """Return, for each input plane, the convex polygon ring of vertices on it.

    Empty rings (fewer than 3 vertices) are returned as ``[]`` so the caller
    can detect degenerate faces.
    """
    n = len(planes)
    if n < 4:
        return [[] for _ in planes]

    # Find all candidate vertices.
    candidates: list[tuple[Vec3, frozenset[int]]] = []
    for i in range(n):
        for j in range(i + 1, n):
            for k in range(j + 1, n):
                p = _intersect_three_planes(planes[i], planes[j], planes[k])
                if p is None:
                    continue
                # Reject if outside the brush (any plane reports positive distance).
                inside = True
                for m, plane in enumerate(planes):
                    if m in (i, j, k):
                        continue
                    if plane.signed_distance(p) > epsilon:
                        inside = False
                        break
                if inside:
                    candidates.append((p, frozenset((i, j, k))))

    # Group candidates per plane (a vertex belongs to plane idx if its
    # generating triple includes idx, OR if it lies on that plane within eps).
    rings: list[list[Vec3]] = [[] for _ in range(n)]
    for plane_idx, plane in enumerate(planes):
        plane_verts: list[Vec3] = []
        for p, triple in candidates:
            if plane_idx in triple or abs(plane.signed_distance(p)) <= epsilon:
                # Deduplicate (vertices on >3 planes are produced multiple times).
                if not any(_close(p, q, epsilon) for q in plane_verts):
                    plane_verts.append(p)
        if len(plane_verts) >= 3:
            rings[plane_idx] = _sort_ccw(plane_verts, plane.normal)
    return rings


def brush_faces(planes: Sequence[Plane], face_textures: Sequence[str] | None = None,
                *, epsilon: float = CSG_EPSILON) -> List[BrushFace]:
    """High-level helper: pair each face polygon with its plane and texture name."""
    rings = brush_faces_from_planes(planes, epsilon=epsilon)
    out: list[BrushFace] = []
    for i, (plane, ring) in enumerate(zip(planes, rings)):
        tex = face_textures[i] if face_textures and i < len(face_textures) else ""
        out.append(BrushFace(plane=plane, vertices=tuple(ring), texture=tex))
    return out


# ------------------------------------------------------------------- helpers


def _close(a: Vec3, b: Vec3, eps: float) -> bool:
    d = a - b
    return d.dot(d) < eps * eps


def _sort_ccw(points: Iterable[Vec3], normal: Vec3) -> List[Vec3]:
    pts = list(points)
    if len(pts) < 3:
        return pts
    centroid = Vec3(
        sum(p.x for p in pts) / len(pts),
        sum(p.y for p in pts) / len(pts),
        sum(p.z for p in pts) / len(pts),
    )
    # Build an orthonormal basis on the plane.
    n = normal.normalized()
    # Pick a non-parallel reference axis.
    ref = Vec3(0, 0, 1) if abs(n.z) < 0.9 else Vec3(1, 0, 0)
    u = (ref - n * n.dot(ref)).normalized()
    v = n.cross(u)

    def angle(p: Vec3) -> float:
        rel = p - centroid
        return math.atan2(rel.dot(v), rel.dot(u))

    pts.sort(key=angle)
    return pts
