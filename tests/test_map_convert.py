"""Tests for the cross-game MAP converter."""

from __future__ import annotations

from quakeblend.formats import csg, map_convert, map_q1, map_q3, map_writer
from quakeblend.formats.common import Vec3


CUBE_Q2 = """
{
"classname" "worldspawn"
{
( -64 -64 -16 ) ( -64 -63 -16 ) ( -64 -64 -15 ) e1u1/wall 0 0 0 1 1 1 2 3
( -64 -64 -16 ) ( -64 -64 -15 ) ( -63 -64 -16 ) e1u1/wall 0 0 0 1 1 0 0 0
( -64 -64 -16 ) ( -63 -64 -16 ) ( -64 -63 -16 ) e1u1/wall 0 0 0 1 1 0 0 0
( 64 64 16 ) ( 64 64 17 ) ( 64 65 16 ) e1u1/wall 0 0 0 1 1 0 0 0
( 64 64 16 ) ( 65 64 16 ) ( 64 64 17 ) e1u1/wall 0 0 0 1 1 0 0 0
( 64 64 16 ) ( 64 65 16 ) ( 65 64 16 ) e1u1/wall 0 0 0 1 1 0 0 0
}
}
"""


CUBE_Q1 = """
{
"classname" "worldspawn"
{
( -64 -64 -16 ) ( -64 -63 -16 ) ( -64 -64 -15 ) BRICK1 0 0 0 1 1
( -64 -64 -16 ) ( -64 -64 -15 ) ( -63 -64 -16 ) BRICK1 0 0 0 1 1
( -64 -64 -16 ) ( -63 -64 -16 ) ( -64 -63 -16 ) BRICK1 0 0 0 1 1
( 64 64 16 ) ( 64 64 17 ) ( 64 65 16 ) BRICK1 0 0 0 1 1
( 64 64 16 ) ( 65 64 16 ) ( 64 64 17 ) BRICK1 0 0 0 1 1
( 64 64 16 ) ( 64 65 16 ) ( 65 64 16 ) BRICK1 0 0 0 1 1
}
}
"""


Q3_MAP = """
{
"classname" "worldspawn"
{
patchDef2
{
common/clip
( 3 3 0 0 0 )
(
( ( 0 0 0 0 0 ) ( 1 0 0 0.5 0 ) ( 2 0 0 1 0 ) )
( ( 0 1 0 0 0.5 ) ( 1 1 1 0.5 0.5 ) ( 2 1 0 1 0.5 ) )
( ( 0 2 0 0 1 ) ( 1 2 0 0.5 1 ) ( 2 2 0 1 1 ) )
)
}
}
{
brushDef3
{
( 0 0 1 0 ) ( ( 0.03125 0 0 ) ( 0 0.03125 0 ) ) common/caulk 0 0 0
( 0 0 -1 -16 ) ( ( 0.03125 0 0 ) ( 0 0.03125 0 ) ) common/caulk 0 0 0
( 1 0 0 0 ) ( ( 0.03125 0 0 ) ( 0 0.03125 0 ) ) common/caulk 0 0 0
( -1 0 0 -16 ) ( ( 0.03125 0 0 ) ( 0 0.03125 0 ) ) common/caulk 0 0 0
( 0 1 0 0 ) ( ( 0.03125 0 0 ) ( 0 0.03125 0 ) ) common/caulk 0 0 0
( 0 -1 0 -16 ) ( ( 0.03125 0 0 ) ( 0 0.03125 0 ) ) common/caulk 0 0 0
}
}
}
"""


Q3_PATCHDEF3 = """
{
"classname" "worldspawn"
{
patchDef3
{
textures/base_wall/example
( 3 3 0 0 0 )
}
}
}
"""


def test_q2_to_q1_strips_trailing_fields() -> None:
    mf = map_q1.parse(CUBE_Q2)
    converted, report = map_convert.convert(mf, source="q2", target="q1")
    for face in converted.entities[0].brushes[0].faces:
        assert face.tex.contents == 0
        assert face.tex.surface_flags == 0
        assert face.tex.value == 0
        assert not face.tex.has_q2_trailing_fields
    assert report.errors == []


def test_q1_to_q2_keeps_zero_trailing_fields() -> None:
    mf = map_q1.parse(CUBE_Q1)
    converted, _ = map_convert.convert(mf, source="q1", target="q2")
    text = map_writer.serialize(converted, dialect="q2")
    # Q2 dialect should append the three trailing zeros to every face line.
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("(") and "BRICK1" in stripped:
            assert stripped.endswith(" 0 0 0"), stripped


def test_q1_to_q3_round_trips_via_q3_parser() -> None:
    mf = map_q1.parse(CUBE_Q1)
    converted, _ = map_convert.convert(mf, source="q1", target="q3")
    text = map_writer.serialize(converted, dialect="q3")
    # The Q3 parser should accept this happily.
    parsed = map_q3.parse(text)
    assert len(parsed.entities[0].brushes[0].faces) == 6


def test_q3_to_q1_tessellates_patches_and_normalizes_brushdef3() -> None:
    mf = map_q1.parse(Q3_MAP)
    options = map_convert.ConvertOptions(
        patch_handling="tessellate",
        tessellation_level=2,
    )
    converted, report = map_convert.convert(mf, source="q3", target="q1",
                                            options=options)
    brushes = converted.entities[0].brushes
    # Every brush is now standard; no patchDef2/brushDef3 left.
    assert all(b.raw_kind == "standard" for b in brushes)
    # 1 patch (3×3 control grid → 1 subpatch) tessellated at level 2 →
    # 2² = 4 quads → 4 thin extruded brushes plus the 1 brushDef3-derived
    # cube → 5 brushes total.
    assert len(brushes) == 5
    assert report.brushdef3_converted == 1
    assert report.patches_tessellated == 1


def test_extruded_patch_quad_builds_closed_brush() -> None:
    options = map_convert.ConvertOptions(extrusion_thickness=1.0)
    brush = map_convert._build_extruded_brush(
        [
            Vec3(0.0, 0.0, 0.0),
            Vec3(1.0, 0.0, 0.0),
            Vec3(1.0, 1.0, 0.0),
            Vec3(0.0, 1.0, 0.0),
        ],
        "common/caulk",
        options,
    )

    assert brush is not None
    rings = csg.brush_faces_from_planes([face.plane for face in brush.faces])
    assert len(rings) == 6
    assert all(len(ring) == 4 for ring in rings)


def test_q3_to_q1_drop_patches() -> None:
    mf = map_q1.parse(Q3_MAP)
    options = map_convert.ConvertOptions(patch_handling="drop")
    converted, report = map_convert.convert(mf, source="q3", target="q1",
                                            options=options)
    brushes = converted.entities[0].brushes
    # No patches left, only the converted brushDef3.
    assert len(brushes) == 1
    assert brushes[0].raw_kind == "standard"
    assert report.patches_dropped == 1


def test_q3_to_q3_preserves_patchdef3_payload() -> None:
    mf = map_q1.parse(Q3_PATCHDEF3)

    converted, report = map_convert.convert(mf, source="q3", target="q3")
    reparsed = map_q1.parse(map_writer.serialize(converted, dialect="q3"))

    assert report.errors == []
    assert len(reparsed.entities[0].brushes) == 1
    brush = reparsed.entities[0].brushes[0]
    assert brush.raw_kind == "patchDef3"
    assert "textures/base_wall/example" in brush.raw_payload


def test_keep_patches_rejected_for_non_q3() -> None:
    mf = map_q1.parse(Q3_MAP)
    options = map_convert.ConvertOptions(patch_handling="keep")
    try:
        map_convert.convert(mf, source="q3", target="q1", options=options)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for keep + target=q1")


def test_texture_remap_applies_to_face_names() -> None:
    mf = map_q1.parse(CUBE_Q1)
    options = map_convert.ConvertOptions(
        texture_map={"BRICK1": "textures/base_wall/c_wall1a"},
    )
    converted, _ = map_convert.convert(mf, source="q1", target="q3",
                                       options=options)
    for face in converted.entities[0].brushes[0].faces:
        assert face.tex.name == "textures/base_wall/c_wall1a"


def test_texture_remap_fallback_wildcard() -> None:
    mf = map_q1.parse(CUBE_Q1)
    options = map_convert.ConvertOptions(
        texture_map={"*": "textures/missing"},
    )
    converted, _ = map_convert.convert(mf, source="q1", target="q3",
                                       options=options)
    for face in converted.entities[0].brushes[0].faces:
        assert face.tex.name == "textures/missing"


def test_texture_remap_applies_to_raw_brushdef3() -> None:
    mf = map_q1.parse(Q3_MAP)
    options = map_convert.ConvertOptions(
        texture_map={"common/caulk": "textures/base_wall/c_wall1a"},
        patch_handling="keep",
    )

    converted, report = map_convert.convert(
        mf,
        source="q3",
        target="q3",
        options=options,
    )
    reparsed = map_q1.parse(map_writer.serialize(converted, dialect="q3"))
    primitive = next(
        brush
        for brush in reparsed.entities[0].brushes
        if brush.raw_kind == "brushDef3"
    )
    parsed_primitive = map_convert.bd3_mod.parse_brushdef3_block(
        primitive.raw_payload
    )

    assert report.errors == []
    assert {
        face.tex.name for face in parsed_primitive.faces
    } == {"textures/base_wall/c_wall1a"}


def test_patch_texture_remap_parse_failure_surfaces_warning() -> None:
    brush = map_q1.MapBrush(
        faces=[],
        raw_kind="patchDef2",
        raw_payload="this is not a valid patchDef2 body",
    )
    mf = map_q1.MapFile(
        entities=[map_q1.MapEntity(properties={"classname": "worldspawn"},
                                   brushes=[brush])]
    )
    options = map_convert.ConvertOptions(
        texture_map={"common/clip": "textures/base_wall/c_wall1a"},
        patch_handling="keep",
    )

    converted, report = map_convert.convert(mf, source="q3", target="q3",
                                            options=options)

    assert len(converted.entities[0].brushes) == 1
    assert converted.entities[0].brushes[0].raw_payload == brush.raw_payload
    assert report.warnings
    assert "failed to remap patchDef2 texture" in report.warnings[0]
