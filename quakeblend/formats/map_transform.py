"""Strict source-backed affine brush transforms and serialized-output checks."""

from __future__ import annotations

from dataclasses import replace
import math

from . import map_q1, map_writer
from .common import Vec3
from .csg import brush_faces_from_planes


def _rings(brush):
    if brush.raw_kind != "standard" or len(brush.faces) < 4:
        raise ValueError("Transform export requires plane-defined closed brushes")
    rings = brush_faces_from_planes([face.plane for face in brush.faces])
    if any(len(ring) < 3 for ring in rings):
        raise ValueError("Brush has empty or degenerate source faces")
    planes = [face.plane for face in brush.faces]
    for index, plane in enumerate(planes):
        for other in planes[:index]:
            if (plane.normal - other.normal).length() < 1e-6 and abs(plane.dist - other.dist) < 1e-4:
                raise ValueError("Duplicate source planes are unsupported")
    return rings


def transform_brush(brush: map_q1.MapBrush, columns: tuple[Vec3, Vec3, Vec3],
                    offset: Vec3) -> map_q1.MapBrush:
    """Apply a positive, nonshearing affine edit in game coordinates."""
    if not all(math.isfinite(value) for vector in (*columns, offset) for value in vector):
        raise ValueError("Transform must be finite")
    lengths = [column.length() for column in columns]
    if min(lengths) < 1e-6 or max(lengths) > 1e6:
        raise ValueError("Transform scale is singular or outside supported bounds")
    units = [column * (1 / length) for column, length in zip(columns, lengths)]
    if units[0].dot(units[1].cross(units[2])) <= 0:
        raise ValueError("Reflections are unsupported")
    if any(abs(units[first].dot(units[second])) > 1e-6
           for first, second in ((0, 1), (0, 2), (1, 2))):
        raise ValueError("Shear is unsupported")
    _rings(brush)

    def point(source):
        return sum((column * value for column, value in zip(columns, source)), offset)

    def covector(axis):
        duals = (columns[1].cross(columns[2]), columns[2].cross(columns[0]), columns[0].cross(columns[1]))
        determinant = columns[0].dot(duals[0])
        return sum((dual * (value / determinant) for dual, value in zip(duals, axis)), Vec3(0, 0, 0))

    faces = []
    for face in brush.faces:
        texture = map_writer._as_valve220(face).tex
        if abs(texture.xscale) < 1e-6 or abs(texture.yscale) < 1e-6:
            raise ValueError("Zero or near-zero texture scale is unsupported")
        horizontal = covector(texture.s_axis * (1 / texture.xscale))
        vertical = covector(texture.t_axis * (1 / texture.yscale))
        faces.append(replace(face, p1=point(face.p1), p2=point(face.p2), p3=point(face.p3),
                             tex=replace(texture, s_axis=horizontal, t_axis=vertical,
                                         s_offset=texture.s_offset - horizontal.dot(offset),
                                         t_offset=texture.t_offset - vertical.dot(offset),
                                         xscale=1, yscale=1, rotation=0)))
    result = map_q1.MapBrush(faces)
    original_rings = _rings(brush)
    transformed_rings = _rings(result)
    for original, transformed in zip(original_rings, transformed_rings):
        _match_points([point(vertex) for vertex in original], transformed)
    return result


def _match_points(expected, actual):
    if len(expected) != len(actual):
        raise ValueError("Brush reconstruction changed face topology")
    remaining = list(actual)
    pairs = []
    for point in expected:
        nearest = min(remaining, key=lambda candidate: (candidate - point).length())
        if (nearest - point).length() > 1e-4:
            raise ValueError("Brush reconstruction exceeds geometry tolerance (0.0001 units)")
        remaining.remove(nearest)
        pairs.append((point, nearest))
    return pairs


def validate_serialized(expected: map_q1.MapFile, text: str) -> None:
    """Validate the exact proposed text before atomic destination replacement."""
    actual = map_q1.parse(text.encode("utf-8").decode("latin-1"))
    if len(expected.entities) != len(actual.entities):
        raise ValueError("Serialization changed entity count")
    for source_entity, actual_entity in zip(expected.entities, actual.entities):
        if source_entity.properties != actual_entity.properties or len(source_entity.brushes) != len(actual_entity.brushes):
            raise ValueError("Serialization changed entity ownership or properties")
        for source, restored in zip(source_entity.brushes, actual_entity.brushes):
            if len(source.faces) != len(restored.faces):
                raise ValueError("Serialization changed source face count")
            for face, other, ring, other_ring in zip(source.faces, restored.faces, _rings(source), _rings(restored)):
                if (face.tex.name, face.tex.contents, face.tex.surface_flags, face.tex.value) != (
                        other.tex.name, other.tex.contents, other.tex.surface_flags, other.tex.value):
                    raise ValueError("Serialization changed face metadata")
                pairs = _match_points(ring, other_ring)
                first = map_writer._as_valve220(face).tex
                second = map_writer._as_valve220(other).tex
                for point, other_point in pairs:
                    for axis_name, offset_name, scale_name in (("s_axis", "s_offset", "xscale"),
                                                               ("t_axis", "t_offset", "yscale")):
                        before = point.dot(getattr(first, axis_name)) / getattr(first, scale_name) + getattr(first, offset_name)
                        after = other_point.dot(getattr(second, axis_name)) / getattr(second, scale_name) + getattr(second, offset_name)
                        if not all(math.isfinite(value) for value in (before, after)) or abs(before - after) > 1e-3:
                            raise ValueError("Serialization exceeds UV tolerance (0.001 texture pixels)")
