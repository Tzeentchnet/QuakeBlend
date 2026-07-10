"""Headless Blender runtime smoke checks for an installed QuakeBlend extension."""

from __future__ import annotations

import argparse
import importlib
import struct
import sys
import tempfile
from pathlib import Path

import bpy


_Q1_MAP = """
{
"classname" "worldspawn"
{
( -64 -64 -16 ) ( -64 -63 -16 ) ( -64 -64 -15 ) SMOKE 0 0 0 1 1
( -64 -64 -16 ) ( -64 -64 -15 ) ( -63 -64 -16 ) SMOKE 0 0 0 1 1
( -64 -64 -16 ) ( -63 -64 -16 ) ( -64 -63 -16 ) SMOKE 0 0 0 1 1
( 64 64 16 ) ( 64 64 17 ) ( 64 65 16 ) SMOKE 0 0 0 1 1
( 64 64 16 ) ( 65 64 16 ) ( 64 64 17 ) SMOKE 0 0 0 1 1
( 64 64 16 ) ( 64 65 16 ) ( 65 64 16 ) SMOKE 0 0 0 1 1
}
}
{
"classname" "info_player_start"
"origin" "8 16 24"
"message" "smoke anchor"
}
"""


_Q3_PATCH_MAP = """
{
"classname" "worldspawn"
{
patchDef2
{
// Preserve this comment and editor fields during Q3 export.
textures/smoke/patch
( 3 3 7 8 9 )
(
( ( 0.123456789 0 0 0 0 ) ( 1 0 0 0.5 0 ) ( 2 0 0 1 0 ) )
( ( 0 1 0 0 0.5 ) ( 1 1 1 0.5 0.5 ) ( 2 1 0 1 0.5 ) )
( ( 0 2 0 0 1 ) ( 1 2 0 0.5 1 ) ( 2 2 0 1 1 ) )
)
}
}
}
{
"classname" "info_player_start"
"origin" "8 16 24"
}
"""


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--extension-root",
        default="bl_ext.user_default.quakeblend",
        help="Installed extension module namespace",
    )
    arguments = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return parser.parse_args(arguments)


def _check_registration(extension_root: str) -> None:
    module = importlib.import_module(extension_root)
    prefs = importlib.import_module(f"{extension_root}.blender.prefs")
    enabled = {addon.module for addon in bpy.context.preferences.addons}

    assert module.__name__ == extension_root
    assert prefs.PACKAGE == extension_root
    assert extension_root in enabled
    assert all(
        hasattr(bpy.ops.quakeblend, operator)
        for operator in ("import_map", "import_bsp", "import_wad", "export_map")
    )


def _check_materials(extension_root: str) -> None:
    materials = importlib.import_module(
        f"{extension_root}.blender.builder_materials"
    )
    rgba = bytes((255, 128, 64, 128))
    mask = bytes((255, 255, 255, 255))
    first_image = materials.create_image(
        "QB Smoke Image",
        1,
        1,
        rgba,
        asset_key="smoke|source-a|image",
    )
    assert materials.create_image(
        "QB Smoke Image",
        1,
        1,
        rgba,
        asset_key="smoke|source-a|image",
    ) is first_image
    second_image = materials.create_image(
        "QB Smoke Image",
        1,
        1,
        rgba,
        asset_key="smoke|source-b|image",
    )
    emission_image = materials.create_image(
        "QB Smoke Emission",
        1,
        1,
        mask,
        asset_key="smoke|source-a|emission",
    )
    assert first_image is not second_image

    flags = materials.MaterialFlags(
        transparent_alpha=0.5,
        texture_alpha=True,
        emissive=True,
    )
    first_material = materials.get_or_create_material(
        "QB Smoke Material",
        first_image,
        emission_image,
        flags,
        asset_key="smoke|source-a|material",
    )
    assert materials.get_or_create_material(
        "QB Smoke Material",
        first_image,
        emission_image,
        flags,
        asset_key="smoke|source-a|material",
    ) is first_material
    second_material = materials.get_or_create_material(
        "QB Smoke Material",
        second_image,
        flags=materials.MaterialFlags(),
        asset_key="smoke|source-b|material",
    )
    assert first_material is not second_material
    assert first_material.surface_render_method == "DITHERED"

    nodes = first_material.node_tree.nodes
    principled = next(node for node in nodes if node.type == "BSDF_PRINCIPLED")
    output = next(node for node in nodes if node.type == "OUTPUT_MATERIAL")
    emission_name = (
        "Emission Color" if "Emission Color" in principled.inputs else "Emission"
    )
    assert principled.inputs["Alpha"].is_linked
    assert principled.inputs[emission_name].is_linked
    assert output.inputs["Surface"].is_linked
    assert (
        output.inputs["Surface"].links[0].from_node.as_pointer()
        == principled.as_pointer()
    )


def _check_transaction(extension_root: str) -> None:
    transaction = importlib.import_module(f"{extension_root}.blender.transaction")
    survivor = bpy.data.materials.new("QB Smoke Survivor")
    created_pointers: set[int] = set()

    try:
        with transaction.ImportTransaction():
            collection = bpy.data.collections.new("QB Smoke Rollback Collection")
            bpy.context.scene.collection.children.link(collection)
            mesh = bpy.data.meshes.new("QB Smoke Rollback Mesh")
            obj = bpy.data.objects.new("QB Smoke Rollback Object", mesh)
            collection.objects.link(obj)
            material = bpy.data.materials.new("QB Smoke Rollback Material")
            image = bpy.data.images.new("QB Smoke Rollback Image", 1, 1)
            light = bpy.data.lights.new("QB Smoke Rollback Light", "POINT")
            camera = bpy.data.cameras.new("QB Smoke Rollback Camera")
            created_pointers.update(
                datablock.as_pointer()
                for datablock in (
                    collection, mesh, obj, material, image, light, camera,
                )
            )
            raise RuntimeError("intentional smoke rollback")
    except RuntimeError as exc:
        assert str(exc) == "intentional smoke rollback"
    else:
        raise AssertionError("transaction did not propagate the test exception")

    remaining_pointers = {
        datablock.as_pointer()
        for collection_name in (
            "objects", "collections", "meshes", "materials", "images",
            "lights", "cameras",
        )
        for datablock in getattr(bpy.data, collection_name)
    }
    assert created_pointers.isdisjoint(remaining_pointers)
    assert survivor.name in bpy.data.materials


def _collections_below(root: bpy.types.Collection) -> list[bpy.types.Collection]:
    collections = [root]
    for child in root.children:
        collections.extend(_collections_below(child))
    return collections


def _objects_below(root: bpy.types.Collection) -> list[bpy.types.Object]:
    by_pointer: dict[int, bpy.types.Object] = {}
    for collection in _collections_below(root):
        for obj in collection.objects:
            by_pointer[obj.as_pointer()] = obj
    return list(by_pointer.values())


def _source_roots(path: Path) -> list[bpy.types.Collection]:
    source = str(path.resolve())
    return [
        collection
        for collection in bpy.data.collections
        if collection.get("qb_source_map") == source
    ]


def _check_map_workflows(extension_root: str, directory: Path) -> None:
    map_q1 = importlib.import_module(f"{extension_root}.formats.map_q1")
    q1_path = directory / "smoke_q1.map"
    q1_path.write_text(_Q1_MAP, encoding="ascii")
    result = bpy.ops.quakeblend.import_map(
        filepath=str(q1_path),
        scale=0.125,
        source_game="Q1",
        texture_root=str(directory),
        wad_paths=";",
        import_entities=True,
        import_lights=True,
        patch_level=2,
    )
    assert result == {"FINISHED"}
    q1_roots = _source_roots(q1_path)
    assert len(q1_roots) == 1
    q1_root = q1_roots[0]
    assert q1_root["qb_source_game"] == "q1"
    assert abs(float(q1_root["qb_import_scale"]) - 0.125) < 1e-9
    q1_objects = _objects_below(q1_root)
    anchors = {
        int(obj["qb_entity_index"]): obj
        for obj in q1_objects
        if obj.get("qb_entity_role") == "ENTITY"
    }
    assert set(anchors) == {0, 1}
    assert tuple(round(value, 6) for value in anchors[1].location) == (1.0, 2.0, 3.0)
    assert anchors[1]["qb_prop_message"] == "smoke anchor"
    assert any(obj.type == "MESH" and len(obj.data.vertices) == 8 for obj in q1_objects)

    q3_path = directory / "smoke_q3.map"
    q3_path.write_text(_Q3_PATCH_MAP, encoding="ascii")
    for _ in range(2):
        result = bpy.ops.quakeblend.import_map(
            filepath=str(q3_path),
            scale=0.25,
            source_game="Q3",
            texture_root=str(directory),
            wad_paths=";",
            import_entities=True,
            import_lights=True,
            patch_level=2,
        )
        assert result == {"FINISHED"}

    q3_roots = _source_roots(q3_path)
    assert len(q3_roots) == 2
    patch_objects: list[bpy.types.Object] = []
    for root in q3_roots:
        patches = [
            obj for obj in _objects_below(root) if "qb_patch_control_grid" in obj
        ]
        assert len(patches) == 1
        assert list(patches[0]["qb_patch_size"]) == [3, 3]
        patch_objects.extend(patches)

    export_root = q3_roots[-1]
    export_objects = _objects_below(export_root)
    anchor = next(
        obj
        for obj in export_objects
        if obj.get("qb_entity_role") == "ENTITY"
        and int(obj["qb_entity_index"]) == 1
    )
    anchor.location = (3.0, 5.0, 7.0)
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    patch_objects[-1].select_set(True)
    bpy.context.view_layer.objects.active = patch_objects[-1]

    exported_path = directory / "smoke_q3_exported.map"
    result = bpy.ops.quakeblend.export_map(
        filepath=str(exported_path),
        target_game="Q3",
        projection="AUTO",
        patch_handling="KEEP",
        tessellation_level=2,
        extrusion_thickness=1.0,
        texture_map_path="",
        use_scene_entity_edits=True,
    )
    assert result == {"FINISHED"}
    exported_text = exported_path.read_text(encoding="utf-8")
    assert "// Preserve this comment and editor fields during Q3 export." in exported_text
    assert "( 3 3 7 8 9 )" in exported_text
    assert "0.123456789" in exported_text
    exported = map_q1.parse_path(exported_path)
    assert exported.entities[1].properties["origin"] == "12 20 28"


def _write_empty_bsp(path: Path, *, version: int, lump_count: int,
                     ibsp: bool) -> None:
    entities = b'{ "classname" "worldspawn" }\n\x00'
    prefix = (b"IBSP" + struct.pack("<i", version)) if ibsp else struct.pack("<i", version)
    header_size = len(prefix) + lump_count * 8
    lumps = [
        (header_size, len(entities)) if index == 0 else (header_size, 0)
        for index in range(lump_count)
    ]
    path.write_bytes(
        prefix
        + b"".join(struct.pack("<ii", offset, size) for offset, size in lumps)
        + entities
    )


def _write_wad(path: Path) -> None:
    texture_name = b"QB_WAD_SMOKE".ljust(16, b"\x00")
    payload = (
        texture_name
        + struct.pack("<II", 1, 1)
        + struct.pack("<IIII", 40, 41, 42, 43)
        + bytes((1, 2, 3, 4))
    )
    entry_offset = 12
    directory_offset = entry_offset + len(payload)
    directory = (
        struct.pack("<iii", entry_offset, len(payload), len(payload))
        + bytes((0x44, 0, 0, 0))
        + texture_name
    )
    path.write_bytes(
        b"WAD2" + struct.pack("<ii", 1, directory_offset) + payload + directory
    )


def _check_bsp_and_wad_workflows(directory: Path) -> None:
    bsp_specs = (
        ("q1", 29, 15, False),
        ("q2", 38, 19, True),
        ("q3", 46, 17, True),
    )
    for name, version, lump_count, ibsp in bsp_specs:
        path = directory / f"smoke_bsp_{name}.bsp"
        _write_empty_bsp(
            path,
            version=version,
            lump_count=lump_count,
            ibsp=ibsp,
        )
        result = bpy.ops.quakeblend.import_bsp(
            filepath=str(path),
            scale=0.03125,
            texture_root=str(directory),
            import_entities=True,
            import_lights=True,
            patch_level=2,
        )
        assert result == {"FINISHED"}
        assert any(collection.name.startswith(path.stem) for collection in bpy.data.collections)

    wad_path = directory / "smoke.wad"
    _write_wad(wad_path)
    result = bpy.ops.quakeblend.import_wad(
        filepath=str(wad_path),
        create_materials=True,
    )
    assert result == {"FINISHED"}
    assert any(
        str(material.get("qb_asset_key", "")).startswith("wad|")
        and "QB_WAD_SMOKE" in material.name
        for material in bpy.data.materials
    )


def _check_unregister(extension_root: str) -> None:
    module = importlib.import_module(extension_root)
    rna_identifiers = (
        "QUAKEBLEND_OT_import_map",
        "QUAKEBLEND_OT_import_bsp",
        "QUAKEBLEND_OT_import_wad",
        "QUAKEBLEND_OT_export_map",
    )
    registered = bpy.types.Operator.bl_rna_get_subclass_py
    assert all(registered(identifier) is not None for identifier in rna_identifiers)
    module.unregister()
    assert all(registered(identifier) is None for identifier in rna_identifiers)
    module.register()
    assert all(registered(identifier) is not None for identifier in rna_identifiers)


def main() -> None:
    args = _arguments()
    _check_registration(args.extension_root)
    _check_materials(args.extension_root)
    _check_transaction(args.extension_root)
    with tempfile.TemporaryDirectory(prefix="quakeblend-smoke-") as temp_dir:
        directory = Path(temp_dir)
        _check_map_workflows(args.extension_root, directory)
        _check_bsp_and_wad_workflows(directory)
    _check_unregister(args.extension_root)
    print(
        "QUAKEBLEND_SMOKE_OK registration materials transaction "
        "map bsp wad export unregister"
    )


if __name__ == "__main__":
    main()