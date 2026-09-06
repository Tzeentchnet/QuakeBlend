from __future__ import annotations

import math

import pytest

from quakeblend.formats import map_q1, map_transform, map_writer
from quakeblend.formats.common import Plane, Vec3
from quakeblend.formats.csg import brush_faces_from_planes


def cube(*, wedge=False):
    planes = [Plane(normal, 32) for normal in (Vec3(1, 0, 0), Vec3(-1, 0, 0),
              Vec3(0, 1, 0), Vec3(0, -1, 0), Vec3(0, 0, 1), Vec3(0, 0, -1))]
    if wedge:
        planes = [Plane(Vec3(-1, 0, 0), 0), Plane(Vec3(0, -1, 0), 0),
                  Plane(Vec3(0, 1, 0), 64), Plane(Vec3(0, 0, -1), 0),
                  Plane(Vec3(1, 0, 1).normalized(), 64 / math.sqrt(2))]
    faces = []
    for plane, ring in zip(planes, brush_faces_from_planes(planes)):
        first, second, third = ring[:3]
        if Plane.from_points(first, second, third).normal.dot(plane.normal) < 0:
            second, third = third, second
        faces.append(map_q1.MapFace(first, second, third, map_q1.TexInfo("brick", rotation=23)))
    return map_q1.MapBrush(faces)


def columns(scale=1):
    angle = math.radians(37)
    return (Vec3(math.cos(angle) * scale, math.sin(angle) * scale, 0),
            Vec3(-math.sin(angle), math.cos(angle), 0), Vec3(0, 0, 1))


@pytest.mark.parametrize("scale", [0.5, 1, 2])
@pytest.mark.parametrize("wedge", [False, True])
def test_transform_and_validate(scale, wedge):
    result = map_transform.transform_brush(cube(wedge=wedge), columns(scale), Vec3(123, -45, 17))
    level = map_q1.MapFile([map_q1.MapEntity({"classname": "worldspawn"}, [result])])
    map_transform.validate_serialized(level, map_writer.serialize(level, projection="valve220"))


def test_map_scale_transform_retains_uv_precision():
    result = map_transform.transform_brush(cube(), columns(), Vec3(3000, 1000, 80))
    level = map_q1.MapFile([map_q1.MapEntity({"classname": "worldspawn"}, [result])])
    map_transform.validate_serialized(level, map_writer.serialize(level, projection="valve220"))


@pytest.mark.parametrize("basis,offset", [
    ((Vec3(0, 0, 0), Vec3(0, 1, 0), Vec3(0, 0, 1)), Vec3(0, 0, 0)),
    ((Vec3(-1, 0, 0), Vec3(0, 1, 0), Vec3(0, 0, 1)), Vec3(0, 0, 0)),
    ((Vec3(1, 0, 0), Vec3(1, 1, 0), Vec3(0, 0, 1)), Vec3(0, 0, 0)),
    (columns(), Vec3(float("nan"), 0, 0)),
])
def test_invalid_transforms(basis, offset):
    with pytest.raises(ValueError):
        map_transform.transform_brush(cube(), basis, offset)


def test_precision_loss_rejected():
    result = map_transform.transform_brush(cube(), columns(), Vec3(1_000_000, 0, 0))
    level = map_q1.MapFile([map_q1.MapEntity({"classname": "worldspawn"}, [result])])
    with pytest.raises(ValueError, match="UV tolerance"):
        map_transform.validate_serialized(level, map_writer.serialize(level, projection="valve220"))


def test_duplicate_plane_rejected():
    brush = cube()
    brush.faces.append(brush.faces[0])
    with pytest.raises(ValueError, match="Duplicate"):
        map_transform.transform_brush(brush, columns(), Vec3(0, 0, 0))


def test_serialized_encoding_change_rejected():
    result = map_transform.transform_brush(cube(), columns(), Vec3(0, 0, 0))
    level = map_q1.MapFile([map_q1.MapEntity({"classname": "worldspawn", "message": "caf\u00e9"}, [result])])
    with pytest.raises(ValueError, match="properties"):
        map_transform.validate_serialized(level, map_writer.serialize(level, projection="valve220"))
