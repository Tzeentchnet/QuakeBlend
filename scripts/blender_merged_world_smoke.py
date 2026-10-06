"""Installed Blender smoke checks for MAP Merged World geometry."""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import sys
import tempfile

import bpy


def _cube(bounds, texture):
    x0, y0, z0, x1, y1, z1 = bounds
    return f"""{{
( {x0} {y0} {z0} ) ( {x0} {y0 + 1} {z0} ) ( {x0} {y0} {z0 + 1} ) {texture} 0 0 0 1 1
( {x0} {y0} {z0} ) ( {x0} {y0} {z0 + 1} ) ( {x0 + 1} {y0} {z0} ) {texture} 0 0 0 1 1
( {x0} {y0} {z0} ) ( {x0 + 1} {y0} {z0} ) ( {x0} {y0 + 1} {z0} ) {texture} 0 0 0 1 1
( {x1} {y1} {z1} ) ( {x1} {y1} {z1 + 1} ) ( {x1} {y1 + 1} {z1} ) {texture} 0 0 0 1 1
( {x1} {y1} {z1} ) ( {x1 + 1} {y1} {z1} ) ( {x1} {y1} {z1 + 1} ) {texture} 0 0 0 1 1
( {x1} {y1} {z1} ) ( {x1} {y1 + 1} {z1} ) ( {x1 + 1} {y1} {z1} ) {texture} 0 0 0 1 1
}}"""


def _q1_map():
    return f"""{{
"classname" "worldspawn"
{_cube((-64, -64, -16, 64, 64, 16), "STONE_A")}
{_cube((96, -32, -16, 160, 32, 16), "STONE_B")}
}}
{{
"classname" "func_door"
{_cube((192, -32, -16, 256, 32, 16), "DOOR")}
}}
{{
"classname" "info_player_start"
"origin" "8 16 24"
"message" "original"
}}
"""


def _mixed_tool_q1_map():
    return f"""{{
"classname" "worldspawn"
{_cube((-64, -64, -16, 64, 64, 16), "STONE")}
{_cube((96, -32, -16, 160, 32, 16), "clip")}
{_cube((192, -32, -16, 256, 32, 16), "hint")}
}}
"""


def _q3_map():
    return f"""{{
"classname" "worldspawn"
{_cube((-64, -64, -16, 64, 64, 16), "textures/test/world")}
{{
patchDef2
{{
textures/test/patch
( 3 3 0 0 0 )
(
( ( 0 0 32 0 0 ) ( 32 0 32 0.5 0 ) ( 64 0 32 1 0 ) )
( ( 0 32 40 0 0.5 ) ( 32 32 48 0.5 0.5 ) ( 64 32 40 1 0.5 ) )
( ( 0 64 32 0 1 ) ( 32 64 32 0.5 1 ) ( 64 64 32 1 1 ) )
)
}}
}}
}}
{{
"classname" "func_door"
{_cube((96, -32, -16, 160, 32, 16), "textures/test/door")}
}}
"""


def _import_root(path, **options):
    before = {collection.as_pointer() for collection in bpy.data.collections}
    result = bpy.ops.quakeblend.import_map(
        filepath=str(path), source_game=options.pop("source_game", "Q1"),
        wad_paths=";", texture_root=str(path.parent), **options,
    )
    assert result == {"FINISHED"}
    roots = [
        collection for collection in bpy.data.collections
        if collection.as_pointer() not in before and collection.get("qb_source_map")
    ]
    assert len(roots) == 1
    return roots[0]


def _world_meshes(root):
    return [
        obj for obj in root.all_objects
        if obj.type == "MESH" and obj.get("qb_owner_entity_index") == 0
        and "qb_patch_control_grid" not in obj
    ]


def _surface_snapshot(objects):
    surfaces = {}
    for obj in objects:
        brush_attribute = obj.data.attributes.get("qb_source_brush")
        face_attribute = obj.data.attributes["qb_source_face"]
        for polygon in obj.data.polygons:
            brush_index = (
                brush_attribute.data[polygon.index].value
                if brush_attribute is not None else obj["qb_brush_index"]
            )
            key = (int(brush_index), int(face_attribute.data[polygon.index].value))
            material = (
                obj.data.materials[polygon.material_index].name_full
                if obj.data.materials else None
            )
            uvs = tuple(
                tuple(round(value, 7) for value in obj.data.uv_layers.active.data[index].uv)
                for index in polygon.loop_indices
            )
            surfaces[key] = (material, uvs)
    return surfaces


def _select(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def _check_q1(extension_root, directory):
    parser = importlib.import_module(f"{extension_root}.formats.map_q1")
    scene_export = importlib.import_module(f"{extension_root}.blender.map_scene_export")
    path = directory / "merged-world-q1.map"
    path.write_text(_q1_map(), encoding="ascii")

    per_brush = _import_root(path)
    assert per_brush["qb_geometry_mode"] == "PER_BRUSH"
    assert json.loads(per_brush["qb_import_options"])["geometry_mode"] == "PER_BRUSH"
    per_brush_meshes = [obj for obj in per_brush.all_objects if obj.type == "MESH"]
    assert len(per_brush_meshes) == 3
    assert len(_world_meshes(per_brush)) == 2
    expected_surfaces = _surface_snapshot(_world_meshes(per_brush))

    merged = _import_root(path, geometry_mode="MERGED_WORLD")
    assert merged["qb_geometry_mode"] == "MERGED_WORLD"
    assert json.loads(merged["qb_import_options"])["geometry_mode"] == "MERGED_WORLD"
    merged_meshes = [obj for obj in merged.all_objects if obj.type == "MESH"]
    assert len(merged_meshes) == 2
    world = _world_meshes(merged)
    assert len(world) == 1
    world = world[0]
    assert list(world["qb_brush_indices"]) == [0, 1]
    assert list(world["qb_source_brush_face_offsets"]) == [0, 6, 12]
    for name in ("qb_source_entity", "qb_source_brush", "qb_source_face",
                 "qb_texture_width", "qb_texture_height"):
        attribute = world.data.attributes[name]
        assert attribute.domain == "FACE" and attribute.data_type == "INT"
    provenance = {
        (world.data.attributes["qb_source_brush"].data[index].value,
         world.data.attributes["qb_source_face"].data[index].value)
        for index in range(len(world.data.polygons))
    }
    assert provenance == {(brush, face) for brush in (0, 1) for face in range(6)}
    assert {item.value for item in world.data.attributes["qb_source_entity"].data} == {0}
    assert _surface_snapshot([world]) == expected_surfaces
    entity_brushes = [
        obj for obj in merged_meshes
        if obj.get("qb_owner_entity_index") == 1
    ]
    assert len(entity_brushes) == 1 and entity_brushes[0]["qb_brush_index"] == 0

    _select(world)
    replay_path = directory / "merged-world-replay.map"
    assert bpy.ops.quakeblend.export_map(
        filepath=str(replay_path), target_game="Q1", projection="AUTO",
        use_brush_transforms=False, use_scene_entity_edits=False,
    ) == {"FINISHED"}
    assert parser.parse_path(replay_path) == parser.parse_path(path)

    anchor = next(
        obj for obj in merged.all_objects
        if obj.get("qb_entity_role") == "ENTITY" and obj.get("qb_entity_index") == 2
    )
    anchor.location = (1.25, 2.5, 3.75)
    anchor["qb_prop_message"] = "edited"
    edited_path = directory / "merged-world-entity-edits.map"
    assert bpy.ops.quakeblend.export_map(
        filepath=str(edited_path), target_game="Q1", projection="AUTO",
        use_brush_transforms=False, use_scene_entity_edits=True,
    ) == {"FINISHED"}
    edited = parser.parse_path(edited_path)
    assert edited.entities[2].properties["origin"] == "40 80 120"
    assert edited.entities[2].properties["message"] == "edited"
    assert edited.entities[0].brushes == parser.parse_path(path).entities[0].brushes

    try:
        scene_export.apply_transforms(parser.parse_path(path), merged, path.read_bytes())
    except ValueError as exc:
        assert str(exc) == (
            "Merged World imports cannot use brush transform export; "
            "reimport with Geometry set to Per Brush"
        )
    else:
        raise AssertionError("Merged World transform extraction was accepted")
    rejected_path = directory / "merged-world-transform-rejected.map"
    rejected_path.write_bytes(b"existing destination")
    try:
        result = bpy.ops.quakeblend.export_map(
            filepath=str(rejected_path), target_game="Q1", projection="VALVE220",
            use_brush_transforms=True,
        )
    except RuntimeError:
        result = {"CANCELLED"}
    assert result == {"CANCELLED"}
    assert rejected_path.read_bytes() == b"existing destination"


def _check_hidden_tool_partitions(directory):
    path = directory / "merged-world-hidden-tools.map"
    path.write_text(_mixed_tool_q1_map(), encoding="ascii")

    per_brush = _import_root(path)
    expected_surfaces = _surface_snapshot(_world_meshes(per_brush))

    merged = _import_root(path, geometry_mode="MERGED_WORLD")
    assert merged["qb_geometry_mode"] == "MERGED_WORLD"
    world = _world_meshes(merged)
    visible = [obj for obj in world if not obj.hide_get()]
    hidden = [obj for obj in world if obj.hide_get()]
    assert len(visible) == len(hidden) == 1
    visible, hidden = visible[0], hidden[0]

    assert list(visible["qb_brush_indices"]) == [0]
    assert list(hidden["qb_brush_indices"]) == [1, 2]
    assert list(visible["qb_source_brush_face_offsets"]) == [0, 6]
    assert list(hidden["qb_source_brush_face_offsets"]) == [0, 6, 12]
    assert visible.get("qb_tool_categories") is None
    assert hidden["qb_tool_categories"] == "clip,hint"
    assert hidden["qb_tool_handling"] == "HIDDEN"
    assert not hidden.hide_render
    counts = merged["qb_tool_counts"]
    assert (counts["visible"], counts["hidden"], counts["skipped"]) == (0, 2, 0)

    visible_surfaces = _surface_snapshot([visible])
    hidden_surfaces = _surface_snapshot([hidden])
    assert set(visible_surfaces) == {(0, face) for face in range(6)}
    assert set(hidden_surfaces) == {
        (brush, face) for brush in (1, 2) for face in range(6)
    }
    assert visible_surfaces | hidden_surfaces == expected_surfaces
    for obj in world:
        assert {item.value for item in obj.data.attributes["qb_source_entity"].data} == {0}

    skipped = _import_root(
        path, geometry_mode="MERGED_WORLD",
        clip_handling="SKIP", hint_handling="SKIP",
    )
    skipped_world = _world_meshes(skipped)
    assert len(skipped_world) == 1
    assert list(skipped_world[0]["qb_brush_indices"]) == [0]
    assert not skipped_world[0].hide_get()
    assert set(skipped["qb_omitted_brushes"].keys()) == {"0:1", "0:2"}
    skipped_counts = skipped["qb_tool_counts"]
    assert (
        skipped_counts["visible"],
        skipped_counts["hidden"],
        skipped_counts["skipped"],
    ) == (0, 0, 2)


def _check_q3(directory):
    path = directory / "merged-world-q3.map"
    path.write_text(_q3_map(), encoding="ascii")
    root = _import_root(
        path, source_game="Q3", geometry_mode="MERGED_WORLD",
        q3_material_mode="DIRECT", patch_level=2,
    )
    meshes = [obj for obj in root.all_objects if obj.type == "MESH"]
    world = _world_meshes(root)
    patches = [obj for obj in meshes if "qb_patch_control_grid" in obj]
    entity_brushes = [obj for obj in meshes if obj.get("qb_owner_entity_index") == 1]
    assert len(meshes) == 3
    assert len(world) == len(patches) == len(entity_brushes) == 1
    assert list(world[0]["qb_brush_indices"]) == [0]
    assert patches[0]["qb_owner_entity_index"] == 0
    assert patches[0]["qb_brush_index"] == 1
    assert entity_brushes[0]["qb_brush_index"] == 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extension-root", default="bl_ext.user_default.quakeblend")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    assert bpy.app.background and not sys.flags.optimize
    if args.extension_root == "quakeblend":
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        importlib.import_module(args.extension_root).register()
    else:
        bpy.ops.preferences.addon_enable(module=args.extension_root)
    with tempfile.TemporaryDirectory(prefix="quakeblend-merged-world-") as temp_dir:
        directory = Path(temp_dir)
        _check_q1(args.extension_root, directory)
        _check_hidden_tool_partitions(directory)
        _check_q3(directory)
    print(
        "MERGED_WORLD_SMOKE_OK default-count merged-count materials UV provenance "
        "brush-entities patches hidden-partitions tool-counts skip source-replay "
        "entity-edits transform-rejection"
    )


if __name__ == "__main__":
    main()
