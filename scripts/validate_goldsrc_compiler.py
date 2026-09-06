"""Compile and verify the original GoldSrc embedded/external connected-map pair."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from quakeblend.formats import bsp_goldsrc, map_q1, wad
from quakeblend.formats.common import Vec3
from quakeblend.formats.csg import brush_faces_from_planes
from quakeblend.formats.entities import parse_origin
from scripts.goldsrc_compiler_fixture import DOOR_ORIGIN, MAP_NAMES, VARIANTS
from scripts.validate_q1_compiler import COMPILER_SHA256


def verify_brush(bsp: bsp_goldsrc.Bsp, model_index: int, source_brush: map_q1.MapBrush,
                 texture_name: str, origin: Vec3) -> dict:
    model = bsp.models[model_index]
    corners = {point for ring in brush_faces_from_planes([face.plane for face in source_brush.faces])
               for point in ring}
    seen_faces = set()
    seen_corners = set()
    maximum_geometry_error = 0.0
    maximum_uv_error = 0.0
    for face in bsp.faces[model.first_face:model.first_face + model.face_count]:
        texinfo = bsp.texinfos[face.texinfo_id]
        texture = bsp.miptextures[texinfo.miptex_index]
        if texture.name != texture_name:
            continue
        points = [bsp.vertices[index] for index in bsp.face_polygon(face)]
        assert len(points) == 4
        world_points = [point + origin for point in points]
        candidates = [index for index, original in enumerate(source_brush.faces)
                      if all(abs(original.plane.normal.dot(point) - original.plane.dist) < 1e-4
                             for point in world_points)]
        assert len(candidates) == 1, (texture_name, candidates, world_points)
        face_index = candidates[0]
        assert face_index not in seen_faces
        seen_faces.add(face_index)
        tex = source_brush.faces[face_index].tex
        assert tex.s_axis is not None and tex.t_axis is not None
        for point, world_point in zip(points, world_points):
            nearest = min(corners, key=lambda corner: (corner - world_point).length())
            error = (nearest - world_point).length()
            maximum_geometry_error = max(maximum_geometry_error, error)
            assert error < 1e-4, (texture_name, world_point, nearest)
            seen_corners.add(nearest)
            expected = (world_point.dot(tex.s_axis) / tex.xscale + tex.s_offset,
                        world_point.dot(tex.t_axis) / tex.yscale + tex.t_offset)
            actual = (point.dot(texinfo.s_axis) + texinfo.s_offset,
                      point.dot(texinfo.t_axis) + texinfo.t_offset)
            error = max(abs(left - right) for left, right in zip(expected, actual))
            maximum_uv_error = max(maximum_uv_error, error)
            assert error < 1e-3, (texture_name, actual, expected)
    assert seen_faces == set(range(6)) and seen_corners == corners
    return {"faces": len(seen_faces), "corners": len(seen_corners),
            "maximum_geometry_error_game_units": maximum_geometry_error,
            "maximum_uv_error_pixels": maximum_uv_error}


def verify_bsp(bsp: bsp_goldsrc.Bsp, source: map_q1.MapFile,
               textures: dict[str, wad.MipTexture], *, embedded: bool) -> dict:
    assert bsp.version == 30 and len(bsp.models) == 3
    references = {index: texture for index, texture in enumerate(bsp.miptextures) if texture is not None}
    assert {texture.name for texture in references.values()} <= textures.keys()
    assert {"qb_wall", "qb_high", "{qb_mask", "aaatrigger"} <= {
        texture.name for texture in references.values()
    }
    assert set(bsp.embedded_textures) == (set(references) if embedded else set())
    for index, reference in references.items():
        expected = textures[reference.name]
        assert (reference.width, reference.height) == (64, 32)
        if embedded:
            actual = bsp.embedded_textures[index]
            assert actual.palette == expected.palette and actual.pixels == expected.pixels
            assert reference.pixels == expected.pixels
        else:
            assert reference.pixels == b""
    door, = [entity for entity in bsp.entities if entity.get("classname") == "func_door"]
    trigger, = [entity for entity in bsp.entities if entity.get("classname") == "trigger_changelevel"]
    landmark, = [entity for entity in bsp.entities if entity.get("classname") == "info_landmark"]
    player, = [entity for entity in bsp.entities if entity.get("classname") == "info_player_start"]
    light, = [entity for entity in bsp.entities if entity.get("classname") == "light"]
    assert tuple(parse_origin(door["origin"])) == DOOR_ORIGIN
    assert door["targetname"] == "fixture_door"
    assert door["model"] == "*1" and trigger["model"] == "*2"
    assert landmark == source.entities[4].properties
    assert (trigger["map"], trigger["landmark"]) == (
        source.entities[5].properties["map"], landmark["targetname"],
    )
    assert player == source.entities[1].properties and light == source.entities[2].properties
    world_result = verify_brush(bsp, 0, source.entities[0].brushes[6], "qb_high", Vec3(0, 0, 0))
    door_result = verify_brush(bsp, 1, source.entities[3].brushes[0], "{qb_mask", Vec3(*parse_origin(door["origin"])))
    trigger_result = verify_brush(bsp, 2, source.entities[5].brushes[0], "aaatrigger",
                                  Vec3(*parse_origin(trigger.get("origin", "0 0 0"))))
    geometry = []
    for model_index, model in enumerate(bsp.models):
        for face in bsp.faces[model.first_face:model.first_face + model.face_count]:
            texinfo = bsp.texinfos[face.texinfo_id]
            points = sorted(tuple(bsp.vertices[index]) for index in bsp.face_polygon(face))
            geometry.append((model_index, bsp.miptextures[texinfo.miptex_index].name, points))
    return {"version": bsp.version, "models": len(bsp.models), "faces": len(bsp.faces),
            "textures": len(references), "embedded_textures": len(bsp.embedded_textures),
            "door_entity_origin": list(parse_origin(door["origin"])),
            "door_model_origin": list(bsp.models[1].origin),
            "landmark": landmark, "changelevel": trigger, "world_cube": world_result,
            "door": door_result, "trigger": trigger_result,
            "geometry_sha256": hashlib.sha256(json.dumps(sorted(geometry)).encode("ascii")).hexdigest()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--qbsp", type=Path, required=True)
    args = parser.parse_args()
    if not __debug__:
        raise RuntimeError("Do not run validation with Python optimization")
    directory = args.directory.resolve()
    executable = args.qbsp.resolve(strict=True)
    assert hashlib.sha256(executable.read_bytes()).hexdigest() == COMPILER_SHA256, "Unexpected compiler binary"
    report_path = directory / "compiler-report.json"
    assert not report_path.exists()
    paths = [directory / variant / f"{name}.map" for variant in VARIANTS for name in MAP_NAMES]
    for path in paths:
        for suffix in (".bsp", ".compiler.log", ".log", ".pts", ".lin", ".prt"):
            assert not path.with_suffix(suffix).exists(), "Use a fresh fixture directory"
    inputs = [directory / "fixture.wad", *paths]
    hashes = {str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
    archive = wad.read_wad_path(directory / "fixture.wad")
    assert archive.flavour == "WAD3"
    textures = {texture.name: texture for texture in archive.textures}
    report = {"compiler": str(executable), "compiler_sha256": COMPILER_SHA256,
              "input_sha256": hashes, "cases": {}}
    for path in paths:
        variant = path.parent.name
        command = [str(executable), "-hlbsp", "-noallowupgrade", "-nodefaultpaths", "-leaktest",
                   "-basedir", str(directory), "-gamedir", str(directory), "-wadpath", str(directory)]
        if variant == "external":
            command.append("-notex")
        command.append(str(path))
        result = subprocess.run(command, cwd=directory, capture_output=True, text=True, timeout=120)
        text = result.stdout + result.stderr
        with path.with_suffix(".compiler.log").open("x", encoding="utf-8") as stream:
            stream.write(text)
        assert result.returncode == 0, text
        assert "WARNING:" not in text and "ERROR:" not in text, text
        assert not any(path.with_suffix(suffix).exists() for suffix in (".pts", ".lin")), "Leak file"
        output = path.with_suffix(".bsp")
        compiled = bsp_goldsrc.read_path(output)
        key = f"{variant}/{path.stem}"
        report["cases"][key] = {"command": command, "exit_code": result.returncode,
                                 "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                                 **verify_bsp(compiled, map_q1.parse_path(path), textures,
                                              embedded=variant == "embedded")}
    for name in MAP_NAMES:
        assert report["cases"][f"embedded/{name}"]["geometry_sha256"] == (
            report["cases"][f"external/{name}"]["geometry_sha256"]
        ), "Texture storage changed geometry"
    assert hashes == {str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in inputs}, "Compiler changed an input"
    with report_path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps(report, indent=2))
    print("QUAKEBLEND_GOLDSRC_COMPILER_OK embedded external origins UVs connections")


if __name__ == "__main__":
    main()
