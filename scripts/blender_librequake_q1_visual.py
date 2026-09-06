"""Render source-camera views from the qualified LibreQuake Q1 scene."""

from __future__ import annotations

import argparse
from array import array
import hashlib
import json
import math
import os
from pathlib import Path
import re
import statistics
import sys

import bpy


WIDTH = 640
HEIGHT = 360
EXPECTED_SOURCE_SHA256 = "a827f8a4f6e011d8c1b81c25b16e43b086bbdec97a82f8327057ae2dc0f3f2cf"
EXPECTED_CAMERA_ENTITIES = {866, 995, 996, 997, 998, 1299, 1300}
POSITIVE_CAMERA_ENTITIES = {866, 995, 996, 997, 998}
PRIMARY_CAMERA_ENTITY = 866


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _configure_render(scene) -> None:
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = WIDTH
    scene.render.resolution_y = HEIGHT
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.color_mode = "RGBA"
    scene.view_settings.view_transform = "Standard"
    scene.world = bpy.data.worlds.new("LibreQuake visual black world")
    scene.world.use_nodes = True
    scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.0


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
    assert all(math.isfinite(value) for value in pixels)
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


def _metrics(pixels) -> dict:
    colors = [tuple(pixels[index:index + 3]) for index in range(0, len(pixels), 4)]
    channels = [channel for color in colors for channel in color]
    luminance = [0.2126 * red + 0.7152 * green + 0.0722 * blue
                 for red, green, blue in colors]
    magenta_like = [red > 0.2 and blue > 0.2 and green < min(red, blue) * 0.35
                    for red, green, blue in colors]
    return {
        "mean_rgb": statistics.fmean(channels),
        "standard_deviation_rgb": statistics.pstdev(channels),
        "maximum_rgb": max(channels),
        "nonblack_fraction": sum(value > 0.01 for value in luminance) / len(luminance),
        "midtone_fraction": sum(0.03 < value < 0.8 for value in luminance) / len(luminance),
        "magenta_like_fraction": sum(magenta_like) / len(magenta_like),
    }


def _safe_name(camera, index: int) -> str:
    entity_index = camera.get("qb_entity_index", index)
    classname = camera.get("qb_prop_classname", camera.name)
    slug = re.sub(r"[^a-z0-9]+", "-", str(classname).casefold()).strip("-")
    return f"camera-{entity_index}-{slug}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-scene-sha256")
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

    scene_path = args.scene.resolve()
    scene_sha256 = _sha256(scene_path)
    if args.expected_scene_sha256:
        assert scene_sha256 == args.expected_scene_sha256
    args.output_dir.mkdir(parents=True, exist_ok=False)
    assert bpy.ops.wm.open_mainfile(filepath=str(scene_path)) == {"FINISHED"}
    assert "bl_ext.user_default.quakeblend" not in bpy.context.preferences.addons

    roots = [root for root in bpy.data.collections
             if root.get("qb_source_game") == "q1"
             and root.get("qb_source_sha256") == EXPECTED_SOURCE_SHA256]
    assert len(roots) == 1
    root = roots[0]
    meshes = [obj for obj in root.all_objects if obj.type == "MESH"]
    lights = [obj for obj in root.all_objects if obj.type == "LIGHT"]
    cameras = sorted(
        (obj for obj in root.all_objects if obj.type == "CAMERA"),
        key=lambda obj: (obj.get("qb_entity_index", 0), obj.name),
    )
    assert len(meshes) == 3441 and len(lights) == 296 and len(cameras) == 7
    assert {camera.get("qb_entity_index") for camera in cameras} == EXPECTED_CAMERA_ENTITIES
    materials = {slot.material for obj in meshes for slot in obj.material_slots if slot.material}
    assert len(materials) == 83
    placeholders = sorted(material.name for material in materials if material.get("qb_placeholder"))
    assert len(placeholders) == 12
    hidden_tools = [obj for obj in meshes if obj.hide_get()]
    for obj in hidden_tools:
        obj.hide_render = True

    scene = bpy.context.scene
    _configure_render(scene)
    inspection_data = bpy.data.lights.new("LibreQuake inspection light", "POINT")
    inspection_data.energy = 1500.0
    inspection_data.shadow_soft_size = 0.25
    inspection_light = bpy.data.objects.new("LibreQuake inspection light", inspection_data)
    scene.collection.objects.link(inspection_light)
    records = []
    rendered_pixels = {}
    for index, camera in enumerate(cameras):
        camera.data.clip_start = 0.01
        camera.data.clip_end = 1000.0
        scene.camera = camera
        inspection_light.location = camera.matrix_world.translation
        bpy.context.view_layer.update()
        name = _safe_name(camera, index)
        pixels, artifacts = _render(scene, args.output_dir, name)
        rendered_pixels[camera.get("qb_entity_index")] = pixels
        record = {
            "name": camera.name,
            "entity_index": camera.get("qb_entity_index"),
            "classname": camera.get("qb_prop_classname"),
            "matrix_world": [list(row) for row in camera.matrix_world],
            "metrics": _metrics(pixels),
            "artifacts": artifacts,
        }
        records.append(record)

    positive = [record for record in records
                if record["entity_index"] in POSITIVE_CAMERA_ENTITIES]
    assert len(positive) == len(POSITIVE_CAMERA_ENTITIES)
    assert all(record["metrics"]["nonblack_fraction"] > 0.7 for record in positive), positive
    assert all(record["metrics"]["midtone_fraction"] > 0.4 for record in positive), positive
    assert all(record["metrics"]["magenta_like_fraction"] < 0.001 for record in positive), positive
    deathmatch = next(record for record in records if record["entity_index"] == 1300)
    assert deathmatch["metrics"]["magenta_like_fraction"] > 0.1, deathmatch

    primary_camera = next(camera for camera in cameras
                          if camera.get("qb_entity_index") == PRIMARY_CAMERA_ENTITY)
    scene.camera = primary_camera
    inspection_light.location = primary_camera.matrix_world.translation
    repeated, repeated_artifacts = _render(
        scene, args.output_dir, "camera-866-info-player-start-repeat"
    )
    primary = rendered_pixels[PRIMARY_CAMERA_ENTITY]
    repeat_max_error = max(abs(left - right) for left, right in zip(primary, repeated))
    assert repeat_max_error < 1e-6
    inspection_data.energy = 0.0
    source_lighting, source_lighting_artifacts = _render(
        scene, args.output_dir, "camera-866-info-player-start-source-lights"
    )
    primary_metrics = _metrics(primary)
    source_lighting_metrics = _metrics(source_lighting)
    assert source_lighting_metrics["mean_rgb"] < primary_metrics["mean_rgb"] * 0.01
    assert _sha256(scene_path) == scene_sha256
    report = {
        "blender": bpy.app.version_string,
        "scene": str(scene_path),
        "scene_sha256": scene_sha256,
        "source_sha256": EXPECTED_SOURCE_SHA256,
        "resolution": [WIDTH, HEIGHT],
        "meshes": len(meshes),
        "lights": len(lights),
        "cameras": records,
        "materials": len(materials),
        "placeholder_materials": placeholders,
        "harness_hidden_meshes": len(hidden_tools),
        "inspection_light_watts": 1500.0,
        "primary_camera_entity": PRIMARY_CAMERA_ENTITY,
        "primary_repeat_max_error": repeat_max_error,
        "primary_repeat_artifacts": repeated_artifacts,
        "primary_source_lighting_metrics": source_lighting_metrics,
        "primary_source_lighting_artifacts": source_lighting_artifacts,
    }
    (args.output_dir / "report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))
    print("QUAKEBLEND_LIBREQUAKE_Q1_VISUAL_OK cameras lighting materials determinism")


if __name__ == "__main__":
    main()
