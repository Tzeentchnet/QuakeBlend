"""Validate installed GoldSrc imports and stitching using compiler-produced BSPs."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import os
import sys
from array import array
from pathlib import Path
from types import SimpleNamespace

import bpy
from mathutils import Vector


def _vector(values):
    return tuple(round(float(value), 6) for value in values)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()


def snapshot(roots):
    objects = {}
    materials = {}
    images = {}
    collections = {}
    for root in roots:
        collections[root.name] = {
            key: (list(root[key]) if key == "qb_stitch_offset" else root[key])
            for key in ("qb_import_id", "qb_source_bsp", "qb_bsp_entities", "qb_stitch_targets", "qb_stitch_offset")
            if key in root
        }
        for obj in root.all_objects:
            record = {"type": obj.type, "parent": obj.parent.name if obj.parent else None,
                      "matrix": [list(row) for row in obj.matrix_world],
                      "hidden": obj.hide_get(), "hide_render": obj.hide_render}
            if obj.type == "MESH":
                mesh = obj.data
                record["mesh"] = _digest({
                    "vertices": [list(vertex.co) for vertex in mesh.vertices],
                    "polygons": [(list(poly.vertices), poly.material_index) for poly in mesh.polygons],
                    "uv": [list(loop.uv) for loop in mesh.uv_layers.active.data],
                    "materials": [material["qb_asset_key"] for material in mesh.materials],
                })
                for material in mesh.materials:
                    bsdf = next(node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
                    materials[material.name] = {
                        "key": material["qb_asset_key"], "alpha_linked": bsdf.inputs["Alpha"].is_linked,
                        "emission": list(bsdf.inputs["Emission Color"].default_value),
                        "emission_strength": bsdf.inputs["Emission Strength"].default_value,
                        "emission_linked": bsdf.inputs["Emission Color"].is_linked,
                        "links": sorted((link.from_node.type, link.from_socket.name,
                                         link.to_node.type, link.to_socket.name) for link in material.node_tree.links),
                    }
                    for node in material.node_tree.nodes:
                        if node.type != "TEX_IMAGE":
                            continue
                        image = node.image
                        assert image is not None and image.packed_file is not None
                        values = array("f", [0]) * len(image.pixels)
                        image.pixels.foreach_get(values)
                        assert all(math.isfinite(value) for value in values)
                        images[image.name] = {"size": list(image.size), "key": image["qb_asset_key"],
                                              "pixels_sha256": hashlib.sha256(values.tobytes()).hexdigest()}
            elif obj.type == "LIGHT":
                record["light"] = [obj.data.type, obj.data.energy, list(obj.data.color)]
            elif obj.type == "CAMERA":
                record["camera"] = [obj.data.lens, obj.data.sensor_width]
            objects[obj.name] = record
    return json.loads(json.dumps({"collections": collections, "objects": objects,
                                  "materials": materials, "images": images}))


def check_material(material, texture):
    assert not material.get("qb_placeholder", False)
    images = [node.image for node in material.node_tree.nodes if node.type == "TEX_IMAGE"]
    assert len(images) == 1, "GoldSrc high palette indices must not create an emission mask"
    image = images[0]
    assert image is not None and tuple(image.size) == (64, 32) and image.packed_file is not None
    pixels = list(image.pixels)
    for row in range(32):
        for column in range(64):
            index = texture.pixels[(31 - row) * 64 + column]
            offset = (row * 64 + column) * 4
            alpha = 0.0 if texture.name.startswith("{") and index == 255 else 1.0
            assert abs(pixels[offset + 3] - alpha) < 1e-6
            if alpha:
                expected = [component / 255 for component in texture.palette[index * 3:index * 3 + 3]]
                assert max(abs(left - right) for left, right in zip(pixels[offset:offset + 3], expected)) < 1e-6
    bsdf = next(node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
    assert bsdf.inputs["Alpha"].is_linked == texture.name.startswith("{")
    assert not bsdf.inputs["Emission Color"].is_linked
    assert not bsdf.inputs["Emission Strength"].is_linked
    assert all(component * bsdf.inputs["Emission Strength"].default_value == 0
               for component in bsdf.inputs["Emission Color"].default_value[:3])


def check_import(root, bsp, bindings, assembly, offset):
    assembly_obj = assembly.assembly_root(root)
    assert _vector(assembly_obj.location) == offset
    assert "qb_source_map" not in root and root["qb_source_game"] == "goldsrc"
    meshes = [obj for obj in root.all_objects if obj.type == "MESH"]
    assert sorted(obj["qb_bsp_model_index"] for obj in meshes) == [0, 1, 2]
    owners = {int(entity["model"][1:]): entity for entity in bsp.entities if entity.get("model", "").startswith("*")}
    for obj in root.all_objects:
        if obj != assembly_obj:
            assert obj.parent == assembly_obj
            assert (obj.matrix_world.translation - obj.location - assembly_obj.location).length < 1e-6
    for obj in meshes:
        model_index = obj["qb_bsp_model_index"]
        model = bsp.models[model_index]
        owner = owners.get(model_index, {})
        origin = Vector(tuple(float(value) for value in owner.get("origin", "0 0 0").split()))
        assert _vector(obj.location) == _vector(origin / 32)
        expected_faces = []
        for face in bsp.faces[model.first_face:model.first_face + model.face_count]:
            texinfo = bsp.texinfos[face.texinfo_id]
            texture = bsp.miptextures[texinfo.miptex_index]
            corners = []
            for index in bsp.face_polygon(face):
                point = bsp.vertices[index]
                position = (Vector(tuple(point)) + origin) / 32 + Vector(offset)
                uv = ((point.dot(texinfo.s_axis) + texinfo.s_offset) / 64,
                      1 - (point.dot(texinfo.t_axis) + texinfo.t_offset) / 32)
                corners.append((_vector(position), _vector(uv)))
            expected_faces.append((texture.name, sorted(corners)))
        actual_faces = []
        for polygon in obj.data.polygons:
            material = obj.data.materials[polygon.material_index]
            texture = bindings[material["qb_asset_key"]]
            corners = []
            for loop_index in polygon.loop_indices:
                vertex = obj.data.vertices[obj.data.loops[loop_index].vertex_index]
                corners.append((_vector(obj.matrix_world @ vertex.co),
                                _vector(obj.data.uv_layers.active.data[loop_index].uv)))
            actual_faces.append((texture.name, sorted(corners)))
        assert sorted(actual_faces) == sorted(expected_faces), (root.name, model_index)
        for material in obj.data.materials:
            check_material(material, bindings[material["qb_asset_key"]])
        assert obj.hide_get() == (model_index == 2)
        assert not obj.hide_render
    door, = [obj for obj in meshes if obj.get("qb_prop_classname") == "func_door"]
    assert _vector(door.location) == (2, 0, -0.5)
    positions = [door.matrix_world @ vertex.co - Vector(offset) for vertex in door.data.vertices]
    assert _vector(min(point[axis] for point in positions) * 32 for axis in range(3)) == (56, -24, -48)
    assert _vector(max(point[axis] for point in positions) * 32 for axis in range(3)) == (72, 24, 16)
    light, = [obj for obj in root.all_objects if obj.type == "LIGHT"]
    assert abs(light.data.energy - 200 * 4 * math.pi / 32 ** 2) < 1e-5
    assert max(abs(left - right) for left, right in zip(light.data.color, (1, 128 / 255, 0))) < 1e-6
    assert _vector(light.matrix_world.translation) == _vector(Vector(offset) + Vector((0, 0, 3)))
    camera, = [obj for obj in root.all_objects if obj.type == "CAMERA"]
    assert _vector(camera.matrix_world.translation) == _vector(Vector(offset) + Vector((2, 2, -2.5)))
    assert (camera.rotation_euler.to_matrix() @ Vector((0, 0, -1)) - Vector((0, 1, 0))).length < 1e-6


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--variant", choices=("embedded", "external"), default="embedded")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--reopen", type=Path)
    parser.add_argument("--extension-root", default="bl_ext.user_default.quakeblend")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    if not __debug__:
        raise RuntimeError("Do not run validation with Python optimization")
    assert bpy.app.background and not bpy.data.filepath
    config = os.environ.get("BLENDER_USER_CONFIG")
    assert config and Path(config).is_dir()
    assert Path(bpy.utils.user_resource("CONFIG")).resolve() == Path(config).resolve()
    bpy.context.preferences.use_preferences_save = False
    if args.reopen:
        assert args.extension_root not in bpy.context.preferences.addons
        report = json.loads((args.reopen.parent / "report.json").read_text(encoding="utf-8"))
        before = hashlib.sha256(args.reopen.read_bytes()).hexdigest()
        assert bpy.ops.wm.open_mainfile(filepath=str(args.reopen)) == {"FINISHED"}
        bpy.context.view_layer.update()
        roots = [root for root in bpy.data.collections if root.get("qb_source_game") == "goldsrc"]
        assert len(roots) == 2 and snapshot(roots) == report["snapshot"]
        assert hashlib.sha256(args.reopen.read_bytes()).hexdigest() == before
        print("QUAKEBLEND_GOLDSRC_REOPEN_OK standalone geometry materials packed pixels visibility")
        return
    assert args.output_dir is not None
    args.output_dir.mkdir(parents=True, exist_ok=False)
    directory = args.directory.resolve()
    compiler_report = json.loads((directory / "compiler-report.json").read_text(encoding="utf-8"))
    assert compiler_report["input_sha256"]["fixture.wad"] == hashlib.sha256((directory / "fixture.wad").read_bytes()).hexdigest()
    assert bpy.ops.preferences.addon_enable(module=args.extension_root) == {"FINISHED"}
    bsp_module = importlib.import_module(f"{args.extension_root}.formats.bsp_goldsrc")
    wad_module = importlib.import_module(f"{args.extension_root}.formats.wad")
    paths_module = importlib.import_module(f"{args.extension_root}.utils.paths")
    assembly = importlib.import_module(f"{args.extension_root}.blender.map_assembly")
    textures = {texture.name: texture for texture in wad_module.read_wad_path(directory / "fixture.wad").textures}
    loaded = {}
    for name in ("qb_gold_a", "qb_gold_b"):
        path = directory / args.variant / f"{name}.bsp"
        expected_hash = compiler_report["cases"][f"{args.variant}/{name}"]["sha256"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected_hash
        loaded[name] = bsp_module.read_path(path)

    def import_level(name, **options):
        path = directory / args.variant / f"{name}.bsp"
        before = set(bpy.data.collections)
        assert bpy.ops.quakeblend.import_bsp(
            filepath=str(path), wad_paths=str(directory / "fixture.wad") if args.variant == "external" else ";",
            texture_root=str(directory / "no-image-fallback"), scale=1 / 32, trigger_handling="HIDDEN",
            **options,
        ) == {"FINISHED"}
        root, = [item for item in bpy.data.collections if item not in before and item.get("qb_source_bsp")]
        return root

    def bindings(name):
        result = {}
        for index, reference in enumerate(loaded[name].miptextures):
            if reference is None:
                continue
            source = directory / "fixture.wad" if args.variant == "external" else directory / args.variant / f"{name}.bsp"
            namespace = "goldsrc-wad" if args.variant == "external" else "goldsrc-bsp"
            key = paths_module.file_asset_key(source, namespace=namespace, member=reference.name)
            if args.variant == "embedded":
                key += f"|{index}"
            result[f"{key}|material"] = textures[reference.name]
        return result

    first = import_level("qb_gold_a", stitch_goldsrc=False)
    assembly.assembly_root(first).location = (10, 20, 30)
    first.name = "Renamed GoldSrc Target"
    bpy.context.view_layer.update()
    check_import(first, loaded["qb_gold_a"], bindings("qb_gold_a"), assembly, (10, 20, 30))
    original = snapshot([first])
    second = import_level("qb_gold_b", stitch_goldsrc=True)
    bpy.context.view_layer.update()
    assert snapshot([first]) == original
    check_import(second, loaded["qb_gold_b"], bindings("qb_gold_b"), assembly, (16, 20, 30))
    assert second["qb_stitch_targets"] == first["qb_import_id"]
    landmarks = [next(obj for obj in root.all_objects if obj.get("qb_prop_classname") == "info_landmark")
                 for root in (first, second)]
    assert (landmarks[0].matrix_world.translation - landmarks[1].matrix_world.translation).length < 1e-6
    before_stitch = snapshot([first, second])
    messages = []
    operator = SimpleNamespace(stitch_target="AUTO", report=lambda levels, text: messages.append(text))
    assert assembly.stitch_import(operator, bpy.context, second)
    assert snapshot([first, second]) == before_stitch
    for obj in list(bpy.context.scene.objects):
        if obj not in set(first.all_objects) | set(second.all_objects):
            bpy.data.objects.remove(obj, do_unlink=True)
    blend = args.output_dir / "connected.blend"
    assert bpy.ops.wm.save_as_mainfile(filepath=str(blend)) == {"FINISHED"}
    report = {"blender_version": bpy.app.version_string, "variant": args.variant,
              "root_offsets": [[10, 20, 30], [16, 20, 30]], "snapshot": before_stitch}
    bpy.context.window.scene = bpy.data.scenes.new("GoldSrc Minimal Import Check")
    counts = (len(bpy.data.materials), len(bpy.data.images))
    bare_first = import_level("qb_gold_a", import_entities=False, import_brush_entities=False,
                               create_materials=False, stitch_goldsrc=False)
    bare_second = import_level("qb_gold_b", import_entities=False, import_brush_entities=False,
                                create_materials=False, stitch_goldsrc=True)
    assert _vector(assembly.assembly_root(bare_first).location) == (0, 0, 0)
    assert _vector(assembly.assembly_root(bare_second).location) == (6, 0, 0)
    assert len(bare_first.all_objects) == len(bare_second.all_objects) == 2
    assert counts == (len(bpy.data.materials), len(bpy.data.images))
    assert bare_second["qb_stitch_targets"] == bare_first["qb_import_id"]
    report["minimal_import_stitching"] = True
    for name in loaded:
        path = directory / args.variant / f"{name}.bsp"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == compiler_report["cases"][f"{args.variant}/{name}"]["sha256"]
    with (args.output_dir / "report.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print("QUAKEBLEND_GOLDSRC_BLENDER_OK textures alpha no-fullbright origins UVs stitching options")
    print(blend)


if __name__ == "__main__":
    main()
