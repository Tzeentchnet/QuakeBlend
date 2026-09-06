"""Original fixtures checking import content, visibility, UVs and ownership."""

from __future__ import annotations

import argparse
import importlib
import json
import struct
from types import SimpleNamespace
from pathlib import Path
import sys

import bpy


def snapshot(root):
    return {f"{obj['qb_owner_entity_index']}:{obj['qb_brush_index']}": (
        [tuple(vertex.co) for vertex in obj.data.vertices],
        [tuple(loop.uv) for loop in obj.data.uv_layers.active.data])
        for obj in root.all_objects if obj.type == "MESH"}


def check_layout(extension_root):
    controls = importlib.import_module(f"{extension_root}.blender.import_options")

    class Layout:
        def __init__(self, rows, enabled=True):
            self.rows = rows
            self.enabled = enabled
            self.parent = None

        def panel(self, *args, **kwargs):
            return self, self

        def label(self, **kwargs):
            pass

        def column(self):
            child = Layout(self.rows)
            child.parent = self
            return child

        def prop(self, operator, name, **kwargs):
            getattr(operator, name)
            current, enabled = self, True
            while current:
                enabled &= current.enabled
                current = current.parent
            self.rows[name] = enabled

    for kind, games in (("map", ("AUTO", "Q1", "Q2", "Q3")), ("bsp", ("", "Q1", "Q2", "Q3", "GOLDSRC"))):
        rna = getattr(bpy.ops.quakeblend, f"import_{kind}").get_rna_type()
        defaults = {prop.identifier: prop.default for prop in rna.properties
                    if prop.identifier != "stitch_target" and hasattr(prop, "default")}
        if kind == "bsp":
            defaults["stitch_target"] = "AUTO"
        for game in games:
            for disabled in (False, True):
                rows = {}
                operator = SimpleNamespace(**defaults)
                operator.bl_idname = rna.identifier
                operator.layout = Layout(rows)
                setattr(operator, "detected_game" if kind == "bsp" else "source_game", game)
                operator.worldspawn_only = disabled
                operator.create_materials = not disabled
                controls.draw_import_options(operator, None)
                assert rows["import_entities"] == (not disabled)
                assert rows["texture_root"]
                assert ("q3_lighting" in rows) == (game in {"", "AUTO", "Q3"})
                if "q3_lighting" in rows:
                    assert rows["q3_lighting"] == (not disabled)
                assert ("stitch_goldsrc" in rows) == (kind == "bsp" and game in {"", "GOLDSRC"})
    print("IMPORT_LAYOUT_OK game sections dependencies registered properties")


def check_projection_sizes(smoke, materials, directory):
    name = b"NON_SQUARE".ljust(16, b"\0")
    payload = name + struct.pack("<6I", 32, 16, 40, 552, 680, 712) + bytes((1,)) * 680
    wad_path = directory / "dimensions.wad"
    wad_path.write_bytes(b"WAD2" + struct.pack("<2i", 1, 12 + len(payload)) + payload +
        struct.pack("<3i", 12, len(payload), len(payload)) + bytes((0x44, 0, 0, 0)) + name)
    wal_path = directory / "NON_SQUARE.wal"
    wal_path.write_bytes(b"NON_SQUARE".ljust(32, b"\0") + struct.pack("<6I", 32, 16, 100, 612, 740, 772) +
        bytes(32) + struct.pack("<3I", 0, 0, 0) + bytes((1,)) * 680)
    (directory / "scripts").mkdir()
    for image_name, size in (("editor", (64, 32)), ("runtime", (8, 8))):
        image = materials.create_image(image_name, *size, bytes((128, 64, 32, 255)) * (size[0] * size[1]))
        image.filepath_raw = str(directory / f"{image_name}.png")
        image.file_format = "PNG"
        image.save()
    (directory / "scripts/dimensions.shader").write_text("""custom/dimensions {
qer_editorimage editor.png
{ map runtime.png }
}
custom/collision {
surfaceparm playerclip
{ map runtime.png }
}
""", encoding="ascii")
    for game in ("Q1", "Q2", "Q3"):
        token = "custom/dimensions" if game == "Q3" else "NON_SQUARE"
        path = directory / f"dimensions-{game}.map"
        path.write_text(smoke._Q1_MAP.replace("SMOKE", token) + (smoke._Q3_PATCH_MAP.replace("textures/smoke/patch", token) if game == "Q3" else ""), encoding="ascii")
        snapshots = []
        for create in (False, True):
            before = set(bpy.data.collections.keys())
            resources = [len(getattr(bpy.data, category)) for category in ("materials", "images", "node_groups", "actions")]
            assert bpy.ops.quakeblend.import_map(filepath=str(path), source_game=game, create_materials=create,
                texture_root=str(directory), wad_paths=str(wad_path) if game == "Q1" else ";", import_entities=False) == {"FINISHED"}
            root = next(collection for collection in bpy.data.collections if collection.name not in before and collection.get("qb_source_map"))
            if not create:
                assert resources == [len(getattr(bpy.data, category)) for category in ("materials", "images", "node_groups", "actions")]
                assert all(not obj.data.materials for obj in root.all_objects)
            snapshots.append(snapshot(root))
            brush = next(obj for obj in root.all_objects if "qb_texture_width" in obj.data.attributes)
            assert {item.value for item in brush.data.attributes["qb_texture_width"].data} == {64 if game == "Q3" else 32}
            assert {item.value for item in brush.data.attributes["qb_texture_height"].data} == {32 if game == "Q3" else 16}
        assert snapshots[0] == snapshots[1]
    path = directory / "shader-clip.map"
    path.write_text(smoke._Q1_MAP.replace("SMOKE", "custom/collision"), encoding="ascii")
    for mode in ("SHADERS", "DIRECT"):
        before = set(bpy.data.collections.keys())
        assert bpy.ops.quakeblend.import_map(filepath=str(path), source_game="Q3", create_materials=False,
            texture_root=str(directory), q3_material_mode=mode, import_entities=False) == {"FINISHED"}
        root = next(collection for collection in bpy.data.collections if collection.name not in before and collection.get("qb_source_map"))
        assert all(obj.hide_get() and obj["qb_tool_categories"] == "clip" for obj in root.all_objects)
    print("MAP_DIMENSIONS_OK WAD WAL Q3 brush patch material-free shader-metadata")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extension-root", default="bl_ext.user_default.quakeblend")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    assert bpy.app.background and not sys.flags.optimize
    args.output_dir.mkdir(parents=True, exist_ok=False)
    if args.extension_root == "quakeblend":
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        importlib.import_module(args.extension_root).register()
    else:
        bpy.ops.preferences.addon_enable(module=args.extension_root)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    smoke = importlib.import_module("blender_smoke")
    transform = importlib.import_module(f"{args.extension_root}.blender.map_scene_export")
    map_format = importlib.import_module(f"{args.extension_root}.formats.map_q1")
    materials = importlib.import_module(f"{args.extension_root}.blender.builder_materials")
    directory = args.output_dir
    check_layout(args.extension_root)
    check_projection_sizes(smoke, materials, directory)
    source = smoke._Q1_MAP
    brush = source[source.index("{", source.index('"worldspawn"')):source.index('\n}\n}\n') + 2]
    text = '{\n"classname" "worldspawn"\n' + brush + '\n' + brush.replace("SMOKE", "clip") + '\n' + brush.replace("SMOKE", "hint") + '\n}\n'
    text += '{\n"classname" "trigger_once"\n' + brush + '\n}\n'
    text += '{\n"classname" "func_door"\n' + brush + '\n}\n'
    text += '{ "classname" "info_player_start" "origin" "8 16 24" }\n{ "classname" "light" "origin" "0 0 48" }'
    path = directory / "options.map"
    path.write_text(text, encoding="ascii")
    roots = []

    def import_map(**options):
        before = set(bpy.data.collections.keys())
        assert bpy.ops.quakeblend.import_map(filepath=str(path), wad_paths=";", texture_root=str(directory), **options) == {"FINISHED"}
        root = next(collection for collection in bpy.data.collections if collection.name not in before and collection.get("qb_source_map"))
        roots.append(root)
        return root

    resource_types = ("materials", "images", "node_groups", "actions")
    for grouped in (True, False):
        before = [len(getattr(bpy.data, category)) for category in resource_types]
        hidden = import_map(create_materials=False, group_entities=grouped)
        assert before == [len(getattr(bpy.data, category)) for category in resource_types]
        assert len(snapshot(hidden)) == 5
        assert bool(hidden.children) == grouped
        assert all(not obj.parent for obj in hidden.all_objects)
        tools = [obj for obj in hidden.all_objects if obj.get("qb_tool_categories")]
        assert len(tools) == 4
        assert all(obj.hide_get() and not obj.hide_render for obj in tools)
        assert all(not obj.hide_get() for obj in hidden.all_objects if not obj.get("qb_tool_categories"))
        level = map_format.parse(text)
        transform.apply_transforms(level, hidden, path.read_bytes())
        visible = import_map(create_materials=True, group_entities=grouped,
            trigger_handling="VISIBLE", clip_handling="VISIBLE", hint_handling="VISIBLE")
        assert snapshot(visible) == snapshot(hidden)
        assert all(not obj.hide_get() for obj in visible.all_objects)
        skipped = import_map(create_materials=False, group_entities=grouped,
            trigger_handling="SKIP", clip_handling="SKIP", hint_handling="SKIP")
        assert set(snapshot(skipped)) == {"0:0", "2:0"}
        bpy.ops.object.select_all(action="DESELECT")
        selected = next(obj for obj in skipped.all_objects if obj.type == "MESH")
        selected.select_set(True)
        bpy.context.view_layer.objects.active = selected
        exported = directory / f"skipped-source-{grouped}.map"
        assert bpy.ops.quakeblend.export_map(filepath=str(exported), target_game="Q1",
            use_brush_transforms=False, use_scene_entity_edits=False) == {"FINISHED"}
        assert map_format.parse(exported.read_text(encoding="utf-8")) == map_format.parse(text)
        try:
            transform.apply_transforms(map_format.parse(text), skipped, path.read_bytes())
        except ValueError as exc:
            assert "complete import" in str(exc)
        else:
            raise AssertionError("Skipped brushes accepted for transform export")
        world = import_map(create_materials=False, worldspawn_only=True, group_entities=grouped)
        assert set(snapshot(world)) == {"0:0", "0:1", "0:2"}
        assert all(obj.type == "MESH" for obj in world.all_objects)
        assert world["qb_tool_counts"]["skipped"] == 0
        no_brush_entities = import_map(create_materials=False, import_brush_entities=False)
        assert set(snapshot(no_brush_entities)) == {"0:0", "0:1", "0:2"}
        no_entities = import_map(create_materials=False, import_entities=False)
        assert len(snapshot(no_entities)) == 5
        assert all(obj.type == "MESH" for obj in no_entities.all_objects)
    for version in (29, 30, 38, 46):
        bsp_path = directory / f"options-{version}.bsp"
        if version == 29:
            smoke._write_q1_submodel_bsp(bsp_path)
        elif version == 30:
            smoke._write_goldsrc_bsp(bsp_path)
        else:
            smoke._write_ibsp_submodels(bsp_path, version=version)
        data = bsp_path.read_bytes().replace(b"func_door", b"trigger_x")
        bsp_path.write_bytes(data)
        for grouped in (True, False):
            for handling in ("HIDDEN", "VISIBLE", "SKIP"):
                before = set(bpy.data.collections.keys())
                assert bpy.ops.quakeblend.import_bsp(filepath=str(bsp_path), texture_root=str(directory),
                    create_materials=False, group_entities=grouped, trigger_handling=handling) == {"FINISHED"}
                root = next(collection for collection in bpy.context.scene.collection.children if collection.name not in before)
                assert bool(root.children) == grouped
                meshes = [obj for obj in root.all_objects if obj.type == "MESH"]
                assert len(meshes) == (1 if handling == "SKIP" else 3 if version == 46 else 2)
                for obj in meshes:
                    if obj["qb_bsp_model_index"] != 0:
                        assert obj.hide_get() == (handling == "HIDDEN")
                    assert not obj.hide_render
                if version == 30:
                    assembly = importlib.import_module(f"{args.extension_root}.blender.map_assembly")
                    assert all(obj.parent == assembly.assembly_root(root) for obj in meshes)
                if handling == "SKIP":
                    assert root["qb_tool_counts"]["skipped"] == (2 if version == 46 else 1)
            before = set(bpy.data.collections.keys())
            assert bpy.ops.quakeblend.import_bsp(filepath=str(bsp_path), texture_root=str(directory),
                create_materials=False, group_entities=grouped, worldspawn_only=True) == {"FINISHED"}
            root = next(collection for collection in bpy.context.scene.collection.children if collection.name not in before)
            assert sum(obj.type == "MESH" for obj in root.all_objects) == 1
            assert all(obj.type == "MESH" or obj.get("qb_assembly_id") for obj in root.all_objects)
            assert root["qb_tool_counts"]["skipped"] == 0
    saved = directory / "import-options.blend"
    visibility = {obj.name: obj.hide_get() for root in roots for obj in root.all_objects}
    bpy.ops.wm.save_as_mainfile(filepath=str(saved))
    bpy.ops.wm.open_mainfile(filepath=str(saved))
    assert visibility == {name: bpy.data.objects[name].hide_get() for name in visibility}
    (directory / "report.json").write_text(json.dumps({"visibility": visibility}, indent=2), encoding="utf-8")
    print("IMPORT_OPTIONS_SMOKE_OK content visibility grouping source-export BSP-models persistence")


if __name__ == "__main__":
    main()
