"""Compile the Q2 fixture and Blender export, then verify geometry, UVs and metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import subprocess
from pathlib import Path

from quakeblend.formats import bsp_q2, map_q2, wal
from quakeblend.formats.csg import brush_faces_from_planes
from scripts.q2_compiler_fixture import TEXTURE_NAMES
from scripts.validate_q1_compiler import COMPILER_SHA256, inverse


def verify_contents(data: bytes, texinfos: list[bsp_q2.TexInfo]) -> dict:
    assert len(data) >= 8 + 19 * 8 and data[:4] == b"IBSP"
    assert struct.unpack_from("<i", data, 4)[0] == 38
    records = []
    for lump, record_size in ((bsp_q2.LUMP_BRUSHES, 12), (bsp_q2.LUMP_BRUSHSIDES, 4)):
        offset, size = struct.unpack_from("<ii", data, 8 + lump * 8)
        assert offset >= 8 + 19 * 8 and size > 0 and size % record_size == 0
        assert offset + size <= len(data)
        records.append(data[offset:offset + size])
    brushes = list(struct.iter_unpack("<iii", records[0]))
    sides = list(struct.iter_unpack("<Hh", records[1]))
    assert len(brushes) == 7
    grid_brushes = 0
    for first_side, side_count, contents in brushes:
        assert contents == 1, ("Expected CONTENTS_SOLID", contents)
        assert first_side >= 0 and side_count >= 6 and first_side + side_count <= len(sides)
        names = set()
        for _, texinfo_index in sides[first_side:first_side + side_count]:
            assert 0 <= texinfo_index < len(texinfos)
            names.add(texinfos[texinfo_index].texture_name)
        if "quakeblend/qb_grid" in names:
            assert names == {"quakeblend/qb_grid"}
            grid_brushes += 1
    assert grid_brushes == 1
    return {"brushes": len(brushes), "grid_brushes": grid_brushes, "contents": 1}


def verify_bsp(path: Path, source: map_q2.MapFile, *, transformed: bool) -> dict:
    bsp = bsp_q2.read_path(path)
    assert bsp.version == 38 and len(bsp.models) == 1
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
        assert texinfo.texture_name in {f"quakeblend/{name}" for name in TEXTURE_NAMES}
        if texinfo.texture_name != "quakeblend/qb_grid":
            assert (texinfo.flags, texinfo.value) == (0, 0)
            continue
        grid_faces += 1
        assert (texinfo.flags, texinfo.value) == (2, 37)
        points = [bsp.vertices[index] for index in bsp.face_polygon(face)]
        assert len(points) == 4
        original_points = [inverse(point, transformed) for point in points]
        candidates = [index for index, original in enumerate(brush.faces)
                      if all(abs(original.plane.normal.dot(point) - original.plane.dist) < 1e-4
                             for point in original_points)]
        assert len(candidates) == 1, (path, candidates)
        face_index = candidates[0]
        assert face_index not in seen_faces, "Duplicate grid face"
        seen_faces.add(face_index)
        tex = brush.faces[face_index].tex
        assert tex.s_axis is not None and tex.t_axis is not None
        for point, original_point in zip(points, original_points):
            nearest = min(corners, key=lambda corner: (corner - original_point).length())
            error = (nearest - original_point).length()
            maximum_geometry_error = max(maximum_geometry_error, error)
            assert error < 1e-4, (path, original_point)
            seen_corners.add(nearest)
            expected = (original_point.dot(tex.s_axis) / tex.xscale + tex.s_offset,
                        original_point.dot(tex.t_axis) / tex.yscale + tex.t_offset)
            actual = (point.dot(texinfo.u_axis) + texinfo.u_offset,
                      point.dot(texinfo.v_axis) + texinfo.v_offset)
            error = max(abs(left - right) for left, right in zip(expected, actual))
            maximum_uv_error = max(maximum_uv_error, error)
            assert error < 1e-3, (path, actual, expected)
    assert grid_faces == 6 and seen_faces == set(range(6)) and seen_corners == corners
    contents = verify_contents(path.read_bytes(), bsp.texinfos)
    return {"version": bsp.version, "faces": len(bsp.faces), "grid_faces": grid_faces,
            "maximum_geometry_error_game_units": maximum_geometry_error,
            "maximum_uv_error_pixels": maximum_uv_error,
            "grid_flags": 2, "grid_value": 37, **contents,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def verify_export(source: map_q2.MapFile, exported: map_q2.MapFile) -> None:
    assert len(exported.entities) == len(source.entities)
    assert [entity.properties for entity in exported.entities] == [entity.properties for entity in source.entities]
    assert len(exported.entities[0].brushes) == 7
    assert exported.entities[0].brushes[:6] == source.entities[0].brushes[:6]
    assert [entity.brushes for entity in exported.entities[1:]] == [entity.brushes for entity in source.entities[1:]]
    for brush in exported.entities[0].brushes:
        assert len(brush.faces) == 6
        for face in brush.faces:
            assert face.tex.is_valve220
    for original, modified in zip(source.entities[0].brushes[6].faces, exported.entities[0].brushes[6].faces):
        assert (modified.tex.name, modified.tex.contents, modified.tex.surface_flags, modified.tex.value) == (
            original.tex.name, original.tex.contents, original.tex.surface_flags, original.tex.value,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--qbsp", type=Path, required=True)
    args = parser.parse_args()
    assert __debug__, "Do not run validation with Python optimization"
    directory = args.directory.resolve()
    executable = args.qbsp.resolve(strict=True)
    assert hashlib.sha256(executable.read_bytes()).hexdigest() == COMPILER_SHA256, "Unexpected compiler binary"
    for name in ("source", "transformed"):
        for suffix in (".bsp", ".compiler.log", ".pts", ".lin"):
            assert not (directory / f"{name}{suffix}").exists(), "Use a fresh fixture directory"
    assert not (directory / "compiler-report.json").exists()
    source = map_q2.parse_path(directory / "source.map")
    exported = map_q2.parse_path(directory / "transformed.map")
    verify_export(source, exported)
    inputs = [directory / "source.map", directory / "transformed.map"]
    for name in (*[f"quakeblend/{name}" for name in TEXTURE_NAMES], "skip"):
        path = directory / "textures" / f"{name}.wal"
        texture = wal.read_wal_path(path)
        assert (texture.name, texture.width, texture.height) == (name, 64, 32)
        assert (texture.contents, texture.flags, texture.value) == (1, 0, 0)
        inputs.append(path)
    input_hashes = {str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in inputs}
    report = {"compiler": str(executable), "compiler_sha256": COMPILER_SHA256,
              "input_sha256": input_hashes, "cases": {}}
    for name in ("source", "transformed"):
        output = directory / f"{name}.bsp"
        log = directory / f"{name}.compiler.log"
        command = [str(executable), "-q2bsp", "-noallowupgrade", "-nodefaultpaths", "-leaktest",
                   "-basedir", str(directory), "-gamedir", str(directory),
                   str(directory / f"{name}.map")]
        result = subprocess.run(command, cwd=directory, capture_output=True, text=True, timeout=120)
        text = result.stdout + result.stderr
        with log.open("x", encoding="utf-8") as stream:
            stream.write(text)
        assert result.returncode == 0, text
        assert "WARNING:" not in text and "ERROR:" not in text, text
        assert output.is_file(), text
        assert not any((directory / f"{name}{suffix}").exists() for suffix in (".pts", ".lin"))
        report["cases"][name] = {"command": command, "exit_code": result.returncode,
                                 **verify_bsp(output, source, transformed=name == "transformed")}
    assert input_hashes == {str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
                            for path in inputs}, "Compiler changed an input"
    with (directory / "compiler-report.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps(report, indent=2))
    print("QUAKEBLEND_Q2_COMPILER_OK source transformed geometry uv metadata")


if __name__ == "__main__":
    main()
