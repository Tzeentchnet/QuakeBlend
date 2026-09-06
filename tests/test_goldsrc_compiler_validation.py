from __future__ import annotations

from dataclasses import replace
from io import BytesIO

import pytest

from quakeblend.formats import bsp_goldsrc, bsp_q1, map_q1, wad
from quakeblend.formats.common import Vec3
from quakeblend.formats.csg import brush_faces_from_planes
from scripts.goldsrc_compiler_fixture import DOOR_ORIGIN, fixture_text, fixture_wad
from scripts.validate_goldsrc_compiler import verify_bsp


def _sample(embedded):
    source = map_q1.parse(fixture_text("qb_gold_a"))
    textures = {texture.name: texture for texture in wad.read_wad(BytesIO(fixture_wad())).textures}
    names = ("qb_wall", "qb_high", "{qb_mask", "aaatrigger")
    bsp = bsp_goldsrc.Bsp(entities=[dict(entity.properties) for entity in source.entities])
    bsp.entities[3].update(model="*1", origin="64 0 -16")
    bsp.entities[5]["model"] = "*2"
    for index, name in enumerate(names):
        texture = textures[name]
        bsp.miptextures.append(bsp_q1.MipTexture(name, 64, 32, texture.pixels if embedded else b""))
        if embedded:
            bsp.embedded_textures[index] = texture
    for model_index, brushes in enumerate((source.entities[0].brushes,
                                           source.entities[3].brushes[:1], source.entities[5].brushes)):
        origin = Vec3(*DOOR_ORIGIN) if model_index == 1 else Vec3(0, 0, 0)
        first_face = len(bsp.faces)
        for brush in brushes:
            for original, ring in zip(brush.faces, brush_faces_from_planes([face.plane for face in brush.faces])):
                tex = original.tex
                axes = [tex.s_axis, tex.t_axis]
                offsets = [tex.s_offset + origin.dot(axes[0]), tex.t_offset + origin.dot(axes[1])]
                start = len(bsp.vertices)
                bsp.vertices.extend(point - origin for point in ring)
                first_edge = len(bsp.ledges)
                for index in range(len(ring)):
                    bsp.ledges.append(len(bsp.edges))
                    bsp.edges.append(bsp_q1.Edge(start + index, start + (index + 1) % len(ring)))
                texinfo = len(bsp.texinfos)
                bsp.texinfos.append(bsp_q1.TexInfo(axes[0], offsets[0], axes[1], offsets[1], names.index(tex.name), 0))
                bsp.faces.append(bsp_q1.Face(0, 0, first_edge, len(ring), texinfo, 0, 0, 0, 0, -1))
        bsp.models.append(bsp_q1.Model(Vec3(-144, -144, -144), Vec3(144, 144, 144), origin,
                                      first_face, len(bsp.faces) - first_face))
    return bsp, source, textures


@pytest.mark.parametrize("embedded", [False, True])
def test_goldsrc_acceptance_known_payloads_origins_uvs(embedded):
    bsp, source, textures = _sample(embedded)
    report = verify_bsp(bsp, source, textures, embedded=embedded)
    assert report["door_entity_origin"] == [64, 0, -16]
    assert report["door"]["maximum_geometry_error_game_units"] == 0
    assert report["door"]["maximum_uv_error_pixels"] == 0


@pytest.mark.parametrize("defect", ["version", "palette", "pixels", "dimension", "origin", "geometry",
                                   "uv", "missing_face", "connection", "landmark", "storage"])
def test_goldsrc_acceptance_rejects_wrong_output(defect):
    bsp, source, textures = _sample(True)
    if defect == "version":
        bsp.version = 29
    elif defect in {"palette", "pixels"}:
        bsp.embedded_textures[2] = replace(bsp.embedded_textures[2], **{defect: b"wrong"})
    elif defect == "dimension":
        bsp.miptextures[2] = replace(bsp.miptextures[2], height=64)
    elif defect == "origin":
        bsp.entities[3]["origin"] = "128 0 -32"
    elif defect == "geometry":
        bsp.vertices[-1] = bsp.vertices[-1] + Vec3(1, 0, 0)
    elif defect == "uv":
        bsp.texinfos[-1] = replace(bsp.texinfos[-1], s_offset=bsp.texinfos[-1].s_offset + 1)
    elif defect == "missing_face":
        bsp.faces.pop()
    elif defect == "connection":
        bsp.entities[5]["map"] = "wrong"
    elif defect == "landmark":
        bsp.entities[4]["origin"] = "0 0 0"
    else:
        bsp.embedded_textures.clear()
    with pytest.raises(AssertionError):
        verify_bsp(bsp, source, textures, embedded=True)
