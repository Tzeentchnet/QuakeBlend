from __future__ import annotations

import pytest

from quakeblend.formats import map_q1
from quakeblend.formats.csg import brush_faces_from_planes
from scripts.blender_large_map_benchmark import (
    DEFAULT_BRUSH_COUNT,
    argument_parser,
    generate_q1_map,
    peak_process_memory,
)


def test_default_large_map_is_deterministic_and_closed() -> None:
    first = generate_q1_map()
    assert first == generate_q1_map()
    level = map_q1.parse(first)
    assert len(level.entities) == 1
    assert level.entities[0].properties == {"classname": "worldspawn"}
    assert len(level.entities[0].brushes) == DEFAULT_BRUSH_COUNT == 3_441
    assert all(len(brush.faces) == 6 for brush in level.entities[0].brushes)
    for brush in (level.entities[0].brushes[0], level.entities[0].brushes[-1]):
        rings = brush_faces_from_planes([face.plane for face in brush.faces])
        assert len(rings) == 6
        assert all(len(ring) == 4 for ring in rings)


def test_benchmark_arguments_validate_brush_count() -> None:
    parser = argument_parser()
    defaults = parser.parse_args([])
    assert defaults.brushes == DEFAULT_BRUSH_COUNT
    assert defaults.geometry_mode == "PER_BRUSH"
    arguments = parser.parse_args([
        "--brushes", "16", "--geometry-mode", "merged_world",
    ])
    assert arguments.brushes == 16
    assert arguments.geometry_mode == "MERGED_WORLD"
    with pytest.raises(SystemExit):
        parser.parse_args(["--brushes", "0"])
    with pytest.raises(SystemExit):
        parser.parse_args(["--geometry-mode", "INVALID"])
    with pytest.raises(ValueError, match="at least 1"):
        generate_q1_map(0)


def test_peak_process_memory_uses_standard_library_probe() -> None:
    peak_bytes, source = peak_process_memory()
    assert peak_bytes > 0
    assert source in {
        "windows_peak_working_set",
        "getrusage_ru_maxrss_bytes",
        "getrusage_ru_maxrss_kibibytes",
    }
