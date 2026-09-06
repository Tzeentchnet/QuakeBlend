"""Export the original Q1 compiler fixture through an installed extension."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import math
import sys
from pathlib import Path

import bpy


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--extension-root", default="bl_ext.user_default.quakeblend")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    assert bpy.app.background and not bpy.data.filepath
    directory = args.directory.resolve()
    source = directory / "source.map"
    destination = directory / "transformed.map"
    assert not destination.exists(), destination
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    importlib.import_module(args.extension_root)
    if args.extension_root not in bpy.context.preferences.addons:
        bpy.ops.preferences.addon_enable(module=args.extension_root)
    assert bpy.ops.quakeblend.import_map(
        filepath=str(source), source_game="Q1", wad_paths=str(directory / "fixture.wad"),
        scale=1.0 / 32.0, texture_root="", import_entities=True,
    ) == {"FINISHED"}
    roots = [collection for collection in bpy.data.collections
             if collection.get("qb_source_map") == str(source)]
    assert len(roots) == 1
    brushes = [obj for obj in roots[0].all_objects if obj.type == "MESH"]
    assert len(brushes) == 7
    cube = next(obj for obj in brushes if obj["qb_brush_index"] == 6)
    assert cube["qb_owner_entity_index"] == 0
    bpy.ops.object.select_all(action="DESELECT")
    cube.select_set(True)
    bpy.context.view_layer.objects.active = cube
    cube.rotation_euler.z = math.pi / 2
    cube.scale = (1.5, 0.5, 1.25)
    cube.location = (24 / 32, -16 / 32, 8 / 32)
    bpy.context.view_layer.update()
    assert bpy.ops.quakeblend.export_map(
        filepath=str(destination), target_game="Q1", projection="VALVE220",
        use_brush_transforms=True, use_scene_entity_edits=False,
    ) == {"FINISHED"}
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash
    assert destination.is_file()
    print("QUAKEBLEND_Q1_COMPILER_EXPORT_OK")


if __name__ == "__main__":
    main()
