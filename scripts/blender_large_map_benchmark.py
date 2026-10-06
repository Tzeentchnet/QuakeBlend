"""Benchmark a deterministic large MAP import through an installed extension."""

from __future__ import annotations

import argparse
import ctypes
import gc
import hashlib
import importlib
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
import time
import tomllib


DEFAULT_BRUSH_COUNT = 3_441
RESULT_PREFIX = "QUAKEBLEND_LARGE_MAP_BENCHMARK "

_BRUSH_SIZE = 32
_BRUSH_STRIDE = 48
_GRID_WIDTH = 64
_TEXTURE_NAME = "__qb_benchmark"


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("brush count must be at least 1")
    return number


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--brushes",
        type=_positive_int,
        default=DEFAULT_BRUSH_COUNT,
        help=f"Number of box brushes to generate (default: {DEFAULT_BRUSH_COUNT})",
    )
    parser.add_argument(
        "--geometry-mode",
        type=str.upper,
        choices=("PER_BRUSH", "MERGED_WORLD"),
        default="PER_BRUSH",
        help="MAP geometry mode to benchmark (default: PER_BRUSH)",
    )
    parser.add_argument(
        "--extension-root",
        default="bl_ext.user_default.quakeblend",
        help="Installed Blender extension module namespace",
    )
    return parser


def _brush_text(index: int) -> str:
    column = index % _GRID_WIDTH
    row = (index // _GRID_WIDTH) % _GRID_WIDTH
    layer = index // (_GRID_WIDTH * _GRID_WIDTH)
    x0 = column * _BRUSH_STRIDE
    y0 = row * _BRUSH_STRIDE
    z0 = layer * _BRUSH_STRIDE
    x1 = x0 + _BRUSH_SIZE
    y1 = y0 + _BRUSH_SIZE
    z1 = z0 + _BRUSH_SIZE
    texture = _TEXTURE_NAME
    return "\n".join((
        "{",
        f"( {x0} {y0} {z0} ) ( {x0} {y0 + 1} {z0} ) "
        f"( {x0} {y0} {z0 + 1} ) {texture} 0 0 0 1 1",
        f"( {x0} {y0} {z0} ) ( {x0} {y0} {z0 + 1} ) "
        f"( {x0 + 1} {y0} {z0} ) {texture} 0 0 0 1 1",
        f"( {x0} {y0} {z0} ) ( {x0 + 1} {y0} {z0} ) "
        f"( {x0} {y0 + 1} {z0} ) {texture} 0 0 0 1 1",
        f"( {x1} {y1} {z1} ) ( {x1} {y1} {z1 + 1} ) "
        f"( {x1} {y1 + 1} {z1} ) {texture} 0 0 0 1 1",
        f"( {x1} {y1} {z1} ) ( {x1 + 1} {y1} {z1} ) "
        f"( {x1} {y1} {z1 + 1} ) {texture} 0 0 0 1 1",
        f"( {x1} {y1} {z1} ) ( {x1} {y1 + 1} {z1} ) "
        f"( {x1 + 1} {y1} {z1} ) {texture} 0 0 0 1 1",
        "}",
    ))


def generate_q1_map(brush_count: int = DEFAULT_BRUSH_COUNT) -> str:
    """Return a deterministic Q1 worldspawn containing disjoint box brushes."""
    if brush_count < 1:
        raise ValueError("brush count must be at least 1")
    parts = ['{\n"classname" "worldspawn"']
    parts.extend(_brush_text(index) for index in range(brush_count))
    parts.append("}")
    return "\n".join(parts) + "\n"


def _windows_peak_working_set() -> int:
    from ctypes import wintypes

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = (
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        )

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.argtypes = ()
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(ProcessMemoryCounters),
        wintypes.DWORD,
    )
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    if not psapi.GetProcessMemoryInfo(
        kernel32.GetCurrentProcess(),
        ctypes.byref(counters),
        counters.cb,
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return int(counters.PeakWorkingSetSize)


def peak_process_memory() -> tuple[int, str]:
    """Return the process lifetime peak resident memory in bytes."""
    if sys.platform == "win32":
        return _windows_peak_working_set(), "windows_peak_working_set"

    import resource

    maximum_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return int(maximum_rss), "getrusage_ru_maxrss_bytes"
    return int(maximum_rss) * 1024, "getrusage_ru_maxrss_kibibytes"


def _installed_extension(extension_root: str):
    if not extension_root.startswith("bl_ext."):
        raise ValueError(
            "benchmark requires an installed extension namespace beginning with 'bl_ext.'"
        )
    module = importlib.import_module(extension_root)
    module_path = Path(module.__file__).resolve()
    manifest_path = module_path.parent / "blender_manifest.toml"
    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    return module, module_path, manifest


def _blender_arguments() -> argparse.Namespace:
    arguments = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return argument_parser().parse_args(arguments)


def main() -> None:
    import bpy

    args = _blender_arguments()
    if not __debug__:
        raise RuntimeError("Run the benchmark without Python optimization")
    if not bpy.app.background or bpy.data.filepath:
        raise RuntimeError("Run the benchmark in a fresh background Blender process")

    _, extension_path, manifest = _installed_extension(args.extension_root)
    enabled = {addon.module for addon in bpy.context.preferences.addons}
    if args.extension_root not in enabled:
        enable_result = bpy.ops.preferences.addon_enable(module=args.extension_root)
        if enable_result != {"FINISHED"}:
            raise RuntimeError(f"failed to enable extension: {enable_result}")

    with tempfile.TemporaryDirectory(prefix="quakeblend-large-map-") as raw_directory:
        directory = Path(raw_directory)
        map_path = directory / f"synthetic-{args.brushes}-brushes.map"
        map_bytes = generate_q1_map(args.brushes).encode("ascii")
        map_path.write_bytes(map_bytes)
        map_sha256 = hashlib.sha256(map_bytes).hexdigest()
        del map_bytes
        gc.collect()

        roots_before = {collection.as_pointer() for collection in bpy.data.collections}
        objects_before = len(bpy.data.objects)
        meshes_before = len(bpy.data.meshes)
        peak_before, memory_source = peak_process_memory()
        started = time.perf_counter()
        operator_result = bpy.ops.quakeblend.import_map(
            filepath=str(map_path),
            source_game="Q1",
            scale=1.0 / 32.0,
            worldspawn_only=True,
            create_materials=False,
            import_entities=False,
            import_lights=False,
            import_cameras=False,
            geometry_mode=args.geometry_mode,
            texture_root=str(directory),
            wad_paths="",
        )
        elapsed_seconds = time.perf_counter() - started
        peak_after, memory_source_after = peak_process_memory()

        if operator_result != {"FINISHED"}:
            raise RuntimeError(f"MAP import operator returned {operator_result}")
        if memory_source_after != memory_source:
            raise RuntimeError("process memory source changed during benchmark")

        source_path = str(map_path.resolve())
        roots = [
            collection
            for collection in bpy.data.collections
            if collection.as_pointer() not in roots_before
            and collection.get("qb_source_map") == source_path
        ]
        if len(roots) != 1:
            raise RuntimeError(f"expected one imported root, found {len(roots)}")
        root = roots[0]
        if root.get("qb_geometry_mode") != args.geometry_mode:
            raise RuntimeError(
                f"expected geometry mode {args.geometry_mode}, "
                f"found {root.get('qb_geometry_mode')!r}"
            )
        objects = list(root.all_objects)
        mesh_objects = [obj for obj in objects if obj.type == "MESH"]
        mesh_datablocks = {obj.data.as_pointer() for obj in mesh_objects}
        expected_mesh_count = (
            args.brushes if args.geometry_mode == "PER_BRUSH" else 1
        )
        if len(mesh_objects) != expected_mesh_count:
            raise RuntimeError(
                f"expected {expected_mesh_count} mesh objects, found {len(mesh_objects)}"
            )
        if len(mesh_datablocks) != expected_mesh_count:
            raise RuntimeError(
                f"expected {expected_mesh_count} mesh datablocks, "
                f"found {len(mesh_datablocks)}"
            )
        if args.geometry_mode == "MERGED_WORLD":
            merged = mesh_objects[0]
            if list(merged.get("qb_brush_indices", ())) != list(range(args.brushes)):
                raise RuntimeError("merged brush provenance is incomplete")
            for name in ("qb_source_entity", "qb_source_brush", "qb_source_face"):
                attribute = merged.data.attributes.get(name)
                if (
                    attribute is None
                    or attribute.domain != "FACE"
                    or attribute.data_type != "INT"
                ):
                    raise RuntimeError(f"missing merged face provenance {name}")

        build_hash = bpy.app.build_hash.decode("ascii")
        report = {
            "benchmark": "synthetic_q1_large_map_import",
            "schema_version": 1,
            "brush_count": args.brushes,
            "elapsed_import_seconds": round(elapsed_seconds, 6),
            "object_count": len(objects),
            "mesh_object_count": len(mesh_objects),
            "mesh_datablock_count": len(mesh_datablocks),
            "blender_object_delta": len(bpy.data.objects) - objects_before,
            "blender_mesh_delta": len(bpy.data.meshes) - meshes_before,
            "peak_process_memory_bytes": peak_after,
            "peak_process_memory_before_import_bytes": peak_before,
            "peak_process_memory_source": memory_source,
            "generated_map_bytes": map_path.stat().st_size,
            "generated_map_sha256": map_sha256,
            "operator_result": sorted(operator_result),
            "import_options": {
                "create_materials": False,
                "geometry_mode": args.geometry_mode,
                "scale": 1.0 / 32.0,
                "source_game": "Q1",
                "worldspawn_only": True,
            },
            "environment": {
                "blender_build_hash": build_hash,
                "blender_version": bpy.app.version_string,
                "extension_id": manifest["id"],
                "extension_path": str(extension_path),
                "extension_version": manifest["version"],
                "logical_cpu_count": os.cpu_count(),
                "machine": platform.machine(),
                "platform": platform.platform(),
                "processor": platform.processor(),
                "python_version": platform.python_version(),
            },
        }
        print(RESULT_PREFIX + json.dumps(report, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
