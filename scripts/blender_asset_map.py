"""Validate the acquired LibreQuake MAP through an installed extension."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import os
import sys
from array import array
from collections import Counter
from pathlib import Path

import bpy


def _verify_asset(cache: Path, catalog: str) -> tuple[dict, Path]:
    asset = json.loads(
        (Path(__file__).resolve().parents[1] / "tests" / "assets" / catalog)
        .read_text(encoding="utf-8")
    )["assets"][0]
    root = (cache / asset["cache_directory"]).resolve()
    for entry in asset["files"]:
        path = (root / entry["path"]).resolve()
        assert path.is_relative_to(root), path
        data = path.read_bytes()
        assert len(data) == entry["bytes"], path
        assert hashlib.sha256(data).hexdigest() == entry["sha256"], path
    return asset, root


def _snapshot(root, scene_export) -> dict:
    objects = {}
    for obj in root.all_objects:
        record = {
            "type": obj.type,
            "matrix": [list(row) for row in obj.matrix_world],
            "properties": obj.id_properties_ensure().to_dict(),
        }
        if obj.type == "MESH":
            assert obj.data.polygons, obj.name
            assert all(math.isfinite(value) for vertex in obj.data.vertices for value in vertex.co)
            assert obj.data.uv_layers.active is not None, obj.name
            assert all(math.isfinite(value) for loop in obj.data.uv_layers.active.data for value in loop.uv)
            record["mesh_signature"] = scene_export.mesh_signature(obj)
            record["vertices"] = len(obj.data.vertices)
            record["polygons"] = len(obj.data.polygons)
        elif obj.type == "LIGHT":
            record["light"] = [obj.data.type, obj.data.energy, list(obj.data.color)]
        elif obj.type == "CAMERA":
            record["camera"] = [obj.data.lens, obj.data.sensor_width, obj.data.sensor_fit]
        objects[obj.name] = record
    materials = {slot.material.name: slot.material for obj in root.all_objects
                 if obj.type == "MESH" for slot in obj.material_slots if slot.material}
    material_records = {}
    for name, material in materials.items():
        images = []
        if material.node_tree:
            for node in material.node_tree.nodes:
                if node.type == "TEX_IMAGE" and node.image:
                    path = (Path(bpy.path.abspath(node.image.filepath)).resolve()
                            if node.image.filepath else None)
                    if path is not None:
                        assert path.is_file(), path
                    else:
                        assert material.get("qb_placeholder"), material.name
                        assert node.image.packed_file is not None, node.image.name
                    pixels = array("f", [0.0]) * len(node.image.pixels)
                    node.image.pixels.foreach_get(pixels)
                    assert pixels and all(math.isfinite(value) for value in pixels)
                    images.append({
                        "path": str(path) if path else None, "size": list(node.image.size),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path else None,
                        "pixels_sha256": hashlib.sha256(pixels.tobytes()).hexdigest(),
                        "asset_key": node.image.get("qb_asset_key"),
                    })
        material_records[name] = {"asset_key": material.get("qb_asset_key"), "images": images,
                                  "placeholder": bool(material.get("qb_placeholder"))}
    return {"properties": root.id_properties_ensure().to_dict(),
            "collections": sorted(collection.name for collection in root.children),
            "objects": objects, "materials": material_records}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--extension-root", default="bl_ext.user_default.quakeblend")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    if not __debug__:
        raise RuntimeError("Run validation without Python optimization")
    assert bpy.app.background and not bpy.data.filepath, "Run in a fresh background Blender"
    config = os.environ.get("BLENDER_USER_CONFIG")
    assert config and Path(config).is_dir(), "Use an explicit existing isolated configuration"
    assert Path(bpy.utils.user_resource("CONFIG")).resolve() == Path(config).resolve()
    bpy.context.preferences.use_preferences_save = False
    source, source_root = _verify_asset(args.cache_root, "manifest.json")
    textures, texture_root = _verify_asset(args.cache_root, "librequake-textures.json")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    module = importlib.import_module(args.extension_root)
    if args.extension_root not in bpy.context.preferences.addons:
        bpy.ops.preferences.addon_enable(module=args.extension_root)
    scene_export = importlib.import_module(f"{args.extension_root}.blender.map_scene_export")
    map_parser = importlib.import_module(f"{args.extension_root}.formats.map_q1")
    constants = importlib.import_module(f"{args.extension_root}.utils.constants")
    assert constants.CSG_EPSILON == 1e-5, "Install the corrected CSG build in the test profile"
    source_path = (source_root / source["map_path"]).resolve()
    level = map_parser.parse_path(source_path)
    expected_ids = {(entity_index, brush_index) for entity_index, entity in enumerate(level.entities)
                    for brush_index, brush in enumerate(entity.brushes)}
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    result = bpy.ops.quakeblend.import_map(
        filepath=str(source_path), source_game="Q1", texture_root=str(texture_root),
        wad_paths="", scale=1.0 / 32.0, import_entities=True,
        import_lights=True, import_cameras=True,
    )
    assert result == {"FINISHED"}, result
    roots = [collection for collection in bpy.data.collections
             if collection.get("qb_source_map") == str(source_path)]
    assert len(roots) == 1
    root = roots[0]
    assert root["qb_source_sha256"] == hashlib.sha256(source_path.read_bytes()).hexdigest()
    assert root["qb_source_game"] == "q1"
    assert root["qb_source_projection"] == "valve220"
    assert root["qb_import_scale"] == 1.0 / 32.0
    meshes = [obj for obj in root.all_objects if obj.type == "MESH"]
    imported_ids = [(obj["qb_owner_entity_index"], obj["qb_brush_index"]) for obj in meshes]
    assert len(set(imported_ids)) == len(imported_ids)
    assert set(imported_ids) == expected_ids, sorted(expected_ids - set(imported_ids))
    assert len(root["qb_transform_baselines"]) == len(meshes)
    assert all(obj["qb_map_import_id"] == root["qb_map_import_id"] for obj in meshes)
    nonclosed_brushes = []
    for obj in meshes:
        entity_index, brush_index = obj["qb_owner_entity_index"], obj["qb_brush_index"]
        edge_uses = Counter(edge for polygon in obj.data.polygons for edge in polygon.edge_keys)
        if not edge_uses or any(count != 2 for count in edge_uses.values()):
            nonclosed_brushes.append({"entity": entity_index, "brush": brush_index,
                                      "edge_use_counts": dict(Counter(edge_uses.values()))})
        brush = level.entities[entity_index].brushes[brush_index]
        attribute = obj.data.attributes.get("qb_source_face")
        assert attribute is not None and attribute.domain == "FACE", obj.name
        source_faces = [item.value for item in attribute.data]
        assert sorted(source_faces) == list(range(len(brush.faces))), obj.name
    assert not nonclosed_brushes, nonclosed_brushes
    before = _snapshot(root, scene_export)
    assert sum(record.get("vertices", 0) for record in before["objects"].values()) == 28752
    assert sum(record.get("polygons", 0) for record in before["objects"].values()) == 22180
    assert len(before["collections"]) == source["expected"]["entities"]
    assert Counter(record["type"] for record in before["objects"].values()) == {
        "MESH": 3441, "EMPTY": 998, "LIGHT": 296, "CAMERA": 7,
    }
    expected_placeholders = set(textures["coverage"]["ambiguous"]) | set(textures["coverage"]["encoded_candidates"])
    assert {name for name, material in before["materials"].items()
            if material["placeholder"]} == expected_placeholders
    assert len(before["materials"]) == textures["coverage"]["required_textures"]
    image_paths = {image["path"] for material in before["materials"].values()
                   for image in material["images"] if image["path"]}
    expected_images = {str((texture_root / entry["path"]).resolve())
                       for entry in textures["files"] if "texture_name" in entry}
    assert image_paths == expected_images, (expected_images - image_paths, image_paths - expected_images)
    blend_path = (args.output_dir / "librequake-e3m4.blend").resolve()
    root_name = root.name
    assert bpy.ops.wm.save_as_mainfile(filepath=str(blend_path)) == {"FINISHED"}
    assert bpy.ops.wm.open_mainfile(filepath=str(blend_path)) == {"FINISHED"}
    after = _snapshot(bpy.data.collections[root_name], scene_export)
    assert before == after, "Imported scene or provenance changed during save/reopen"
    scene_export.apply_transforms(map_parser.parse_path(source_path),
                                  bpy.data.collections[root_name], source_path.read_bytes())
    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == before["properties"]["qb_source_sha256"]
    report = {
        "blender": bpy.app.version_string,
        "extension": str(Path(module.__file__).resolve()),
        "source_sha256": before["properties"]["qb_source_sha256"],
        "expected_brushes": len(expected_ids), "imported_brushes": len(meshes),
        "missing_brush_ids": sorted(expected_ids - set(imported_ids)),
        "csg_epsilon": constants.CSG_EPSILON,
        "omitted_source_faces": [],
        "nonclosed_brushes": nonclosed_brushes,
        "object_types": dict(Counter(record["type"] for record in before["objects"].values())),
        "vertices": sum(record.get("vertices", 0) for record in before["objects"].values()),
        "polygons": sum(record.get("polygons", 0) for record in before["objects"].values()),
        "materials": len(before["materials"]), "resolved_images": len(image_paths),
        "placeholder_materials": sorted(name for name, material in before["materials"].items()
                        if material["placeholder"]),
        "save_reopen_equal": True, "blend_path": str(blend_path),
        "unchanged_transform_preflight": "passed",
    }
    (args.output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    summary = {key: value for key, value in report.items()
               if key not in {"omitted_source_faces", "nonclosed_brushes"}}
    summary["omitted_source_faces"] = 0
    summary["nonclosed_brushes"] = len(nonclosed_brushes)
    print(json.dumps(summary, indent=2))
    print("QUAKEBLEND_ASSET_MAP_OK import materials save_reopen")


if __name__ == "__main__":
    main()
