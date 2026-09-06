"""Render standalone GoldSrc material probes from compiler-backed scenes."""

from __future__ import annotations

import argparse
from array import array
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import sys

import bpy


WIDTH = 512
HEIGHT = 256


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _material(texture_name: str, expected_count: int):
    matches = []
    for material in bpy.data.materials:
        key = material.get("qb_asset_key", "")
        parts = key.split("|")
        texture_parts = parts[-3:-1]
        if parts[-1:] == ["material"] and texture_name in texture_parts:
            matches.append(material)
    assert len(matches) == expected_count, (texture_name, [item.name for item in matches])
    return sorted(matches, key=lambda item: item.name)[0]


def _image_digest(material) -> str:
    nodes = [node for node in material.node_tree.nodes if node.type == "TEX_IMAGE"]
    assert len(nodes) == 1 and nodes[0].image is not None
    image = nodes[0].image
    values = array("f", [0]) * len(image.pixels)
    image.pixels.foreach_get(values)
    assert all(math.isfinite(value) for value in values)
    return hashlib.sha256(values.tobytes()).hexdigest()


def _emission_material():
    material = bpy.data.materials.new("GoldSrc probe backdrop")
    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (0.05, 0.8, 0.1, 1.0)
    emission.inputs["Strength"].default_value = 1.0
    material.node_tree.links.new(emission.outputs["Emission"], output.inputs["Surface"])
    return material


def _add_plane(scene, name: str, location, size: float, material):
    bpy.ops.mesh.primitive_plane_add(size=size, location=location)
    plane = bpy.context.object
    plane.name = name
    plane.data.materials.append(material)
    assert plane.name in scene.objects and plane.data.uv_layers.active is not None
    return plane


def _configure_render(scene):
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = WIDTH
    scene.render.resolution_y = HEIGHT
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.color_mode = "RGBA"
    scene.view_settings.view_transform = "Standard"


def _build_probe(high_material, mask_material):
    scene = bpy.data.scenes.new("GoldSrc Visual Probe")
    bpy.context.window.scene = scene
    _configure_render(scene)
    scene.world = bpy.data.worlds.new("GoldSrc probe black world")
    scene.world.use_nodes = True
    scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.0

    _add_plane(scene, "Backdrop", (0, 0, -0.1), 20.0, _emission_material())
    _add_plane(scene, "High palette", (-2, 0, 0), 3.4, high_material)
    _add_plane(scene, "Masked", (2, 0, 0), 3.4, mask_material)

    bpy.ops.object.camera_add(location=(0, 0, 8))
    camera = bpy.context.object
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = 8.0
    scene.camera = camera

    bpy.ops.object.light_add(type="SUN", location=(0, 0, 4))
    sun = bpy.context.object
    sun.data.energy = 3.0
    bpy.context.view_layer.update()
    return scene, sun


def _render_room(roots, triggers, output_dir: Path, variant: str):
    scene = bpy.context.scene
    _configure_render(scene)
    scene.world = bpy.data.worlds.new(f"{variant} room black world")
    scene.world.use_nodes = True
    scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.0
    first = next(root for root in roots if Path(root["qb_source_bsp"]).stem == "qb_gold_a")
    camera = next(obj for obj in first.all_objects if obj.type == "CAMERA")
    scene.camera = camera
    for trigger in triggers:
        trigger.hide_render = True
    bpy.ops.object.light_add(type="POINT", location=camera.matrix_world.translation)
    inspection_light = bpy.context.object
    inspection_light.name = "GoldSrc visual inspection light"
    inspection_light.data.energy = 150.0
    inspection_light.data.shadow_soft_size = 0.25
    bpy.context.view_layer.update()
    pixels, record = _render(scene, output_dir, f"{variant}-room")
    rgb = [pixels[index] for index in range(len(pixels)) if index % 4 != 3]
    metrics = {
        "mean_rgb": statistics.fmean(rgb),
        "nonblack_fraction": sum(value > 0.02 for value in rgb) / len(rgb),
        "maximum": max(rgb),
    }
    assert metrics["mean_rgb"] > 0.02, metrics
    assert metrics["nonblack_fraction"] > 0.2, metrics
    assert metrics["maximum"] > 0.1, metrics
    return pixels, record, metrics


def _render(scene, output_dir: Path, name: str):
    exr_path = output_dir / f"{name}.exr"
    png_path = output_dir / f"{name}.png"
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_depth = "32"
    scene.render.filepath = str(exr_path)
    assert bpy.ops.render.render(write_still=True) == {"FINISHED"}
    image = bpy.data.images.load(str(exr_path), check_existing=False)
    try:
        assert tuple(image.size) == (WIDTH, HEIGHT)
        pixels = array("f", [0]) * len(image.pixels)
        image.pixels.foreach_get(pixels)
    finally:
        bpy.data.images.remove(image)
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_depth = "8"
    bpy.data.images["Render Result"].save_render(str(png_path), scene=scene)
    assert exr_path.is_file() and png_path.is_file()
    return pixels, {
        "exr": exr_path.name,
        "exr_sha256": _sha256(exr_path),
        "png": png_path.name,
        "png_sha256": _sha256(png_path),
        "pixels_sha256": hashlib.sha256(pixels.tobytes()).hexdigest(),
    }


def _region(pixels, x_min: int, x_max: int, y_min: int, y_max: int):
    return [
        tuple(pixels[(row * WIDTH + column) * 4:(row * WIDTH + column) * 4 + 3])
        for row in range(y_min, y_max)
        for column in range(x_min, x_max)
    ]


def _mean_rgb(values):
    return tuple(statistics.fmean(value[channel] for value in values) for channel in range(3))


def _metrics(lit, dark, repeated):
    high_lit = _region(lit, 40, 216, 40, 216)
    high_dark = _region(dark, 40, 216, 40, 216)
    mask_lit = _region(lit, 296, 472, 40, 216)
    backdrop = _mean_rgb(_region(lit, 248, 264, 104, 152))
    mask_deltas = [max(abs(left - right) for left, right in zip(value, backdrop))
                   for value in mask_lit]
    result = {
        "backdrop_rgb": list(backdrop),
        "high_lit_mean": statistics.fmean(component for value in high_lit for component in value),
        "high_dark_max": max(component for value in high_dark for component in value),
        "mask_backdrop_fraction": sum(delta < 0.02 for delta in mask_deltas) / len(mask_deltas),
        "mask_opaque_fraction": sum(delta > 0.08 for delta in mask_deltas) / len(mask_deltas),
        "repeat_max_error": max(abs(left - right) for left, right in zip(lit, repeated)),
    }
    assert result["high_lit_mean"] > 0.05, result
    assert result["high_dark_max"] < 0.01, result
    assert result["mask_backdrop_fraction"] > 0.35, result
    assert result["mask_opaque_fraction"] > 0.35, result
    assert result["repeat_max_error"] < 1e-6, result
    return result


def _load_and_render(path: Path, variant: str, output_dir: Path):
    source_hash = _sha256(path)
    assert bpy.ops.wm.open_mainfile(filepath=str(path)) == {"FINISHED"}
    assert "bl_ext.user_default.quakeblend" not in bpy.context.preferences.addons
    bpy.context.view_layer.update()
    roots = [root for root in bpy.data.collections if root.get("qb_source_game") == "goldsrc"]
    assert len(roots) == 2
    landmarks = [next(obj for obj in root.all_objects
                      if obj.get("qb_prop_classname") == "info_landmark") for root in roots]
    landmark_distance = (landmarks[0].matrix_world.translation
                         - landmarks[1].matrix_world.translation).length
    assert landmark_distance < 1e-6
    triggers = [obj for root in roots for obj in root.all_objects
                if obj.get("qb_prop_classname") == "trigger_changelevel"]
    assert len(triggers) == 2 and all(obj.hide_get() and not obj.hide_render for obj in triggers)

    material_count = 2 if variant == "embedded" else 1
    high_material = _material("qb_high", material_count)
    mask_material = _material("{qb_mask", material_count)
    high_digest = _image_digest(high_material)
    mask_digest = _image_digest(mask_material)
    room, room_record, room_metrics = _render_room(roots, triggers, output_dir, variant)
    scene, sun = _build_probe(high_material, mask_material)
    lit, lit_record = _render(scene, output_dir, f"{variant}-lit")
    repeated, repeat_record = _render(scene, output_dir, f"{variant}-lit-repeat")
    sun.data.energy = 0.0
    dark, dark_record = _render(scene, output_dir, f"{variant}-dark")
    metrics = _metrics(lit, dark, repeated)
    assert _sha256(path) == source_hash
    return {
        "variant": variant,
        "blend": str(path),
        "blend_sha256": source_hash,
        "roots": sorted(root.name for root in roots),
        "landmark_distance": landmark_distance,
        "trigger_count": len(triggers),
        "high_image_sha256": high_digest,
        "mask_image_sha256": mask_digest,
        "room_metrics": room_metrics,
        "metrics": metrics,
        "renders": {
            "room": room_record,
            "lit": lit_record,
            "lit_repeat": repeat_record,
            "dark": dark_record,
        },
    }, {"room": room, "lit": lit, "dark": dark}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--embedded", type=Path, required=True)
    parser.add_argument("--external", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    if not __debug__:
        raise RuntimeError("Do not run validation with Python optimization")
    assert bpy.app.background and not bpy.data.filepath
    resources = Path(os.environ["BLENDER_USER_RESOURCES"]).resolve()
    config = Path(os.environ["BLENDER_USER_CONFIG"]).resolve()
    assert resources.is_dir() and config.is_dir() and config.is_relative_to(resources)
    assert Path(bpy.utils.user_resource("CONFIG")).resolve() == config
    bpy.context.preferences.use_preferences_save = False
    assert "bl_ext.user_default.quakeblend" not in bpy.context.preferences.addons
    args.output_dir.mkdir(parents=True, exist_ok=False)

    reports = []
    rendered = {}
    for variant, path in (("embedded", args.embedded), ("external", args.external)):
        report, pixels = _load_and_render(path.resolve(), variant, args.output_dir)
        reports.append(report)
        rendered[variant] = pixels
    assert reports[0]["high_image_sha256"] == reports[1]["high_image_sha256"]
    assert reports[0]["mask_image_sha256"] == reports[1]["mask_image_sha256"]
    parity = {
        name: max(abs(left - right) for left, right in zip(
            rendered["embedded"][name], rendered["external"][name]
        ))
        for name in ("room", "lit", "dark")
    }
    assert parity["lit"] < 1e-6 and parity["dark"] < 1e-6, parity
    assert parity["room"] <= 1 / 255, parity
    output = {
        "blender_version": bpy.app.version_string,
        "resolution": [WIDTH, HEIGHT],
        "variants": reports,
        "parity_max_error": parity,
    }
    (args.output_dir / "report.json").write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf-8"
    )
    print("QUAKEBLEND_GOLDSRC_VISUAL_OK masked-alpha high-palette lighting parity determinism")


if __name__ == "__main__":
    main()
