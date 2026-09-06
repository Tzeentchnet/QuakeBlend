"""Compile and validate the bounded LibreQuake e3m4 transform export."""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

from quakeblend.formats import bsp_q1, map_q1, map_transform
from quakeblend.formats.common import Vec3
from quakeblend.formats.csg import brush_faces_from_planes


SOURCE_SHA256 = "a827f8a4f6e011d8c1b81c25b16e43b086bbdec97a82f8327057ae2dc0f3f2cf"
COMPILER_SHA256 = "fad5a4dc4daf42773ad9a812349b2667221bec47a920cad10cb821ae442c8eb8"
EXPECTED_WARNING = (
    "WARNING: worldspawn at 0 0 0 has long value for key wad (length 385 >= 127)"
)
EXPECTED_WADS = (
    "lq_dev.wad",
    "lq_flesh.wad",
    "lq_greek.wad",
    "lq_legacy.wad",
    "lq_liquidsky.wad",
    "lq_medieval.wad",
    "lq_props.wad",
    "lq_secret.wad",
    "lq_terra.wad",
    "lq_wood.wad",
)
TARGET_ENTITY_INDEX = 165
TARGET_BRUSH_INDEX = 0
TRANSLATION = Vec3(0, 0, 16)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _brush_rings(brush):
    return brush_faces_from_planes([face.plane for face in brush.faces])


def _bounds(rings):
    points = [point for ring in rings for point in ring]
    return (
        Vec3(*(min(getattr(point, axis) for point in points) for axis in ("x", "y", "z"))),
        Vec3(*(max(getattr(point, axis) for point in points) for axis in ("x", "y", "z"))),
    )


def _inside(point: Vec3, minimum: Vec3, maximum: Vec3) -> bool:
    return all(
        getattr(minimum, axis) - 1e-4
        <= getattr(point, axis)
        <= getattr(maximum, axis) + 1e-4
        for axis in ("x", "y", "z")
    )


def _match_points(expected, actual) -> float:
    assert len(expected) == len(actual)
    remaining = list(actual)
    maximum_error = 0.0
    for point in expected:
        nearest = min(remaining, key=lambda candidate: (candidate - point).length())
        error = (nearest - point).length()
        maximum_error = max(maximum_error, error)
        assert error < 1e-4, (point, nearest, error)
        remaining.remove(nearest)
    return maximum_error


def verify_exported_map(source_path: Path, transformed_path: Path) -> tuple[map_q1.MapFile, dict]:
    assert _sha256(source_path) == SOURCE_SHA256
    source = map_q1.parse_path(source_path)
    transformed_text = transformed_path.read_bytes().decode("latin-1")
    transformed = map_q1.parse(transformed_text)
    assert len(source.entities) == len(transformed.entities) == 1301
    assert sum(len(entity.brushes) for entity in source.entities) == 3441
    assert sum(len(entity.brushes) for entity in transformed.entities) == 3441
    assert [entity.properties for entity in source.entities] == [
        entity.properties for entity in transformed.entities
    ]

    source_brush = source.entities[TARGET_ENTITY_INDEX].brushes[TARGET_BRUSH_INDEX]
    transformed_brush = transformed.entities[TARGET_ENTITY_INDEX].brushes[TARGET_BRUSH_INDEX]
    assert source.entities[TARGET_ENTITY_INDEX].properties["classname"] == "func_detail_wall"
    assert len(source_brush.faces) == len(transformed_brush.faces) == 6
    expected = deepcopy(source)
    expected.entities[TARGET_ENTITY_INDEX].brushes[TARGET_BRUSH_INDEX] = transformed_brush
    map_transform.validate_serialized(expected, transformed_text)

    source_rings = _brush_rings(source_brush)
    transformed_rings = _brush_rings(transformed_brush)
    maximum_geometry_error = 0.0
    maximum_uv_error = 0.0
    for source_face, transformed_face, source_ring, transformed_ring in zip(
        source_brush.faces,
        transformed_brush.faces,
        source_rings,
        transformed_rings,
    ):
        expected_ring = [point + TRANSLATION for point in source_ring]
        maximum_geometry_error = max(
            maximum_geometry_error,
            _match_points(expected_ring, transformed_ring),
        )
        assert source_face.tex.name == transformed_face.tex.name == "grk_ebrick10"
        assert source_face.tex.s_axis is not None and source_face.tex.t_axis is not None
        assert transformed_face.tex.s_axis is not None and transformed_face.tex.t_axis is not None
        for source_point in source_ring:
            transformed_point = min(
                transformed_ring,
                key=lambda candidate: (candidate - source_point - TRANSLATION).length(),
            )
            source_uv = (
                source_point.dot(source_face.tex.s_axis) / source_face.tex.xscale
                + source_face.tex.s_offset,
                source_point.dot(source_face.tex.t_axis) / source_face.tex.yscale
                + source_face.tex.t_offset,
            )
            transformed_uv = (
                transformed_point.dot(transformed_face.tex.s_axis)
                / transformed_face.tex.xscale
                + transformed_face.tex.s_offset,
                transformed_point.dot(transformed_face.tex.t_axis)
                / transformed_face.tex.yscale
                + transformed_face.tex.t_offset,
            )
            maximum_uv_error = max(
                maximum_uv_error,
                max(abs(left - right) for left, right in zip(source_uv, transformed_uv)),
            )
    assert maximum_uv_error < 1e-3
    source_bounds = _bounds(source_rings)
    transformed_bounds = _bounds(transformed_rings)
    assert source_bounds == (Vec3(-272, -912, 72), Vec3(-264, -880, 80))
    assert transformed_bounds == (Vec3(-272, -912, 88), Vec3(-264, -880, 96))
    return source, {
        "entities": len(transformed.entities),
        "brushes": sum(len(entity.brushes) for entity in transformed.entities),
        "source_bounds": [list(source_bounds[0]), list(source_bounds[1])],
        "transformed_bounds": [list(transformed_bounds[0]), list(transformed_bounds[1])],
        "maximum_map_geometry_error_game_units": maximum_geometry_error,
        "maximum_map_uv_error_pixels": maximum_uv_error,
    }


def verify_target_bsp(path: Path, source: map_q1.MapFile, *, expect_present: bool) -> dict:
    bsp = bsp_q1.read_path(path)
    assert bsp.version == 29
    assert len(bsp.models) > 1
    brush = source.entities[TARGET_ENTITY_INDEX].brushes[TARGET_BRUSH_INDEX]
    source_rings = _brush_rings(brush)
    moved_rings = [[point + TRANSLATION for point in ring] for ring in source_rings]
    minimum, maximum = _bounds(moved_rings)
    seen_faces = set()
    seen_corners = set()
    maximum_geometry_error = 0.0
    maximum_uv_error = 0.0
    matched_faces = 0
    for compiled_face in bsp.faces:
        points = [bsp.vertices[index] for index in bsp.face_polygon(compiled_face)]
        candidates = [
            index
            for index, source_face in enumerate(brush.faces)
            if all(
                abs(source_face.plane.normal.dot(point - TRANSLATION)
                    - source_face.plane.dist) < 1e-4
                for point in points
            )
        ]
        if not candidates or not all(_inside(point, minimum, maximum) for point in points):
            continue
        assert len(candidates) == 1, candidates
        face_index = candidates[0]
        assert face_index not in seen_faces
        seen_faces.add(face_index)
        matched_faces += 1
        source_face = brush.faces[face_index]
        expected_corners = moved_rings[face_index]
        texinfo = bsp.texinfos[compiled_face.texinfo_id]
        assert source_face.tex.s_axis is not None and source_face.tex.t_axis is not None
        for point in points:
            nearest = min(expected_corners, key=lambda corner: (corner - point).length())
            error = (nearest - point).length()
            maximum_geometry_error = max(maximum_geometry_error, error)
            assert error < 1e-4, (path, point, error)
            seen_corners.add(nearest)
            source_point = point - TRANSLATION
            expected_uv = (
                source_point.dot(source_face.tex.s_axis) / source_face.tex.xscale
                + source_face.tex.s_offset,
                source_point.dot(source_face.tex.t_axis) / source_face.tex.yscale
                + source_face.tex.t_offset,
            )
            actual_uv = (
                point.dot(texinfo.s_axis) + texinfo.s_offset,
                point.dot(texinfo.t_axis) + texinfo.t_offset,
            )
            maximum_uv_error = max(
                maximum_uv_error,
                max(abs(left - right) for left, right in zip(expected_uv, actual_uv)),
            )
    if expect_present:
        assert seen_faces == set(range(6))
        assert seen_corners == {point for ring in moved_rings for point in ring}
        assert matched_faces == 6
        assert maximum_uv_error < 1e-3
    else:
        assert not seen_faces and not seen_corners and matched_faces == 0
    return {
        "version": bsp.version,
        "models": len(bsp.models),
        "faces": len(bsp.faces),
        "target_faces": matched_faces,
        "maximum_geometry_error_game_units": maximum_geometry_error,
        "maximum_uv_error_pixels": maximum_uv_error,
        "sha256": _sha256(path),
    }


def _warning_summary(text: str, expected_textures: set[str]) -> dict:
    missing_wads = Counter()
    missing_textures = []
    multiple_contents = Counter()
    no_valid_wad = 0
    unmatched_sides = []
    long_wad = 0
    unknown = []
    for raw_line in text.splitlines():
        if "WARNING:" not in raw_line:
            continue
        line = raw_line.strip()
        archive = re.search(r"([^/\\']+\.wad)' not found$", line)
        contents = re.search(
            r"\[line \d+\]: brush has multiple face contents \((.+)\), "
            r"the former will be used\.$",
            line,
        )
        sides = re.fullmatch(r"WARNING: (\d+) sides not found \(use -verbose to display\)", line)
        if line.startswith("fs::addArchive: WARNING:") and archive:
            missing_wads[archive.group(1).casefold()] += 1
        elif line == "WARNING: No valid WAD filenames in worldmodel":
            no_valid_wad += 1
        elif contents:
            multiple_contents[contents.group(1)] += 1
        elif line.startswith("WARNING: unable to find texture "):
            missing_textures.append(line.removeprefix("WARNING: unable to find texture "))
        elif sides:
            unmatched_sides.append(int(sides.group(1)))
        elif line == EXPECTED_WARNING:
            long_wad += 1
        else:
            unknown.append(line)
    assert not unknown, unknown
    assert missing_wads == Counter({name: 2 for name in EXPECTED_WADS}), missing_wads
    assert len(missing_textures) == len(set(missing_textures)) == 83
    assert set(missing_textures) == expected_textures
    assert sum(multiple_contents.values()) == 28, multiple_contents
    assert set(multiple_contents) == {
        "SOLID vs WATER | TRANSLUCENT | DETAIL",
        "WATER | TRANSLUCENT | DETAIL vs SOLID",
    }
    assert no_valid_wad == 1 and unmatched_sides == [19] and long_wad == 1
    return {
        "total": sum(1 for line in text.splitlines() if "WARNING:" in line),
        "missing_wads": dict(sorted(missing_wads.items())),
        "missing_textures": sorted(missing_textures),
        "multiple_face_contents": dict(sorted(multiple_contents.items())),
        "no_valid_wad": no_valid_wad,
        "unmatched_sides": unmatched_sides,
        "long_wad": long_wad,
    }


def _compile(
    executable: Path,
    source: Path,
    output_dir: Path,
    name: str,
    expected_textures: set[str],
) -> dict:
    staged_map = output_dir / f"{name}.map"
    staged_map.write_bytes(source.read_bytes())
    output = output_dir / f"{name}.bsp"
    log = output_dir / f"{name}.compiler.log"
    command = [
        str(executable),
        "-noallowupgrade",
        "-nodefaultpaths",
        "-leaktest",
        "-notex",
        "-basedir",
        str(output_dir),
        "-gamedir",
        str(output_dir),
        "-wadpath",
        str(output_dir),
        str(staged_map),
    ]
    started = time.perf_counter()
    result = subprocess.run(
        command,
        cwd=output_dir,
        capture_output=True,
        text=True,
        timeout=180,
    )
    elapsed = time.perf_counter() - started
    text = result.stdout + result.stderr
    log.write_text(text, encoding="utf-8")
    assert result.returncode == 0, text
    assert "ERROR:" not in text
    assert output.is_file()
    assert not (output_dir / f"{name}.pts").exists(), "Compiler produced a leak file"
    return {
        "command": command,
        "exit_code": result.returncode,
        "elapsed_seconds": elapsed,
        "warnings": _warning_summary(text, expected_textures),
        "map_sha256": _sha256(staged_map),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-map", type=Path, required=True)
    parser.add_argument("--transformed-map", type=Path, required=True)
    parser.add_argument("--qbsp", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if not __debug__:
        raise RuntimeError("Do not run validation with Python optimization")
    source_path = args.source_map.resolve(strict=True)
    transformed_path = args.transformed_map.resolve(strict=True)
    executable = args.qbsp.resolve(strict=True)
    assert _sha256(executable) == COMPILER_SHA256, "Unexpected compiler binary"
    source_hash = _sha256(source_path)
    transformed_hash = _sha256(transformed_path)
    source, map_report = verify_exported_map(source_path, transformed_path)
    expected_textures = {
        face.tex.name
        for entity in source.entities
        for brush in entity.brushes
        for face in brush.faces
    }
    assert len(expected_textures) == 83
    args.output_dir.mkdir(parents=True, exist_ok=False)
    report = {
        "compiler": str(executable),
        "compiler_sha256": _sha256(executable),
        "source_sha256": source_hash,
        "transformed_sha256": transformed_hash,
        "map": map_report,
        "cases": {},
    }
    for name, path, expect_present in (
        ("source", source_path, False),
        ("transformed", transformed_path, True),
    ):
        case = _compile(executable, path, args.output_dir, name, expected_textures)
        case.update(
            verify_target_bsp(
                args.output_dir / f"{name}.bsp",
                source,
                expect_present=expect_present,
            )
        )
        report["cases"][name] = case
    assert report["cases"]["source"]["warnings"] == report["cases"]["transformed"]["warnings"]
    assert _sha256(source_path) == source_hash
    assert _sha256(transformed_path) == transformed_hash
    with (args.output_dir / "compiler-report.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps(report, indent=2))
    print("QUAKEBLEND_LIBREQUAKE_Q1_COMPILER_OK source transformed geometry uv")


if __name__ == "__main__":
    main()
