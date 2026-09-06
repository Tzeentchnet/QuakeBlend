"""Export one bounded transform from the qualified LibreQuake e3m4 scene."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Vector


SOURCE_SHA256 = "a827f8a4f6e011d8c1b81c25b16e43b086bbdec97a82f8327057ae2dc0f3f2cf"
TARGET_ENTITY_INDEX = 165
TARGET_BRUSH_INDEX = 0
TRANSLATION_GAME_UNITS = (0.0, 0.0, 16.0)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bounds(brush, csg_module):
    points = [
        point
        for ring in csg_module.brush_faces_from_planes(
            [face.plane for face in brush.faces]
        )
        for point in ring
    ]
    return [
        [min(getattr(point, axis) for point in points) for axis in ("x", "y", "z")],
        [max(getattr(point, axis) for point in points) for axis in ("x", "y", "z")],
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-map", type=Path, required=True)
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--extension-root", default="bl_ext.user_default.quakeblend")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    if not __debug__:
        raise RuntimeError("Do not run validation with Python optimization")
    assert bpy.app.background and not bpy.data.filepath
    config = Path(os.environ["BLENDER_USER_CONFIG"]).resolve()
    assert config.is_dir()
    assert Path(bpy.utils.user_resource("CONFIG")).resolve() == config
    bpy.context.preferences.use_preferences_save = False

    source_path = args.source_map.resolve(strict=True)
    scene_path = args.scene.resolve(strict=True)
    assert _sha256(source_path) == SOURCE_SHA256
    source_hash = _sha256(source_path)
    scene_hash = _sha256(scene_path)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    destination = (args.output_dir / "transformed.map").resolve()

    assert bpy.ops.wm.open_mainfile(filepath=str(scene_path)) == {"FINISHED"}
    assert args.extension_root in bpy.context.preferences.addons
    map_module = importlib.import_module(f"{args.extension_root}.formats.map_q1")
    csg_module = importlib.import_module(f"{args.extension_root}.formats.csg")
    roots = [
        collection
        for collection in bpy.data.collections
        if collection.get("qb_source_map")
        and Path(collection["qb_source_map"]).resolve() == source_path
    ]
    assert len(roots) == 1
    root = roots[0]
    assert root["qb_source_sha256"] == SOURCE_SHA256
    assert root["qb_source_game"] == "q1"
    assert root["qb_source_projection"] == "valve220"
    assert root["qb_import_scale"] == 1.0 / 32.0
    meshes = [obj for obj in root.all_objects if obj.type == "MESH"]
    assert len(meshes) == 3441
    targets = [
        obj
        for obj in meshes
        if obj["qb_owner_entity_index"] == TARGET_ENTITY_INDEX
        and obj["qb_brush_index"] == TARGET_BRUSH_INDEX
    ]
    assert len(targets) == 1
    target = targets[0]
    assert not target.constraints and not target.modifiers and target.animation_data is None
    assert max(
        abs(target.matrix_world[row][column] - Matrix.Identity(4)[row][column])
        for row in range(4)
        for column in range(4)
    ) < 1e-9

    matrix = target.matrix_world.copy()
    matrix.translation += Vector(tuple(value / 32.0 for value in TRANSLATION_GAME_UNITS))
    target.matrix_world = matrix
    bpy.context.view_layer.update()
    bpy.ops.object.select_all(action="DESELECT")
    target.select_set(True)
    bpy.context.view_layer.objects.active = target
    assert bpy.ops.quakeblend.export_map(
        filepath=str(destination),
        target_game="Q1",
        projection="VALVE220",
        use_brush_transforms=True,
        use_scene_entity_edits=False,
    ) == {"FINISHED"}
    assert destination.is_file()
    assert _sha256(source_path) == source_hash
    assert _sha256(scene_path) == scene_hash

    source = map_module.parse_path(source_path)
    exported = map_module.parse_path(destination)
    assert len(source.entities) == len(exported.entities) == 1301
    assert sum(len(entity.brushes) for entity in exported.entities) == 3441
    assert [entity.properties for entity in exported.entities] == [
        entity.properties for entity in source.entities
    ]
    original_brush = source.entities[TARGET_ENTITY_INDEX].brushes[TARGET_BRUSH_INDEX]
    transformed_brush = exported.entities[TARGET_ENTITY_INDEX].brushes[TARGET_BRUSH_INDEX]
    assert _bounds(original_brush, csg_module) == [
        [-272.0, -912.0, 72.0],
        [-264.0, -880.0, 80.0],
    ]
    assert _bounds(transformed_brush, csg_module) == [
        [-272.0, -912.0, 88.0],
        [-264.0, -880.0, 96.0],
    ]
    report = {
        "blender": bpy.app.version_string,
        "extension": str(Path(importlib.import_module(args.extension_root).__file__).resolve()),
        "source_map": str(source_path),
        "source_sha256": source_hash,
        "scene": str(scene_path),
        "scene_sha256": scene_hash,
        "destination": str(destination),
        "destination_sha256": _sha256(destination),
        "destination_bytes": destination.stat().st_size,
        "entities": len(exported.entities),
        "brushes": sum(len(entity.brushes) for entity in exported.entities),
        "target": {
            "entity_index": TARGET_ENTITY_INDEX,
            "brush_index": TARGET_BRUSH_INDEX,
            "classname": exported.entities[TARGET_ENTITY_INDEX].properties["classname"],
            "translation_game_units": list(TRANSLATION_GAME_UNITS),
            "source_bounds": _bounds(original_brush, csg_module),
            "transformed_bounds": _bounds(transformed_brush, csg_module),
        },
    }
    (args.output_dir / "export-report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))
    print("QUAKEBLEND_LIBREQUAKE_Q1_EXPORT_OK source scene transform serialization")


if __name__ == "__main__":
    main()
