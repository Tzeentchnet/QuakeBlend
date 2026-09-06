"""Test the depth limitation of a Q3 sky-boundary surface in Eevee."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy


def material(name, color):
    result = bpy.data.materials.new(name)
    result.use_nodes = True
    nodes = result.node_tree.nodes
    nodes.clear()
    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (*color, 1)
    output = nodes.new("ShaderNodeOutputMaterial")
    result.node_tree.links.new(emission.outputs[0], output.inputs["Surface"])
    return result


def plane(name, location, size, assigned):
    bpy.ops.mesh.primitive_plane_add(size=size, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(assigned)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    assert bpy.app.background and not sys.flags.optimize
    args.output_dir.mkdir(parents=True, exist_ok=False)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 384
    scene.render.resolution_y = 128
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_depth = "32"
    scene.view_settings.view_transform = "Standard"
    sky_color = (0.1, 0.2, 0.5)
    solid_color = (0.6, 0.1, 0.05)
    sky = material("Sky boundary", sky_color)
    solid = material("Opaque geometry", solid_color)
    for horizontal in (-2, 0, 2):
        plane("Sky boundary", (horizontal, 0, 0), 1.8, sky)
    plane("Near opaque control", (0, 0, 1), 1, solid)
    plane("Beyond-boundary opaque", (2, 0, -1), 1, solid)
    bpy.ops.object.camera_add(location=(0, 0, 6))
    scene.camera = bpy.context.object
    scene.camera.data.type = "ORTHO"
    scene.camera.data.ortho_scale = 6
    scene.render.filepath = str((args.output_dir / "sky-depth.exr").resolve())
    bpy.ops.render.render(write_still=True)
    image = bpy.data.images.load(scene.render.filepath)
    pixels = list(image.pixels)
    measured = [pixels[(64 * 384 + column) * 4:(64 * 384 + column) * 4 + 3] for column in (64, 192, 320)]
    expected = [sky_color, solid_color, solid_color]
    errors = [max(abs(actual - target) for actual, target in zip(actual_color, target_color))
              for actual_color, target_color in zip(measured, expected)]
    report = {"cases": ["sky_only", "near_opaque", "beyond_boundary_opaque"],
              "expected_far_depth": expected, "actual": measured, "max_errors": errors,
              "far_depth_supported": max(errors) < .01}
    (args.output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_depth = "8"
    image.save_render(str((args.output_dir / "sky-depth.png").resolve()), scene=scene)
    bpy.ops.wm.save_as_mainfile(filepath=str((args.output_dir / "sky-depth-probe.blend").resolve()))
    print(json.dumps(report, indent=2))
    assert errors[0] < .01 and errors[1] < .01, "Sky or opaque control failed"
    assert report["far_depth_supported"], "Boundary surface occludes geometry that Q3's far-depth sky leaves visible"
    print("QUAKEBLEND_Q3_SKY_DEPTH_OK")


if __name__ == "__main__":
    main()
