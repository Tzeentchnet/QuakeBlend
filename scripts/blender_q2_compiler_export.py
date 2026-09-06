"""Export the original Q2 compiler fixture through an installed extension."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import math
import os
import sys
from pathlib import Path

import bpy


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--extension-root", default="bl_ext.user_default.quakeblend")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    assert __debug__, "Do not run validation with Python optimization"
    assert bpy.app.background and not bpy.data.filepath
    config = os.environ.get("BLENDER_USER_CONFIG")
    assert config and Path(config).is_dir(), "Use an explicit existing isolated config directory"
    assert Path(bpy.utils.user_resource("CONFIG")).resolve() == Path(config).resolve()
    bpy.context.preferences.use_preferences_save = False
    directory = args.directory.resolve()
    source = directory / "source.map"
    destination = directory / "transformed.map"
    blend = directory / "transformed.blend"
    assert not destination.exists() and not blend.exists(), "Use a fresh fixture directory"
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    importlib.import_module(args.extension_root)
    if args.extension_root not in bpy.context.preferences.addons:
        assert bpy.ops.preferences.addon_enable(module=args.extension_root) == {"FINISHED"}
    map_q2 = importlib.import_module(f"{args.extension_root}.formats.map_q2")
    level = map_q2.parse_path(source)
    assert bpy.ops.quakeblend.import_map(
        filepath=str(source), source_game="Q2", wad_paths="",
        scale=1.0 / 32.0, texture_root=str(directory), import_entities=True,
        create_materials=True, import_brush_entities=True, worldspawn_only=False,
    ) == {"FINISHED"}
    roots = [collection for collection in bpy.data.collections
             if collection.get("qb_source_map") == str(source)]
    assert len(roots) == 1
    brushes = [obj for obj in roots[0].all_objects if obj.type == "MESH"]
    assert len(brushes) == 7
    for obj in brushes:
        assert obj["qb_owner_entity_index"] == 0
        brush = level.entities[0].brushes[obj["qb_brush_index"]]
        mesh = obj.data
        assert len(mesh.polygons) == 6 and len(mesh.vertices) == 8
        assert all(item.value == 64 for item in mesh.attributes["qb_texture_width"].data)
        assert all(item.value == 32 for item in mesh.attributes["qb_texture_height"].data)
        for polygon in mesh.polygons:
            source_face = mesh.attributes["qb_source_face"].data[polygon.index].value
            tex = brush.faces[source_face].tex
            assert tex.s_axis is not None and tex.t_axis is not None
            for loop_index in polygon.loop_indices:
                point = mesh.vertices[mesh.loops[loop_index].vertex_index].co * 32
                expected = (
                    (sum(left * right for left, right in zip(point, tex.s_axis)) / tex.xscale
                     + tex.s_offset) / 64,
                    1 - (sum(left * right for left, right in zip(point, tex.t_axis)) / tex.yscale
                         + tex.t_offset) / 32,
                )
                actual = mesh.uv_layers.active.data[loop_index].uv
                assert max(abs(left - right) for left, right in zip(actual, expected)) < 1e-6
        assert len(mesh.materials) == 1
        images = [node.image for node in mesh.materials[0].node_tree.nodes if node.type == "TEX_IMAGE"]
        assert images and all(image and tuple(image.size) == (64, 32) for image in images)
    cube = next(obj for obj in brushes if obj["qb_brush_index"] == 6)
    bpy.ops.object.select_all(action="DESELECT")
    cube.select_set(True)
    bpy.context.view_layer.objects.active = cube
    cube.rotation_euler.z = math.pi / 2
    cube.scale = (1.5, 0.5, 1.25)
    cube.location = (24 / 32, -16 / 32, 8 / 32)
    bpy.context.view_layer.update()
    assert bpy.ops.quakeblend.export_map(
        filepath=str(destination), target_game="Q2", projection="VALVE220",
        use_brush_transforms=True, use_scene_entity_edits=False,
    ) == {"FINISHED"}
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash
    assert destination.is_file()
    assert bpy.ops.wm.save_as_mainfile(filepath=str(blend)) == {"FINISHED"}
    print("QUAKEBLEND_Q2_COMPILER_EXPORT_OK WAL dimensions UVs transform export")
    print(blend)


if __name__ == "__main__":
    main()
