"""Headless Blender runtime smoke checks for an installed QuakeBlend extension."""

from __future__ import annotations

import argparse
import importlib
import math
import struct
import sys
import tempfile
from pathlib import Path

import bpy
from mathutils import Vector


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


# Every face carries the Quake 2 `contents flags value` trailer; only the first
# face uses non-zero values so both branches of the tagger are exercised.
_Q2_MAP = """
{
"classname" "worldspawn"
{
( -64 -64 -16 ) ( -64 -63 -16 ) ( -64 -64 -15 ) e1u1/metal1 0 0 0 1 1 1 4 100
( -64 -64 -16 ) ( -64 -64 -15 ) ( -63 -64 -16 ) e1u1/metal1 0 0 0 1 1 0 0 0
( -64 -64 -16 ) ( -63 -64 -16 ) ( -64 -63 -16 ) e1u1/metal1 0 0 0 1 1 0 0 0
( 64 64 16 ) ( 64 64 17 ) ( 64 65 16 ) e1u1/metal1 0 0 0 1 1 0 0 0
( 64 64 16 ) ( 65 64 16 ) ( 64 64 17 ) e1u1/metal1 0 0 0 1 1 0 0 0
( 64 64 16 ) ( 64 65 16 ) ( 65 64 16 ) e1u1/metal1 0 0 0 1 1 0 0 0
}
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

    # MaterialCache must fold case and separators so `.map` face names need not
    # match the casing stored inside a WAD.
    cache = materials.MaterialCache()
    cache.add("Smoke\\Wall1", first_material)
    assert cache.get("smoke/WALL1") is first_material
    assert "  SMOKE/wall1  " in cache
    assert cache.setdefault("smoke/wall1", second_material) is first_material
    assert cache.get("smoke/wall2") is None
    assert len(cache) == 1


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


def _check_import_failure_rollback(extension_root: str, directory: Path) -> None:
    patch = importlib.import_module(f"{extension_root}.formats.patch")
    original_tessellate = patch.tessellate

    def fail_tessellation(*_args, **_kwargs):
        raise RuntimeError("intentional patch smoke failure")

    path = directory / "smoke_patch_failure.map"
    path.write_text(_Q3_PATCH_MAP, encoding="ascii")
    patch.tessellate = fail_tessellation
    try:
        try:
            result = bpy.ops.quakeblend.import_map(
                filepath=str(path),
                scale=0.25,
                source_game="Q3",
                texture_root=str(directory),
                wad_paths=";",
                import_entities=True,
                import_lights=True,
                patch_level=2,
            )
        except RuntimeError as exc:
            assert "intentional patch smoke failure" in str(exc)
            result = {"CANCELLED"}
    finally:
        patch.tessellate = original_tessellate

    assert result == {"CANCELLED"}
    assert _source_roots(path) == []


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
        control_grid = patches[0]["qb_patch_control_grid"]
        assert len(control_grid) == 9
        assert all(len(control) == 5 for control in control_grid)
        assert abs(float(control_grid[0][0]) - 0.123456789) < 1e-6
        patch_objects.extend(patches)

    export_root = q3_roots[-1]
    export_objects = _objects_below(export_root)
    anchor = next(
        obj
        for obj in export_objects
        if obj.get("qb_entity_role") == "ENTITY"
        and int(obj["qb_entity_index"]) == 1
    )
    anchor.location = (31234.567, 52345.678, -73456.789)
    expected_origin = tuple(float(component) / 0.25 for component in anchor.location)
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
    actual_origin = tuple(
        float(component)
        for component in exported.entities[1].properties["origin"].split()
    )
    assert max(
        abs(actual - expected)
        for actual, expected in zip(actual_origin, expected_origin)
    ) < 0.001


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


def _write_q1_submodel_bsp(path: Path) -> None:
    """A v29 BSP with textured and missing-texture submodel quads."""
    entities = (
        b'{ "classname" "worldspawn" }\n'
        b'{ "classname" "func_door" "model" "*1" "targetname" "smoke_door" }\n'
        b"\x00"
    )
    vertices = b"".join(
        struct.pack("<3f", x, y, z)
        for x, y, z in (
            (0, 0, 0), (64, 0, 0), (64, 64, 0), (0, 64, 0),
            (0, 0, 64), (64, 0, 64), (64, 64, 64), (0, 64, 64),
        )
    )
    # Edge 0 is unused by convention: signed ledge indices cannot encode -0.
    edge_pairs = [
        (0, 0),
        (0, 1), (1, 2), (2, 3), (3, 0),
        (4, 5), (5, 6), (6, 7), (7, 4),
    ]
    edges = b"".join(struct.pack("<HH", a, b) for a, b in edge_pairs)
    ledges = b"".join(struct.pack("<i", i) for i in range(1, 9))
    texinfo = b"".join(
        struct.pack(
            "<8fII",
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            miptex_index, 0,
        )
        for miptex_index in (0, 1)
    )
    faces = b"".join(
        struct.pack(
            "<HHiHHBBBBi",
            0, 0, ledge_id, 4, texinfo_id, 0, 0, 0, 0, -1,
        )
        for texinfo_id, ledge_id in enumerate((0, 4))
    )
    models = b"".join(
        struct.pack(
            "<9f7i",
            0.0, 0.0, 0.0, 64.0, 64.0, 64.0, 0.0, 0.0, 0.0,
            0, 0, 0, 0, 0,
            first_face, 1,
        )
        for first_face in (0, 1)
    )

    texture = (
        b"QB_BSP_SMOKE".ljust(16, b"\x00")
        + struct.pack("<II", 1, 1)
        + struct.pack("<IIII", 40, 41, 41, 41)
        + bytes((1,))
    )
    miptextures = struct.pack("<iii", 2, 12, -1) + texture

    lumps = {
        0: entities,
        2: miptextures,
        3: vertices,
        6: texinfo,
        7: faces,
        12: edges,
        13: ledges,
        14: models,
    }
    header_size = 4 + 15 * 8
    cursor = header_size
    header = [struct.pack("<i", 29)]
    for index in range(15):
        blob = lumps.get(index, b"")
        header.append(struct.pack("<ii", cursor if blob else header_size, len(blob)))
        cursor += len(blob)
    path.write_bytes(
        b"".join(header) + b"".join(lumps.get(i, b"") for i in range(15))
    )


def _write_ibsp_submodels(path: Path, *, version: int) -> None:
    entities = (
        b'{ "classname" "worldspawn" }\n'
        b'{ "classname" "func_door" "model" "*1" }\n'
        b'{ "classname" "info_player_start" "origin" "0 0 24" }\n'
        b'{ "classname" "light" "origin" "0 0 48" }\n\x00'
    )
    positions = [(0, 0, 0), (64, 0, 0), (0, 64, 0),
                 (0, 0, 64), (64, 0, 64), (0, 64, 64)]
    if version == 38:
        texture = "QB_FILTER_TEXTURE"
        wal_path = path.parent / f"{texture}.wal"
        wal_path.write_bytes(
            texture.encode("ascii").ljust(32, b"\x00")
            + struct.pack("<6I", 32, 16, 100, 612, 740, 772)
            + bytes(32) + struct.pack("<3I", 0, 0, 0) + bytes(680)
        )
        lumps = {
            0: entities,
            2: b"".join(struct.pack("<3f", *position) for position in positions),
            5: (struct.pack("<8fii", 1, 0, 0, 0, 0, 1, 0, 0, 0, 0)
                + texture.encode("ascii").ljust(32, b"\x00") + struct.pack("<i", -1)),
            6: b"".join(struct.pack("<HHiHH4Bi", 0, 0, first_edge, 3, 0, 0, 0, 0, 0, -1)
                        for first_edge in (0, 3)),
            11: b"".join(struct.pack("<2H", *edge) for edge in
                         ((0, 0), (0, 1), (1, 2), (2, 0), (3, 4), (4, 5), (5, 3))),
            12: struct.pack("<6i", 1, 2, 3, 4, 5, 6),
            13: b"".join(struct.pack("<9f3i", 0, 0, 0, 64, 64, 64, 0, 0, 0, 0, first_face, 1)
                         for first_face in (0, 1)),
        }
        lump_count = 19
    else:
        positions.extend((column * 32, row * 32, 128)
                         for row in range(3) for column in range(3))
        faces = b"".join(
            struct.pack("<12i12f2i", 0, -1, face_type, first_vertex, vertex_count,
                        0, 0, -1, 0, 0, 0, 0,
                        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, width, height)
            for face_type, first_vertex, vertex_count, width, height in (
                (1, 0, 3, 0, 0), (1, 3, 3, 0, 0), (2, 6, 9, 3, 3),
            )
        )
        lumps = {
            0: entities,
            1: b"QB_FILTER_TEXTURE".ljust(64, b"\x00") + struct.pack("<2i", 0, 0),
            7: b"".join(struct.pack("<6f4i", 0, 0, 0, 64, 64, 128, first_face, count, 0, 0)
                        for first_face, count in ((0, 1), (1, 2))),
            10: b"".join(struct.pack("<10f4B", *position, position[0] / 64, position[1] / 64,
                                    0, 0, 0, 0, 1, 255, 255, 255, 255)
                         for position in positions),
            13: faces,
        }
        lump_count = 17
    header_size = 8 + lump_count * 8
    cursor = header_size
    header = [b"IBSP", struct.pack("<i", version)]
    for index in range(lump_count):
        blob = lumps.get(index, b"")
        header.append(struct.pack("<ii", cursor, len(blob)))
        cursor += len(blob)
    path.write_bytes(b"".join(header) + b"".join(lumps.get(index, b"") for index in range(lump_count)))


def _check_bsp_import_controls(directory: Path) -> None:
    for version in (29, 38, 46):
        for create_materials in (False, True):
            for import_brush_entities in (False, True):
                path = directory / f"controls_{version}_{create_materials}_{import_brush_entities}.bsp"
                if version == 29:
                    _write_q1_submodel_bsp(path)
                else:
                    _write_ibsp_submodels(path, version=version)
                before = (len(bpy.data.materials), len(bpy.data.images))
                assert bpy.ops.quakeblend.import_bsp(
                    filepath=str(path), texture_root=str(directory), scale=0.03125,
                    create_materials=create_materials,
                    import_brush_entities=import_brush_entities,
                    import_entities=True, import_lights=True, import_cameras=True,
                    patch_level=2,
                ) == {"FINISHED"}
                root = bpy.data.collections[path.stem]
                meshes = [obj for obj in root.all_objects if obj.type == "MESH"]
                expected_count = (3 if version == 46 else 2) if import_brush_entities else 1
                assert len(meshes) == expected_count
                assert {obj["qb_bsp_model_index"] for obj in meshes} == (
                    {0, 1} if import_brush_entities else {0}
                )
                if not create_materials:
                    assert before == (len(bpy.data.materials), len(bpy.data.images))
                    assert all(len(obj.data.materials) == 0 for obj in meshes)
                else:
                    assert all(len(obj.data.materials) > 0 for obj in meshes)
                assert all(obj.data.uv_layers.active is not None for obj in meshes)
                if version == 38:
                    world = next(obj for obj in meshes if obj["qb_bsp_model_index"] == 0)
                    uvs = {tuple(round(value, 6) for value in loop.uv)
                           for loop in world.data.uv_layers.active.data}
                    assert uvs == {(0.0, 1.0), (2.0, 1.0), (0.0, -3.0)}
                if version != 29:
                    assert len([obj for obj in root.all_objects if obj.type == "CAMERA"]) == 1
                    assert len([obj for obj in root.all_objects if obj.type == "LIGHT"]) == 1


def _write_wad(path: Path, texture: str = "QB_WAD_SMOKE", *,
               wad3: bool = False, pixel: int = 1,
               color: tuple[int, int, int] = (51, 102, 153)) -> None:
    texture_name = texture.encode("ascii").ljust(16, b"\x00")
    payload = (
        texture_name
        + struct.pack("<II", 8, 8)
        + struct.pack("<IIII", 40, 104, 120, 124)
        + bytes((pixel,)) * 85
    )
    if wad3:
        payload += struct.pack("<H", 256) + bytes(color) * 256
    entry_offset = 12
    directory_offset = entry_offset + len(payload)
    directory = (
        struct.pack("<iii", entry_offset, len(payload), len(payload))
        + bytes((0x43 if wad3 else 0x44, 0, 0, 0))
        + texture_name
    )
    path.write_bytes(
        (b"WAD3" if wad3 else b"WAD2")
        + struct.pack("<ii", 1, directory_offset) + payload + directory
    )


def _check_wad3_palettes(directory: Path) -> None:
    for wad3 in (False, True):
        name = "QB_WAD3_COLOR" if wad3 else "QB_WAD2_GLOW"
        path = directory / f"{name}.wad"
        _write_wad(path, texture=name, wad3=wad3, pixel=224)
        assert bpy.ops.quakeblend.import_wad(
            filepath=str(path), create_materials=True,
        ) == {"FINISHED"}
        material = next(mat for mat in bpy.data.materials if mat.name == name)
        images = [node.image for node in material.node_tree.nodes
                  if node.type == "TEX_IMAGE"]
        assert len(images) == (1 if wad3 else 2)
        if wad3:
            assert tuple(round(value, 6) for value in images[0].pixels[:4]) == (
                0.2, 0.4, 0.6, 1.0,
            )

    path = directory / "masked_wad3.wad"
    _write_wad(path, texture="{QB_WAD3_MASK", wad3=True, pixel=255)
    assert bpy.ops.quakeblend.import_wad(
        filepath=str(path), create_materials=True,
    ) == {"FINISHED"}
    material = bpy.data.materials["{QB_WAD3_MASK"]
    image = next(node.image for node in material.node_tree.nodes
                 if node.type == "TEX_IMAGE")
    assert image.pixels[3] == 0.0
    bsdf = next(node for node in material.node_tree.nodes
                if node.type == "BSDF_PRINCIPLED")
    assert bsdf.inputs["Alpha"].is_linked

    wad_path = directory / "map_wad3.wad"
    _write_wad(wad_path, texture="QB_WAD3_MAP", wad3=True, pixel=254)
    map_path = directory / "map_wad3.map"
    map_path.write_text(_Q1_MAP.replace("SMOKE", "QB_WAD3_MAP"), encoding="ascii")
    assert bpy.ops.quakeblend.import_map(
        filepath=str(map_path), wad_paths=str(wad_path),
        source_game="Q1", import_entities=False,
    ) == {"FINISHED"}
    root = _source_roots(map_path)[0]
    brushes = [obj for obj in _objects_below(root) if obj.type == "MESH"]
    assert brushes
    for brush in brushes:
        for material in brush.data.materials:
            assert not material.get("qb_placeholder", False)
            images = [node.image for node in material.node_tree.nodes
                      if node.type == "TEX_IMAGE"]
            assert len(images) == 1
            assert tuple(round(value, 6) for value in images[0].pixels[:4]) == (
                0.2, 0.4, 0.6, 1.0,
            )


def _check_texture_case_and_face_flags(directory: Path) -> None:
    """WAD lookups must fold case, and Q2 face trailers must reach Blender."""
    wad_path = directory / "smoke_lowercase.wad"
    _write_wad(wad_path, texture="smoke")          # map face says "SMOKE"
    map_path = directory / "smoke_case.map"
    map_path.write_text(_Q1_MAP, encoding="ascii")
    result = bpy.ops.quakeblend.import_map(
        filepath=str(map_path),
        scale=0.125,
        source_game="Q1",
        texture_root=str(directory),
        wad_paths=str(wad_path),
        import_entities=False,
        import_lights=False,
        patch_level=2,
    )
    assert result == {"FINISHED"}
    root = _source_roots(map_path)[0]
    brushes = [
        obj for obj in _objects_below(root)
        if obj.type == "MESH" and obj.data.materials
    ]
    assert brushes, "case-insensitive WAD import produced no textured brushes"
    for obj in brushes:
        for material in obj.data.materials:
            assert "qb_placeholder" not in material, (
                f"'{material.name}' fell back to a placeholder despite a WAD match"
            )

    q2_path = directory / "smoke_q2.map"
    q2_path.write_text(_Q2_MAP, encoding="ascii")
    result = bpy.ops.quakeblend.import_map(
        filepath=str(q2_path),
        scale=0.125,
        source_game="Q2",
        texture_root=str(directory),
        wad_paths=";",
        import_entities=False,
        import_lights=False,
        patch_level=2,
    )
    assert result == {"FINISHED"}
    q2_root = _source_roots(q2_path)[0]
    flagged = [obj for obj in _objects_below(q2_root) if "qb_face_flags" in obj]
    assert len(flagged) == 1
    brush = flagged[0]
    assert list(brush["qb_face_contents"]) == [1, 0, 0, 0, 0, 0]
    assert list(brush["qb_face_flags"]) == [4, 0, 0, 0, 0, 0]
    assert list(brush["qb_face_value"]) == [100, 0, 0, 0, 0, 0]
    assert brush["qb_face_textures"].split("\n") == ["e1u1/metal1"] * 6


def _check_bsp_submodels(directory: Path) -> None:
    """The models lump must yield one object per submodel, not one world mesh."""
    path = directory / "smoke_bsp_submodels.bsp"
    _write_q1_submodel_bsp(path)
    result = bpy.ops.quakeblend.import_bsp(
        filepath=str(path),
        scale=0.03125,
        texture_root=str(directory),
        import_entities=True,
        import_lights=True,
        light_energy=1.0,
        patch_level=2,
    )
    assert result == {"FINISHED"}
    root = next(
        collection for collection in bpy.data.collections
        if collection.name == path.stem
    )
    meshes = [
        obj for obj in _objects_below(root)
        if obj.type == "MESH" and "qb_bsp_model_index" in obj
    ]
    by_model = {int(obj["qb_bsp_model_index"]): obj for obj in meshes}
    assert set(by_model) == {0, 1}
    # Compacting must drop the other submodel's vertices from each mesh.
    assert len(by_model[0].data.vertices) == 4
    assert len(by_model[1].data.vertices) == 4
    assert by_model[1]["qb_prop_targetname"] == "smoke_door"
    assert by_model[1].name.startswith(f"{path.stem}_func_door")
    world_material = by_model[0].data.materials[
        by_model[0].data.polygons[0].material_index
    ]
    missing_material = by_model[1].data.materials[
        by_model[1].data.polygons[0].material_index
    ]
    assert "qb_placeholder" not in world_material
    assert bool(missing_material.get("qb_placeholder", False))
    assert world_material.as_pointer() != missing_material.as_pointer()
    missing_image = next(
        node.image
        for node in missing_material.node_tree.nodes
        if node.type == "TEX_IMAGE"
    )
    assert tuple(round(channel, 6) for channel in missing_image.pixels[:4]) == (
        1.0, 0.0, 1.0, 1.0,
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


def _check_cameras(extension_root: str, directory: Path) -> None:
    builder = importlib.import_module(f"{extension_root}.blender.builder_entities")
    collection = bpy.data.collections.new("QB Camera Checks")
    bpy.context.scene.collection.children.link(collection)
    previous_camera = bpy.context.scene.camera
    cases = (
        ({"angle": "0"}, (1, 0, 0), (0, 0, 1)),
        ({"angle": "90"}, (0, 1, 0), (0, 0, 1)),
        ({"mangle": "30 90 0"}, (0, math.sqrt(3) / 2, -0.5), (0, 0.5, math.sqrt(3) / 2)),
        ({"mangle": "0 0 90"}, (1, 0, 0), (0, -1, 0)),
        ({"mangle": "bad", "angle": "90"}, (0, 1, 0), (0, 0, 1)),
        ({"mangle": "nan 0 0", "angle": "inf"}, (1, 0, 0), (0, 0, 1)),
    )
    for angles, forward, up in cases:
        entity = {"classname": "info_intermission", "origin": "8 16 24", **angles}
        obj = builder.build_entity(entity, collection, scale=0.125)
        assert obj is not None and obj.type == "CAMERA"
        rotation = obj.rotation_euler.to_matrix()
        assert (rotation @ Vector((0, 0, -1)) - Vector(forward)).length < 1e-5
        assert (rotation @ Vector((0, 1, 0)) - Vector(up)).length < 1e-5
        assert abs(obj.data.angle_x - math.pi / 2) < 1e-5
        assert tuple(obj.location) == (1.0, 2.0, 3.0)
        assert obj["qb_prop_classname"] == "info_intermission"
    assert bpy.context.scene.camera == previous_camera

    map_path = directory / "no_cameras.map"
    map_path.write_text(_Q1_MAP, encoding="ascii")
    assert bpy.ops.quakeblend.import_map(
        filepath=str(map_path), wad_paths=";", import_entities=True,
        import_cameras=False,
    ) == {"FINISHED"}
    root = _source_roots(map_path)[0]
    assert any(obj.type == "MESH" for obj in _objects_below(root))
    assert not any(obj.get("qb_prop_classname") == "info_player_start"
                   for obj in _objects_below(root))

    runner = importlib.import_module(f"{extension_root}.blender.import_runner_bsp")
    operator = type("CameraOptions", (), {"import_cameras": False})()
    entities = [
        {"classname": "info_player_start", "origin": "0 0 0"},
        {"classname": "light", "origin": "0 0 0"},
        {"classname": "info_null", "origin": "0 0 0"},
    ]
    root = bpy.data.collections.new("QB BSP Camera Filter")
    runner._build_bsp_entities(operator, entities, root, "camera_filter", scale=0.125)
    assert sorted(obj.type for obj in root.all_objects) == ["EMPTY", "LIGHT"]


def _write_goldsrc_bsp(path: Path, *, color: tuple[int, int, int] = (51, 102, 153),
                       origin: str = "128 64 32", extra_entities: str = "") -> None:
    entities = (
        '{ "classname" "worldspawn" "wad" "untrusted.wad" }\n'
        '{ "classname" "func_door" "model" "*1" "origin" "' + origin + '" }\n'
        '{ "classname" "light" "origin" "8 16 24" "_light" "255 128 0 200" }\n'
        '{ "classname" "light_spot" "origin" "0 0 16" "_light" "255 255 255 100" }\n'
        '{ "classname" "info_player_start" "origin" "0 0 24" "angles" "0 90 0" }\n'
        '{ "classname" "info_landmark" "origin" "0 0 0" "targetname" "entry" }\n'
        + extra_entities + '\x00'
    ).encode("ascii")
    payloads = [
        (b"{QB_GOLD_EMBED".ljust(16, b"\x00") + struct.pack("<2I4I", 8, 8, 40, 104, 120, 124)
         + bytes((224, 255)) * 32 + bytes((224,)) * 21
         + struct.pack("<H", 256) + bytes(color) * 256),
        b"QB_GOLD_WAD".ljust(16, b"\x00") + struct.pack("<2I4I", 16, 32, 0, 0, 0, 0),
        b"{QB_GOLD_IMAGE".ljust(16, b"\x00") + struct.pack("<2I4I", 32, 16, 0, 0, 0, 0),
        None,
        b"../outside_gold".ljust(16, b"\x00") + struct.pack("<2I4I", 8, 8, 0, 0, 0, 0),
    ]
    cursor = 4 + len(payloads) * 4
    offsets = []
    for payload in payloads:
        offsets.append(cursor if payload is not None else -1)
        cursor += len(payload) if payload is not None else 0
    miptextures = (struct.pack("<i", len(payloads))
                   + b"".join(struct.pack("<i", offset) for offset in offsets)
                   + b"".join(payload for payload in payloads if payload is not None))
    face_textures = (0, 1, 2, 3, 4, 1)
    vertices = b"".join(struct.pack("<3f", horizontal, vertical, face_index * 8)
                        for face_index in range(6)
                        for horizontal, vertical in ((0, 0), (64, 0), (64, 64), (0, 64)))
    edges = struct.pack("<2H", 0, 0) + b"".join(
        struct.pack("<2H", face_index * 4 + corner, face_index * 4 + (corner + 1) % 4)
        for face_index in range(6) for corner in range(4)
    )
    lumps = {
        0: entities, 2: miptextures, 3: vertices,
        6: b"".join(struct.pack("<8f2I", 1, 0, 0, 0, 0, 1, 0, 0, texture_index, 0)
                    for texture_index in range(5)),
        7: b"".join(struct.pack("<HHiHH4Bi", 0, 0, index * 4, 4, texture_index, 0, 255, 255, 255, -1)
                    for index, texture_index in enumerate(face_textures)),
        12: edges,
        13: b"".join(struct.pack("<i", index) for index in range(1, 25)),
        14: b"".join(struct.pack("<9f7i", 0, 0, 0, 64, 64, 64,
                     *( (128, 64, 32) if first_face else (0, 0, 0) ),
                                 0, 0, 0, 0, 0, first_face, count)
                     for first_face, count in ((0, 5), (5, 1))),
    }
    cursor = 124
    header = [struct.pack("<i", 30)]
    for index in range(15):
        blob = lumps.get(index, b"")
        header.append(struct.pack("<2i", cursor, len(blob)))
        cursor += len(blob)
    path.write_bytes(b"".join(header) + b"".join(lumps.get(index, b"") for index in range(15)))


def _check_goldsrc(directory: Path) -> None:
    texture_root = directory / "goldsrc_textures"
    texture_root.mkdir()
    for path in (texture_root / "{QB_GOLD_IMAGE.png", directory / "outside_gold.png"):
        image = bpy.data.images.new("GoldSrc fixture image", 8, 8, alpha=True)
        image.pixels = [0.2, 0.4, 0.6, 0.0] * 64
        image.filepath_raw = str(path)
        image.file_format = "PNG"
        image.save()
        bpy.data.images.remove(image)
    first_wad = directory / "gold_first.wad"
    second_wad = directory / "gold_second.wad"
    embedded_wad = directory / "gold_embedded_conflict.wad"
    _write_wad(first_wad, texture="qb_gold_wad", wad3=True, pixel=224, color=(102, 51, 153))
    _write_wad(second_wad, texture="QB_GOLD_WAD", wad3=True, pixel=224, color=(255, 0, 0))
    _write_wad(embedded_wad, texture="{QB_GOLD_EMBED", wad3=True, pixel=224, color=(255, 0, 0))
    wad_paths = ";".join(str(path) for path in (first_wad, second_wad, embedded_wad))

    def import_level(path: Path, **options) -> bpy.types.Collection:
        assert bpy.ops.quakeblend.import_bsp(
            filepath=str(path), texture_root=str(texture_root), wad_paths=wad_paths,
            scale=0.03125, **options,
        ) == {"FINISHED"}
        return bpy.data.collections[path.stem]

    path = directory / "goldsrc.bsp"
    _write_goldsrc_bsp(path)
    root = import_level(path)
    assert root["qb_source_game"] == "goldsrc"
    assert root["qb_source_bsp"] == str(path.resolve())
    assert "qb_source_map" not in root
    assert "info_landmark" in root["qb_bsp_entities"]
    meshes = [obj for obj in root.all_objects if obj.type == "MESH"]
    assert len(meshes) == 2
    world = next(obj for obj in meshes if obj["qb_bsp_model_index"] == 0)
    brush = next(obj for obj in meshes if obj["qb_bsp_model_index"] == 1)
    assert tuple(brush.location) == (4.0, 2.0, 1.0)
    bpy.context.view_layer.update()
    assert tuple(brush.matrix_world @ brush.data.vertices[0].co) == (4.0, 2.0, 2.25)
    assert len([obj for obj in root.all_objects if obj.get("qb_prop_classname") == "func_door"]) == 1

    def face_material(face_index: int) -> bpy.types.Material:
        return world.data.materials[world.data.polygons[face_index].material_index]

    for face_index, expected in ((0, (0.2, 0.4, 0.6, 1.0)), (1, (0.4, 0.2, 0.6, 1.0))):
        material = face_material(face_index)
        images = [node.image for node in material.node_tree.nodes if node.type == "TEX_IMAGE"]
        assert len(images) == 1
        assert tuple(round(value, 6) for value in images[0].pixels[:4]) == expected
        if face_index == 0:
            assert images[0].pixels[7] == 0.0
    image_material = face_material(2)
    image = next(node.image for node in image_material.node_tree.nodes if node.type == "TEX_IMAGE")
    assert image.pixels[3] == 0.0
    bsdf = next(node for node in image_material.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
    assert bsdf.inputs["Alpha"].is_linked
    assert face_material(3)["qb_placeholder"]
    assert face_material(4)["qb_placeholder"]
    for face_index, expected_uv in (
        (1, {(0.0, 1.0), (4.0, 1.0), (4.0, -1.0), (0.0, -1.0)}),
        (2, {(0.0, 1.0), (2.0, 1.0), (2.0, -3.0), (0.0, -3.0)}),
    ):
        polygon = world.data.polygons[face_index]
        assert {tuple(world.data.uv_layers.active.data[index].uv)
                for index in polygon.loop_indices} == expected_uv
    lights = [obj for obj in root.all_objects if obj.type == "LIGHT"]
    assert len(lights) == 1
    assert abs(lights[0].data.energy - 200 * 4 * math.pi * 0.03125 ** 2) < 1e-5
    assert abs(lights[0].data.color[1] - 128 / 255) < 1e-6
    assert next(obj for obj in root.all_objects if obj.get("qb_prop_classname") == "light_spot").type == "EMPTY"
    camera = next(obj for obj in root.all_objects if obj.type == "CAMERA")
    assert (camera.rotation_euler.to_matrix() @ Vector((0, 0, -1)) - Vector((0, 1, 0))).length < 1e-5

    second_path = directory / "goldsrc_second.bsp"
    _write_goldsrc_bsp(second_path, color=(255, 0, 0))
    second_root = import_level(second_path)
    second_world = next(obj for obj in second_root.all_objects if obj.get("qb_bsp_model_index") == 0)
    second_material = second_world.data.materials[second_world.data.polygons[0].material_index]
    assert second_material != face_material(0)
    assert second_root["qb_import_id"] != root["qb_import_id"]

    bare_path = directory / "goldsrc_bare.bsp"
    _write_goldsrc_bsp(bare_path)
    before = (len(bpy.data.images), len(bpy.data.materials))
    bare_root = import_level(bare_path, create_materials=False, import_brush_entities=False,
                             import_entities=False)
    assert before == (len(bpy.data.images), len(bpy.data.materials))
    bare_meshes = [obj for obj in bare_root.all_objects if obj.type == "MESH"]
    assert len(bare_meshes) == 1
    assert bare_meshes[0]["qb_bsp_model_index"] == 0
    assert len(bare_root.all_objects) == 2
    assert "info_landmark" in bare_root["qb_bsp_entities"]

    failed_path = directory / "goldsrc_failed.bsp"
    _write_goldsrc_bsp(failed_path, origin="nan 0 0")
    categories = ("objects", "collections", "meshes", "materials", "images", "lights", "cameras")
    before = {category: {item.as_pointer() for item in getattr(bpy.data, category)} for category in categories}
    try:
        result = bpy.ops.quakeblend.import_bsp(filepath=str(failed_path), wad_paths=wad_paths,
                                               texture_root=str(texture_root))
    except RuntimeError as exc:
        assert "finite" in str(exc)
        result = {"CANCELLED"}
    assert result == {"CANCELLED"}
    assert before == {category: {item.as_pointer() for item in getattr(bpy.data, category)}
                      for category in categories}


def _check_goldsrc_stitching(extension_root: str, directory: Path) -> None:
    from types import SimpleNamespace

    assembly = importlib.import_module(f"{extension_root}.blender.map_assembly")
    messages = []
    operator = SimpleNamespace(stitch_target="AUTO", report=lambda _levels, message: messages.append(message))

    def import_map(name, origin, destination="", **options):
        path = directory / f"{name}.bsp"
        extra = f'{{ "classname" "info_landmark" "targetname" "join" "origin" "{origin}" }}\n'
        if destination:
            extra += f'{{ "classname" "trigger_changelevel" "map" "{destination}" "landmark" "join" }}\n'
        _write_goldsrc_bsp(path, extra_entities=extra)
        before = {collection.as_pointer() for collection in bpy.data.collections}
        assert bpy.ops.quakeblend.import_bsp(filepath=str(path), create_materials=False,
                                             **options) == {"FINISHED"}
        return next(collection for collection in bpy.data.collections
                    if collection.as_pointer() not in before and collection.get("qb_source_bsp"))

    target = import_map("stitch_old", "64 0 0", import_entities=False)
    target_root = assembly.assembly_root(target)
    target_root.location = (10, 20, 30)
    target.name = "Renamed collection does not affect map identity"
    source = import_map("stitch_new", "16 0 0", "stitch_old", stitch_goldsrc=True)
    source_root = assembly.assembly_root(source)
    assert tuple(source_root.location) == (11.5, 20, 30)
    assert tuple(target_root.location) == (10, 20, 30)
    for obj in source.all_objects:
        if obj != source_root:
            assert obj.parent == source_root
            assert (obj.matrix_world.translation - obj.location - source_root.location).length < 1e-5
    assert source["qb_stitch_targets"] == target["qb_import_id"]
    assert assembly.stitch_import(operator, bpy.context, source)
    assert tuple(source_root.location) == (11.5, 20, 30)

    chain = import_map("stitch_third", "0 0 0", "stitch_new", stitch_goldsrc=True,
                       import_entities=False, import_brush_entities=False)
    assert tuple(assembly.assembly_root(chain).location) == (12, 20, 30)
    assert len(chain.all_objects) == 2
    unstitched = import_map("stitch_off", "16 0 0", "stitch_old")
    assert tuple(assembly.assembly_root(unstitched).location) == (0, 0, 0)

    duplicate = import_map("stitch_old", "64 0 0", import_entities=False)
    ambiguous = import_map("stitch_ambiguous", "16 0 0", "stitch_old", stitch_goldsrc=True)
    assert tuple(assembly.assembly_root(ambiguous).location) == (0, 0, 0)
    assert "qb_stitch_offset" not in ambiguous
    selected = import_map("stitch_selected", "16 0 0", "stitch_old", stitch_goldsrc=True,
                          stitch_target=target["qb_import_id"])
    assert tuple(assembly.assembly_root(selected).location) == (11.5, 20, 30)
    assert tuple(assembly.assembly_root(duplicate).location) == (0, 0, 0)

    operator.stitch_target = target["qb_import_id"]
    target_root.rotation_euler.z = 0.5
    assert not assembly.stitch_import(operator, bpy.context, selected)
    assert tuple(assembly.assembly_root(selected).location) == (11.5, 20, 30)
    target_root.rotation_euler.z = 0
    target_root.scale = (2, 2, 2)
    assert not assembly.stitch_import(operator, bpy.context, selected)
    target_root.scale = (1, 1, 1)
    incompatible = import_map("stitch_scale", "16 0 0", "stitch_old", stitch_goldsrc=True,
                              stitch_target=target["qb_import_id"], scale=0.25)
    assert tuple(assembly.assembly_root(incompatible).location) == (0, 0, 0)

    categories = ("objects", "collections", "meshes", "materials", "images", "lights", "cameras")
    before = {category: {item.as_pointer() for item in getattr(bpy.data, category)} for category in categories}
    original_stitch = assembly.stitch_import

    def fail_after_placement(*args):
        assert original_stitch(*args)
        raise RuntimeError("intentional stitching rollback")

    assembly.stitch_import = fail_after_placement
    try:
        try:
            import_map("stitch_failure", "16 0 0", "stitch_old", stitch_goldsrc=True,
                       stitch_target=target["qb_import_id"])
        except RuntimeError as exc:
            assert "intentional stitching rollback" in str(exc)
        else:
            raise AssertionError("stitching failure did not cancel the import")
    finally:
        assembly.stitch_import = original_stitch
    assert before == {category: {item.as_pointer() for item in getattr(bpy.data, category)}
                      for category in categories}
    assert tuple(target_root.location) == (10, 20, 30)


def _check_map_transform_export(extension_root: str, directory: Path) -> None:
    parser = importlib.import_module(f"{extension_root}.formats.map_q1")
    csg = importlib.import_module(f"{extension_root}.formats.csg")
    writer = importlib.import_module(f"{extension_root}.formats.map_writer")
    geometry = importlib.import_module(f"{extension_root}.blender.builder_geometry")
    scene_export = importlib.import_module(f"{extension_root}.blender.map_scene_export")
    for game, fixture in (("Q1", _Q1_MAP), ("Q2", _Q2_MAP)):
        path = directory / f"transform_{game}.map"
        path.write_text(fixture, encoding="ascii")
        assert bpy.ops.quakeblend.import_map(filepath=str(path), source_game=game,
                                             wad_paths=";", scale=0.125) == {"FINISHED"}
        root = _source_roots(path)[0]
        brush = next(obj for obj in root.all_objects if obj.type == "MESH")
        for obj in bpy.context.selected_objects:
            obj.select_set(False)
        brush.select_set(True)
        bpy.context.view_layer.objects.active = brush
        source = parser.parse_path(path)
        entity_index = brush["qb_owner_entity_index"]
        brush_index = brush["qb_brush_index"]
        original = source.entities[entity_index].brushes[brush_index]
        assert sorted(item.value for item in brush.data.attributes["qb_source_face"].data) == list(range(len(original.faces)))
        parent = bpy.data.objects.new("Transform test parent", None)
        root.objects.link(parent)
        parent.location = (1, 2, 3)
        brush.parent = parent
        brush.location = (2, -1, 0.5)
        brush.rotation_euler.z = math.radians(37)
        brush.scale = (2, 0.5, 1.5)
        destination = directory / f"transformed_{game}.map"

        def export(**options):
            return bpy.ops.quakeblend.export_map(filepath=str(destination), target_game=game,
                                                 projection="VALVE220", **options)

        assert export(use_brush_transforms=True) == {"FINISHED"}
        restored = parser.parse_path(destination).entities[entity_index].brushes[brush_index]
        rings = csg.brush_faces_from_planes([face.plane for face in restored.faces])
        ids = [item.value for item in brush.data.attributes["qb_source_face"].data]
        for polygon, face_id in zip(brush.data.polygons, ids):
            for loop_index in polygon.loop_indices:
                loop = brush.data.loops[loop_index]
                expected = brush.matrix_world @ brush.data.vertices[loop.vertex_index].co / 0.125
                assert min((Vector(tuple(vertex)) - expected).length for vertex in rings[face_id]) < 1e-3
                dimensions = (brush.data.attributes["qb_texture_width"].data[polygon.index].value,
                              brush.data.attributes["qb_texture_height"].data[polygon.index].value)
                point = next(vertex for vertex in rings[face_id] if (Vector(tuple(vertex)) - expected).length < 1e-3)
                projected = geometry._project_uv(restored.faces[face_id].tex, point, dimensions)
                uv = brush.data.uv_layers.active.data[loop_index].uv
                assert abs(projected[0] - uv.x) * dimensions[0] < 0.001
                assert abs(1 - projected[1] - uv.y) * dimensions[1] < 0.001
        if game == "Q2":
            assert [(face.tex.contents, face.tex.surface_flags, face.tex.value) for face in restored.faces] == [
                (face.tex.contents, face.tex.surface_flags, face.tex.value) for face in original.faces]
        anchor = next((obj for obj in root.all_objects if obj.get("qb_entity_has_origin")), None)
        if game == "Q1":
            assert anchor is not None
        if anchor is not None:
            saved_location = anchor.location.copy()
            anchor.location.x += 1
            assert export(use_brush_transforms=True, use_scene_entity_edits=True) == {"FINISHED"}
            overlay = parser.parse_path(destination)
            actual_origin = Vector(tuple(float(value) for value in overlay.entities[anchor["qb_entity_index"]].properties["origin"].split()))
            assert (actual_origin - anchor.location / 0.125).length < 1e-4
            assert overlay.entities[entity_index].brushes[brush_index] == restored
            anchor.location = saved_location
        assert export(use_brush_transforms=False) == {"FINISHED"}
        replayed = parser.parse_path(destination)
        assert writer.serialize(replayed, dialect=game.lower(), projection="valve220") == writer.serialize(
            source, dialect=game.lower(), projection="valve220")

        def rejected():
            destination.write_bytes(b"existing destination must survive")
            try:
                result = export(use_brush_transforms=True)
            except RuntimeError:
                result = {"CANCELLED"}
            assert result == {"CANCELLED"}
            assert destination.read_bytes() == b"existing destination must survive"

        vertex = brush.data.vertices[0]
        original_position = vertex.co.copy()
        vertex.co.x += 1
        rejected()
        brush.data.vertices[0].co = original_position
        baseline = root["qb_transform_baselines"][f"{entity_index}:{brush_index}"]
        assert scene_export.mesh_signature(brush) == baseline, "vertex restore failed"
        uv = brush.data.uv_layers.active.data[0]
        original_uv = uv.uv.copy()
        uv.uv.x += 0.1
        rejected()
        brush.data.uv_layers.active.data[0].uv = original_uv
        assert scene_export.mesh_signature(brush) == baseline, "UV restore failed"
        original_material = brush.data.materials[0]
        replacement_material = bpy.data.materials.new("Rejected material replacement")
        brush.data.materials[0] = replacement_material
        rejected()
        brush.data.materials[0] = original_material
        bpy.data.materials.remove(replacement_material)
        owners = list(brush.users_collection)
        for owner in owners:
            owner.objects.unlink(brush)
        bpy.context.view_layer.objects.active = parent
        rejected()
        for owner in owners:
            owner.objects.link(brush)
        bpy.context.view_layer.objects.active = brush
        duplicate = brush.copy()
        root.objects.link(duplicate)
        rejected()
        bpy.data.objects.remove(duplicate, do_unlink=True)
        modifier = brush.modifiers.new("Unsupported bevel", "BEVEL")
        rejected()
        brush.modifiers.remove(modifier)
        brush.scale.x = -2
        rejected()
        brush.scale.x = 0
        rejected()
        brush.scale.x = 2
        parent.scale = (2, 1, 1)
        rejected()
        parent.scale = (1, 1, 1)
        face_id = brush.data.attributes["qb_source_face"].data[0]
        saved_id = face_id.value
        face_id.value = 99
        rejected()
        brush.data.attributes["qb_source_face"].data[0].value = saved_id
        saved_scale = root["qb_import_scale"]
        root["qb_import_scale"] = 1
        rejected()
        root["qb_import_scale"] = saved_scale
        path.write_text(fixture + "\n", encoding="ascii")
        rejected()
        path.write_text(fixture, encoding="ascii")
        brush.location.x = 125000
        rejected()
        brush.location.x = 2
        assert export(use_brush_transforms=True) == {"FINISHED"}


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
        _check_import_failure_rollback(args.extension_root, directory)
        _check_texture_case_and_face_flags(directory)
        _check_bsp_and_wad_workflows(directory)
        _check_wad3_palettes(directory)
        _check_cameras(args.extension_root, directory)
        _check_bsp_submodels(directory)
        _check_bsp_import_controls(directory)
        _check_goldsrc(directory)
        _check_goldsrc_stitching(args.extension_root, directory)
        _check_map_transform_export(args.extension_root, directory)
    _check_unregister(args.extension_root)
    print(
        "QUAKEBLEND_SMOKE_OK registration materials transaction "
        "map rollback textures bsp submodels wad export unregister"
    )


if __name__ == "__main__":
    main()
