from __future__ import annotations

from io import BytesIO

import pytest

from quakeblend.formats import map_q1, wad
from quakeblend.formats.csg import brush_faces_from_planes
from scripts.goldsrc_compiler_fixture import (
    MAP_NAMES, TEXTURE_NAMES, fixture_palette, fixture_text, fixture_wad, write_fixture,
)


@pytest.mark.parametrize("name,landmark", [(MAP_NAMES[0], "96 0 0"), (MAP_NAMES[1], "-96 0 0")])
def test_goldsrc_fixture_closed_brushes_and_connections(name, landmark):
    restored = map_q1.parse(fixture_text(name))
    assert len(restored.entities) == 6
    assert len(restored.entities[0].brushes) == 7
    assert len(restored.entities[3].brushes) == 2
    assert restored.entities[3].brushes[0].faces[0].tex.name == "{qb_mask"
    assert restored.entities[4].properties["origin"] == landmark
    assert restored.entities[5].properties["map"] == next(other for other in MAP_NAMES if other != name)
    for entity in restored.entities:
        for brush in entity.brushes:
            rings = brush_faces_from_planes([face.plane for face in brush.faces])
            assert len(rings) == 6 and all(len(ring) == 4 for ring in rings)
            assert all(face.tex.is_valve220 for face in brush.faces)


def test_goldsrc_fixture_wad3_palettes_mask_and_high_indices():
    archive = wad.read_wad(BytesIO(fixture_wad()))
    assert archive.flavour == "WAD3"
    assert {texture.name for texture in archive.textures} == set(TEXTURE_NAMES)
    for texture in archive.textures:
        assert (texture.width, texture.height) == (64, 32)
        assert texture.palette == fixture_palette()
        assert len(texture.pixels) == 2048
        assert min(texture.pixels) >= 224
        assert (255 in texture.pixels) == texture.name.startswith("{")


def test_goldsrc_fixture_refuses_existing_directory(tmp_path):
    directory = tmp_path / "fixture"
    write_fixture(directory)
    original = (directory / "fixture.wad").read_bytes()
    for name in MAP_NAMES:
        assert (directory / "embedded" / f"{name}.map").read_bytes() == (
            directory / "external" / f"{name}.map"
        ).read_bytes()
    with pytest.raises(FileExistsError):
        write_fixture(directory)
    assert (directory / "fixture.wad").read_bytes() == original
