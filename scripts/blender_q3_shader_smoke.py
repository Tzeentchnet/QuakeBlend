"""Synthetic installed-extension acceptance checks for non-sky Q3 shaders."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

import bpy


def check_lighting(builders, assets, output_dir):
    shader_path = assets / "scripts/lighting.shader"
    shader_path.write_text("\n".join(
        f"lighting/{kind} {{\n{{\nmap $whiteimage\nrgbGen {kind}\n}}\n"
        "{\nmap $lightmap\nblendFunc filter\n}\n}"
        for kind in ("vertex", "exactvertex", "oneminusvertex")
    ) + "\nlighting/alpha { {\nmap $whiteimage\nalphaGen vertex\nalphaFunc GE128\n} }", encoding="ascii")
    scene = bpy.data.scenes.new("Lighting options")
    bpy.context.window.scene = scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 640
    scene.render.resolution_y = 160
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_depth = "32"
    scene.world = bpy.data.worlds.new("Lighting black world")
    scene.world.use_nodes = True
    scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0
    names = ["lighting/vertex", "lighting/exactvertex", "lighting/oneminusvertex",
             "textures/demo_trans", "textures/runtime.png", "lighting/alpha", "lighting/vertex", "lighting/vertex"]
    modes = ["FULLBRIGHT"] * 6 + ["BAKED", "RELIT"]
    libraries = {mode: builders.Q3Materials(assets, scene, lighting=mode,
        lightmaps=[bytes((32, 32, 32)) * (128 * 128)], source_key="lighting-probe") for mode in set(modes)}
    for index, (name, mode) in enumerate(zip(names, modes)):
        before = len(bpy.data.images)
        material = libraries[mode].get(name, 0)
        assert not material.get("qb_placeholder"), material.get("qb_q3_diagnostic")
        assert material["qb_q3_lighting"] == mode.lower()
        if index < 3:
            assert len(bpy.data.images) == before
        bpy.ops.mesh.primitive_plane_add(size=1.8, location=(-7 + index * 2, 0, 0))
        obj = bpy.context.object
        obj.data.materials.append(material)
        colors = obj.data.color_attributes.new(name="qb_q3_color", type="FLOAT_COLOR", domain="CORNER")
        for color in colors.data:
            color.color = (.1, .1, .1, 0 if name == "lighting/alpha" else 1)
        light_uv = obj.data.uv_layers.new(name="Q3Lightmap")
        for loop in light_uv.data:
            loop.uv = (.5, .5)
    bpy.ops.object.camera_add(location=(0, 0, 8))
    scene.camera = bpy.context.object
    scene.camera.data.type = "ORTHO"
    scene.camera.data.ortho_scale = 16
    samples = []
    for illuminated in (False, True):
        if illuminated:
            bpy.ops.object.light_add(type="SUN")
            bpy.context.object.data.energy = 2
        path = output_dir / f"lighting-{illuminated}.exr"
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        image = bpy.data.images.load(str(path))
        pixels = list(image.pixels)
        samples.append([pixels[(80 * 640 + 40 + index * 80) * 4:(80 * 640 + 40 + index * 80) * 4 + 3] for index in range(8)])
    for index in range(3):
        assert max(abs(value - 1) for value in samples[0][index]) < .01, samples
    assert sum(samples[0][3]) > .05 and sum(samples[0][4]) > .05
    assert max(samples[0][5]) < .01, samples
    assert max(samples[0][6]) < .05 and max(samples[0][7]) < .01, samples
    for index in range(7):
        assert max(abs(left - right) for left, right in zip(samples[0][index], samples[1][index])) < .01, samples
    assert min(samples[1][7]) > .1, samples
    for mode in ("FULLBRIGHT", "RELIT"):
        assert libraries[mode].lightmap(0) is None
    print("Q3_LIGHTING_OPTIONS_OK fullbright baked relit vertex-alpha isolation")


def check_effect_options(builders, assets, output_dir):
    (assets / "scripts/effect-options.shader").write_text("""effects/options {
deformVertexes wave 100 sin 0 2 0 1
{
animMap 10 textures/red.png textures/green.png
tcMod scale 2 3
tcMod scroll .25 .5
}
}
""", encoding="ascii")
    scene = bpy.data.scenes.new("Effect options")
    bpy.context.window.scene = scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 320
    scene.render.resolution_y = 80
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_depth = "32"
    objects = []
    for animate in (False, True):
        for deform in (False, True):
            library = builders.Q3Materials(assets, scene, lighting="FULLBRIGHT",
                animate_shaders=animate, deform_geometry=deform)
            material = library.get("effects/options")
            assert not material.get("qb_placeholder"), material.get("qb_q3_diagnostic")
            bpy.ops.mesh.primitive_plane_add(size=1.8, location=(-3 + len(objects) * 2, 0, 0))
            obj = bpy.context.object
            objects.append(obj)
            obj.data.materials.append(material)
            source_positions = [tuple(vertex.co) for vertex in obj.data.vertices]
            library.apply(obj)
            shader = library.effects[material.name]
            attribute_name = builders.uv_attribute(shader, 0)
            snapshots = []
            for frame in (1, 4):
                scene.frame_set(frame)
                evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
                mesh = evaluated.to_mesh()
                snapshots.append(([tuple(vertex.co) for vertex in mesh.vertices],
                    [tuple(item.vector) for item in mesh.attributes[attribute_name].data]))
                evaluated.to_mesh_clear()
            assert (snapshots[0][0] != snapshots[1][0]) == deform
            assert (snapshots[0][1] != snapshots[1][1]) == animate
            assert max(value[0] for value in snapshots[0][1]) == 2
            assert min(value[1] for value in snapshots[0][1]) == -2
            assert [tuple(vertex.co) for vertex in obj.data.vertices] == source_positions
            if not deform:
                assert len(snapshots[0][0]) == len(source_positions)
            if not animate:
                assert not material.node_tree.animation_data
            if not animate and not deform:
                assert not obj.modifiers[0].node_group.animation_data
    bpy.ops.object.camera_add(location=(0, 0, 8))
    scene.camera = bpy.context.object
    scene.camera.data.type = "ORTHO"
    scene.camera.data.ortho_scale = 8
    for frame in (1, 4):
        scene.frame_set(frame)
        path = output_dir / f"effect-options-{frame}.exr"
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        image = bpy.data.images.load(str(path))
        pixels = list(image.pixels)
        colors = [pixels[(40 * 320 + 40 + index * 80) * 4:(40 * 320 + 40 + index * 80) * 4 + 3]
                  for index in range(4)]
        for index, color in enumerate(colors):
            expected = (0, 1, 0) if frame == 4 and index >= 2 else (1, 0, 0)
            assert max(abs(value - reference) for value, reference in zip(color, expected)) < .01, colors
    print("Q3_EFFECT_OPTIONS_OK animation deformation static-UV source-mesh")


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
    builders = importlib.import_module(f"{args.extension_root}.blender.builder_q3_materials")
    materials = importlib.import_module(f"{args.extension_root}.blender.builder_materials")
    transaction = importlib.import_module(f"{args.extension_root}.blender.transaction")
    assets = args.output_dir / "assets"
    (assets / "scripts").mkdir(parents=True)
    (assets / "textures").mkdir()
    for name, size, color in [("editor", (64, 32), (255, 255, 255, 255)),
                              ("runtime", (8, 8), (128, 64, 32, 0)),
                              ("red", (8, 8), (255, 0, 0, 255)),
                              ("green", (8, 8), (0, 255, 0, 255))]:
        image = materials.create_image(name, *size, bytes(color) * (size[0] * size[1]))
        image.filepath_raw = str(assets / "textures" / f"{name}.png")
        image.file_format = "PNG"
        image.save()
    shader_text = '''textures/demo_trans {
qer_editorimage textures/editor.png
{ map $lightmap }
{
map textures/runtime.png
blendFunc filter
}
}
textures/animation {
{
animMap 10 textures/red.png textures/green.png
}
}
'''
    cases = [
        ("opaque", "", "", (.2, .1, .05)),
        ("additive", "blendFunc add", "", (.3, .3, .35)),
        ("multiply", "", "{\nmap $whiteimage\nrgbGen const ( .5 .5 .5 )\nblendFunc filter\n}", (.1, .05, .025)),
        ("layer_alpha", "", "{\nmap $whiteimage\nrgbGen const ( .4 .2 .1 )\nalphaGen const .25\nblendFunc blend\n}", (.25, .125, .0625)),
        ("water", "blendFunc blend\nalphaGen const .25", "", (.125, .175, .2375)),
        ("cutout", "alphaGen const 0\nalphaFunc GE128", "", (.1, .2, .3)),
    ]
    for name, first, second, _ in cases:
        shader_text += f"textures/{name} {{\n{{\nmap $WHITEIMAGE\nrgbGen const ( .2 .1 .05 )\n{first}\n}}\n{second}\n}}\n"
    (assets / "scripts/smoke.shader").write_text(shader_text, encoding="ascii")
    map_path = args.output_dir / "shader-smoke.map"
    map_path.write_text(smoke._Q1_MAP.replace("SMOKE", "textures/demo_trans") +
                        smoke._Q3_PATCH_MAP.replace("textures/smoke/patch", "textures/demo_trans"), encoding="ascii")
    assert bpy.ops.quakeblend.import_map(filepath=str(map_path), source_game="Q3", texture_root=str(assets),
        wad_paths=";", import_entities=False) == {"FINISHED"}
    root = bpy.data.collections["shader-smoke"]
    for obj in root.all_objects:
        if obj.type != "MESH":
            continue
        material = obj.data.materials[0]
        assert material["qb_q3_lighting"] == "relit"
        assert list(material["qb_q3_projection_size"]) == [64, 32]
        assert not material.get("qb_placeholder")
        if "qb_patch_control_grid" not in obj:
            assert {item.value for item in obj.data.attributes["qb_texture_width"].data} == {64}
            assert {item.value for item in obj.data.attributes["qb_texture_height"].data} == {32}
    world = bpy.context.scene.world
    before = {name: {item.as_pointer() for item in getattr(bpy.data, name)} for name in transaction._DATA_COLLECTIONS}
    try:
        with transaction.ImportTransaction():
            bpy.data.node_groups.new("Rollback Q3 group", "GeometryNodeTree")
            bpy.data.actions.new("Rollback Q3 action")
            raise RuntimeError("rollback probe")
    except RuntimeError:
        pass
    assert before == {name: {item.as_pointer() for item in getattr(bpy.data, name)} for name in transaction._DATA_COLLECTIONS}
    assert bpy.context.scene.world == world
    geometry = importlib.import_module(f"{args.extension_root}.blender.builder_geometry")
    common = importlib.import_module(f"{args.extension_root}.formats.common")
    duplicate = geometry.build_bsp_geometry("Channel association", [common.Vec3(0, 0, 0),
        common.Vec3(0, 1, 0), common.Vec3(1, 0, 0), common.Vec3(1, 1, 0)],
        [[0, 1, 2], [0, 1, 2], [1, 3, 2]], [0, 0, 0], [[(0, 0)] * 3] * 3,
        bpy.context.scene.collection, [], scale=1,
        corner_channels=[[(.1, .2, 1, 0, 0, 1, 0, 0, 1)] * 3,
                         [(.3, .4, 0, 1, 0, 1, 0, 0, 1)] * 3,
                         [(.5, .6, 0, 0, 1, 1, 0, 0, 1)] * 3],
        source_faces=[7, 8, 9], shader_indices=[2, 3, 4])
    assert [item.value for item in duplicate.data.attributes["qb_q3_source_face"].data] == [7, 9]
    assert [item.value for item in duplicate.data.attributes["qb_q3_shader_index"].data] == [2, 4]
    assert all(polygon.normal.z > .99 for polygon in duplicate.data.polygons)
    assert duplicate.data.uv_layers["Q3Lightmap"].data[-1].uv.x == .5
    bpy.data.objects.remove(duplicate, do_unlink=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output_dir / "q3-map-shader-smoke.blend"))
    scene = bpy.data.scenes.new("Q3 synthetic blending")
    bpy.context.window.scene = scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 640
    scene.render.resolution_y = 160
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_depth = "32"
    library = builders.Q3Materials(assets, scene, baked=True)
    background = bpy.data.materials.new("Q3 synthetic background")
    background.use_nodes = True
    background.node_tree.nodes.clear()
    nodes = builders.Nodes(background.node_tree)
    emission = nodes.node("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (.1, .2, .3, 1)
    output = nodes.node("ShaderNodeOutputMaterial")
    nodes.put(output.inputs["Surface"], emission.outputs[0])
    for index, (name, _, _, _) in enumerate(cases):
        for height, material in ((0, background), (.1, library.get(f"textures/{name}"))):
            assert not material.get("qb_placeholder"), material.get("qb_q3_diagnostic")
            bpy.ops.mesh.primitive_plane_add(size=1.8, location=(-5 + index * 2, 0, height))
            bpy.context.object.data.materials.append(material)
    for index, name in enumerate(("textures/demo_trans", "textures/animation"), start=6):
        bpy.ops.mesh.primitive_plane_add(size=1.8, location=(-5 + index * 2, 0, .1))
        bpy.context.object.data.materials.append(library.get(name))
    bpy.ops.object.camera_add(location=(2, 0, 6))
    scene.camera = bpy.context.object
    scene.camera.data.type = "ORTHO"
    scene.camera.data.ortho_scale = 16
    measurements = []
    for frame in (1, 4):
        scene.frame_set(frame)
        path = args.output_dir / f"blend-{frame}.exr"
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        image = bpy.data.images.load(str(path))
        pixels = list(image.pixels)
        colors = [pixels[(80 * 640 + 40 + index * 80) * 4:(80 * 640 + 40 + index * 80) * 4 + 3] for index in range(8)]
        measurements.append(colors)
        for (name, _, _, expected), actual in zip(cases, colors):
            assert max(abs(value - reference) for value, reference in zip(actual, expected)) < .01, (name, actual, expected)
        assert sum(colors[6]) > .05, "Zero-alpha opaque image disappeared"
    assert measurements[0][7][0] > .9 and measurements[1][7][1] > .9, measurements
    assert library.get("textures/demo_trans", 0) is not library.get("textures/demo_trans", 1)
    assert library.get("textures/demo_trans", 0) is library.get("textures/demo_trans", 0)
    (args.output_dir / "report.json").write_text(json.dumps(measurements, indent=2), encoding="utf-8")
    check_lighting(builders, assets, args.output_dir)
    check_effect_options(builders, assets, args.output_dir)
    print("Q3_SHADER_SMOKE_OK MAP dimensions blends alpha animation isolation rollback")


if __name__ == "__main__":
    main()
