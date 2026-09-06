from __future__ import annotations

from io import BytesIO

import pytest

from quakeblend.formats import map_q2, map_transform, map_writer, wal
from quakeblend.formats.common import Vec3
from quakeblend.formats.csg import brush_faces_from_planes
from scripts.q2_compiler_fixture import TEXTURE_NAMES, fixture_level, fixture_wal, write_fixture


def test_q2_fixture_roundtrip_and_transform() -> None:
    restored = map_q2.parse(map_writer.serialize(fixture_level(), dialect="q2", projection="valve220"))
    assert "wad" not in restored.entities[0].properties
    assert len(restored.entities[0].brushes) == 7
    for brush_index, brush in enumerate(restored.entities[0].brushes):
        rings = brush_faces_from_planes([face.plane for face in brush.faces])
        assert len(rings) == 6 and all(len(ring) == 4 for ring in rings)
        for face in brush.faces:
            assert face.tex.is_valve220
            assert face.tex.name == f"quakeblend/{'qb_grid' if brush_index == 6 else 'qb_wall'}"
            assert (face.tex.contents, face.tex.surface_flags, face.tex.value) == (
                (1, 2, 37) if brush_index == 6 else (1, 0, 0)
            )
    restored.entities[0].brushes[6] = map_transform.transform_brush(
        restored.entities[0].brushes[6],
        (Vec3(0, 1.5, 0), Vec3(-0.5, 0, 0), Vec3(0, 0, 1.25)), Vec3(24, -16, 8),
    )
    map_transform.validate_serialized(
        restored, map_writer.serialize(restored, dialect="q2", projection="valve220"),
    )


def test_q2_fixture_wals_have_non_square_original_pixels() -> None:
    for name in TEXTURE_NAMES:
        texture = wal.read_wal(BytesIO(fixture_wal(name)))
        assert texture.name == f"quakeblend/{name}"
        assert (texture.width, texture.height) == (64, 32)
        assert [len(pixels) for pixels in texture.mip_pixels] == [2048, 512, 128, 32]
        assert len(set(texture.pixels)) > 2
        assert (texture.contents, texture.flags, texture.value) == (1, 0, 0)


def test_q2_fixture_refuses_existing_directory(tmp_path) -> None:
    directory = tmp_path / "fixture"
    write_fixture(directory)
    skip = wal.read_wal_path(directory / "textures" / "skip.wal")
    assert skip.name == "skip" and (skip.width, skip.height) == (64, 32)
    original = (directory / "source.map").read_bytes()
    with pytest.raises(FileExistsError):
        write_fixture(directory)
    assert (directory / "source.map").read_bytes() == original
