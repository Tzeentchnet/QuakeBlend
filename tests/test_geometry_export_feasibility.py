"""Test-only affine export experiment; no production scene-export API."""

from __future__ import annotations

from dataclasses import dataclass, replace
import math

import pytest

from quakeblend.formats import brushdef3, map_q1, map_writer
from quakeblend.formats.common import Plane, Vec3
from quakeblend.formats.csg import brush_faces_from_planes


@dataclass(frozen=True)
class _AffineProbe:
    scale: Vec3 = Vec3(1, 1, 1)
    angle: float = 0
    shear: float = 0
    shift: Vec3 = Vec3(0, 0, 0)

    def point(self, point: Vec3) -> Vec3:
        cosine = math.cos(math.radians(self.angle))
        sine = math.sin(math.radians(self.angle))
        return Vec3(
            self.scale.x * (cosine * point.x - sine * point.y) + self.shear * point.z,
            self.scale.y * (sine * point.x + cosine * point.y),
            self.scale.z * point.z,
        ) + self.shift

    def covector(self, axis: Vec3) -> Vec3:
        cosine = math.cos(math.radians(self.angle))
        sine = math.sin(math.radians(self.angle))
        horizontal = (cosine * axis.x - sine * axis.y) / self.scale.x
        vertical = (sine * axis.x + cosine * axis.y) / self.scale.y
        return Vec3(horizontal, vertical, (axis.z - self.shear * horizontal) / self.scale.z)


def _brush(shape: str, projection: str) -> map_q1.MapBrush:
    if shape == "cube":
        planes = [Plane(normal, 32) for normal in (
            Vec3(1, 0, 0), Vec3(-1, 0, 0), Vec3(0, 1, 0),
            Vec3(0, -1, 0), Vec3(0, 0, 1), Vec3(0, 0, -1),
        )]
    else:
        planes = [Plane(Vec3(-1, 0, 0), 0), Plane(Vec3(0, -1, 0), 0),
                  Plane(Vec3(0, 1, 0), 64), Plane(Vec3(0, 0, -1), 0),
                  Plane(Vec3(1, 0, 1).normalized(), 64 / math.sqrt(2))]
    faces = []
    for index, (plane, ring) in enumerate(zip(planes, brush_faces_from_planes(planes))):
        assert len(ring) >= 3
        first, second, third = ring[:3]
        if Plane.from_points(first, second, third).normal.dot(plane.normal) < 0:
            second, third = third, second
        texture = map_q1.TexInfo(
            name=f"probe/face{index}", xoffset=13.25, yoffset=-7.5, rotation=23,
            xscale=-0.75, yscale=1.25, contents=index + 1, surface_flags=index + 2,
            value=index + 3, has_q2_trailing_fields=True,
        )
        face = map_q1.MapFace(first, second, third, texture)
        if projection == "valve220":
            face = map_writer._as_valve220(face)
            face = replace(face, tex=replace(face.tex, t_axis=face.tex.t_axis + face.tex.s_axis * 0.2))
        faces.append(face)
    return map_q1.MapBrush(faces)


def _pixels(face: map_q1.MapFace, point: Vec3) -> tuple[float, float]:
    texture = face.tex
    if texture.is_valve220:
        return (point.dot(texture.s_axis) / texture.xscale + texture.s_offset,
                point.dot(texture.t_axis) / texture.yscale + texture.t_offset)
    horizontal, vertical = brushdef3.base_axes_for_normal(face.plane.normal)
    cosine = math.cos(math.radians(texture.rotation))
    sine = math.sin(math.radians(texture.rotation))
    return ((point.dot(horizontal) * cosine - point.dot(vertical) * sine) / texture.xscale + texture.xoffset,
            (point.dot(horizontal) * sine + point.dot(vertical) * cosine) / texture.yscale + texture.yoffset)


def _transform(brush: map_q1.MapBrush, transform: _AffineProbe) -> map_q1.MapBrush:
    faces = []
    for source in brush.faces:
        texture = map_writer._as_valve220(source).tex
        horizontal = transform.covector(texture.s_axis * (1 / texture.xscale))
        vertical = transform.covector(texture.t_axis * (1 / texture.yscale))
        points = [transform.point(point) for point in (source.p1, source.p2, source.p3)]
        if transform.scale.x * transform.scale.y * transform.scale.z < 0:
            points[1], points[2] = points[2], points[1]
        faces.append(map_q1.MapFace(*points, replace(
            texture, s_axis=horizontal, t_axis=vertical,
            s_offset=texture.s_offset - horizontal.dot(transform.shift),
            t_offset=texture.t_offset - vertical.dot(transform.shift),
            rotation=0, xscale=1, yscale=1,
        )))
    return map_q1.MapBrush(faces)


_TRANSFORMS = [
    pytest.param(_AffineProbe(), id="identity"),
    pytest.param(_AffineProbe(shift=Vec3(123.25, -45.5, 17.125)), id="translation"),
    pytest.param(_AffineProbe(angle=37), id="rotation"),
    pytest.param(_AffineProbe(scale=Vec3(2, 2, 2)), id="uniform-scale"),
    pytest.param(_AffineProbe(scale=Vec3(2, 0.5, 1.5), angle=37,
                              shift=Vec3(123.25, -45.5, 17.125)), id="nonuniform-combined"),
    pytest.param(_AffineProbe(angle=37, shear=0.375), id="shear"),
    pytest.param(_AffineProbe(scale=Vec3(-1, 2, 0.5), angle=37), id="reflection"),
]


@pytest.mark.parametrize("shape", ["cube", "wedge"])
@pytest.mark.parametrize("projection", ["standard", "valve220"])
@pytest.mark.parametrize("dialect", ["q1", "q2"])
@pytest.mark.parametrize("transform", _TRANSFORMS)
def test_affine_brush_roundtrip(shape, projection, dialect, transform):
    source = _brush(shape, projection)
    changed = _transform(source, transform)
    properties = {"classname": "func_wall", "targetname": "probe"}
    level = map_q1.MapFile([map_q1.MapEntity({"classname": "worldspawn"}),
                            map_q1.MapEntity(properties, [changed])])
    result = map_q1.parse(map_writer.serialize(level, dialect=dialect, projection="valve220"))
    assert result.entities[1].properties == properties
    assert not result.entities[0].brushes
    restored = result.entities[1].brushes[0]
    source_rings = brush_faces_from_planes([face.plane for face in source.faces])
    restored_rings = brush_faces_from_planes([face.plane for face in restored.faces])
    for original, exported, original_ring, restored_ring in zip(
            source.faces, restored.faces, source_rings, restored_rings):
        assert len(original_ring) == len(restored_ring)
        assert original.tex.name == exported.tex.name
        if dialect == "q2":
            assert (exported.tex.contents, exported.tex.surface_flags, exported.tex.value) == (
                original.tex.contents, original.tex.surface_flags, original.tex.value,
            )
        transformed_normal = transform.covector(original.plane.normal).normalized()
        assert exported.plane.normal.dot(transformed_normal) > 1 - 1e-8
        for point in original_ring:
            expected_point = transform.point(point)
            nearest = min(restored_ring, key=lambda candidate: (candidate - expected_point).length())
            assert (nearest - expected_point).length() < 1e-4
            assert _pixels(exported, nearest) == pytest.approx(_pixels(original, point), abs=1e-3)


def test_large_coordinates_expose_writer_uv_precision():
    source = _brush("cube", "standard")
    transform = _AffineProbe(angle=37, shift=Vec3(1_000_000, 0, 0))
    changed = _transform(source, transform)
    level = map_q1.MapFile([map_q1.MapEntity({"classname": "worldspawn"}, [changed])])
    restored = map_q1.parse(map_writer.serialize(level, projection="valve220")).entities[0].brushes[0]
    errors = []
    for original, unrounded, exported in zip(source.faces, changed.faces, restored.faces):
        point = transform.point(original.p1)
        expected = _pixels(original, original.p1)
        assert _pixels(unrounded, point) == pytest.approx(expected, abs=1e-8)
        errors.extend(abs(actual - reference) for actual, reference in zip(_pixels(exported, point), expected))
    assert max(errors) > 1e-3
    print(f"Large-coordinate probe maximum UV error: {max(errors):.9f} texture pixels")
