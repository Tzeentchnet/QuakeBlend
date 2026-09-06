from __future__ import annotations

from io import BytesIO

from quakeblend.formats import map_q1, map_transform, map_writer, wad
from quakeblend.formats.common import Vec3
from quakeblend.formats.csg import brush_faces_from_planes
from scripts.q1_compiler_fixture import fixture_level, fixture_wad


def test_compiler_fixture_is_closed_and_serializable() -> None:
    level = fixture_level()
    assert len(level.entities[0].brushes) == 7
    for brush in level.entities[0].brushes:
        rings = brush_faces_from_planes([face.plane for face in brush.faces])
        assert len(rings) == 6
        assert all(len(ring) == 4 for ring in rings)
    restored = map_q1.parse(map_writer.serialize(level, projection="valve220"))
    assert all(face.tex.is_valve220 for brush in restored.entities[0].brushes for face in brush.faces)
    restored.entities[0].brushes[6] = map_transform.transform_brush(
        restored.entities[0].brushes[6],
        (Vec3(0, 1.5, 0), Vec3(-0.5, 0, 0), Vec3(0, 0, 1.25)), Vec3(24, -16, 8),
    )
    map_transform.validate_serialized(restored, map_writer.serialize(restored, projection="valve220"))


def test_compiler_fixture_wad_has_original_non_square_textures() -> None:
    archive = wad.read_wad(BytesIO(fixture_wad()))
    assert {texture.name for texture in archive.textures} == {"qb_wall", "qb_grid", "skip"}
    for texture in archive.textures:
        assert (texture.width, texture.height) == (64, 32)
        assert len(texture.pixels) == 2048
        assert len(set(texture.pixels)) > 2
