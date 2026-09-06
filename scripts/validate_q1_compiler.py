"""Compile the Q1 fixture and Blender export, then verify BSP geometry and UVs."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from quakeblend.formats import bsp_q1, map_q1
from quakeblend.formats.common import Vec3
from quakeblend.formats.csg import brush_faces_from_planes


COMPILER_SHA256 = "fad5a4dc4daf42773ad9a812349b2667221bec47a920cad10cb821ae442c8eb8"


def inverse(point: Vec3, transformed: bool) -> Vec3:
    if not transformed:
        return point
    return Vec3((point.y + 16) / 1.5, -(point.x - 24) / 0.5, (point.z - 8) / 1.25)


def verify_bsp(path: Path, source: map_q1.MapFile, *, transformed: bool) -> dict:
    bsp = bsp_q1.read_path(path)
    assert bsp.version == 29
    assert len(bsp.models) == 1
    assert any(entity.get("classname") == "info_player_start" for entity in bsp.entities)
    brush = source.entities[0].brushes[6]
    corners = {point for ring in brush_faces_from_planes([face.plane for face in brush.faces])
               for point in ring}
    seen_corners = set()
    seen_faces = set()
    maximum_geometry_error = 0.0
    maximum_uv_error = 0.0
    grid_faces = 0
    for face in bsp.faces:
        texinfo = bsp.texinfos[face.texinfo_id]
        texture = bsp.miptextures[texinfo.miptex_index]
        if texture is None or texture.name != "qb_grid":
            continue
        grid_faces += 1
        assert (texture.width, texture.height) == (64, 32)
        assert len(texture.pixels) == 64 * 32
        points = []
        for ledge in bsp.ledges[face.ledge_id:face.ledge_id + face.ledge_num]:
            edge = bsp.edges[abs(ledge)]
            points.append(bsp.vertices[edge.v0 if ledge >= 0 else edge.v1])
        original_points = [inverse(point, transformed) for point in points]
        candidates = [index for index, original in enumerate(brush.faces)
                      if all(abs(original.plane.normal.dot(point) - original.plane.dist) < 1e-4
                             for point in original_points)]
        assert len(candidates) == 1, (path, candidates)
        face_index = candidates[0]
        seen_faces.add(face_index)
        tex = brush.faces[face_index].tex
        assert tex.s_axis is not None and tex.t_axis is not None
        for point, original_point in zip(points, original_points):
            assert all(abs(component) <= 16.0001 for component in original_point)
            nearest = min(corners, key=lambda corner: (corner - original_point).length())
            error = (nearest - original_point).length()
            maximum_geometry_error = max(maximum_geometry_error, error)
            assert error < 1e-4, (path, original_point)
            seen_corners.add(nearest)
            expected = (original_point.dot(tex.s_axis) / tex.xscale + tex.s_offset,
                        original_point.dot(tex.t_axis) / tex.yscale + tex.t_offset)
            actual = (point.dot(texinfo.s_axis) + texinfo.s_offset,
                      point.dot(texinfo.t_axis) + texinfo.t_offset)
            error = max(abs(left - right) for left, right in zip(expected, actual))
            maximum_uv_error = max(maximum_uv_error, error)
            assert error < 1e-3, (path, actual, expected)
    assert seen_faces == set(range(6))
    assert seen_corners == corners
    return {"version": bsp.version, "faces": len(bsp.faces), "grid_faces": grid_faces,
            "maximum_geometry_error_game_units": maximum_geometry_error,
            "maximum_uv_error_pixels": maximum_uv_error,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--qbsp", type=Path, required=True)
    args = parser.parse_args()
    directory = args.directory.resolve()
    executable = args.qbsp.resolve(strict=True)
    assert hashlib.sha256(executable.read_bytes()).hexdigest() == COMPILER_SHA256, "Unexpected compiler binary"
    source = map_q1.parse_path(directory / "source.map")
    exported = map_q1.parse_path(directory / "transformed.map")
    assert len(exported.entities) == len(source.entities)
    assert [entity.properties for entity in exported.entities] == [entity.properties for entity in source.entities]
    assert len(exported.entities[0].brushes) == 7
    assert exported.entities[0].brushes[:6] == source.entities[0].brushes[:6]
    report = {"compiler": str(executable),
              "compiler_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(), "cases": {}}
    for name in ("source", "transformed"):
        output = directory / f"{name}.bsp"
        log = directory / f"{name}.compiler.log"
        assert not output.exists() and not log.exists(), "Use a fresh fixture directory"
        command = [str(executable), "-noallowupgrade", "-nodefaultpaths", "-leaktest",
                   "-basedir", str(directory), "-gamedir", str(directory),
                   "-wadpath", str(directory), str(directory / f"{name}.map")]
        result = subprocess.run(command, cwd=directory, capture_output=True, text=True, timeout=120)
        text = result.stdout + result.stderr
        log.write_text(text, encoding="utf-8")
        assert result.returncode == 0, text
        assert "WARNING:" not in text and "ERROR:" not in text, text
        assert output.is_file(), text
        assert not (directory / f"{name}.pts").exists(), "Compiler produced a leak file"
        report["cases"][name] = {"command": command, "exit_code": result.returncode,
                                 **verify_bsp(output, source, transformed=name == "transformed")}
    for name in ("source.map", "transformed.map", "fixture.wad"):
        report[name + "_sha256"] = hashlib.sha256((directory / name).read_bytes()).hexdigest()
    with (directory / "compiler-report.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps(report, indent=2))
    print("QUAKEBLEND_Q1_COMPILER_OK source transformed geometry uv")


if __name__ == "__main__":
    main()
