"""Check Eevee additive material feasibility in linear pixels, not just nodes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy


def emission_material(name, color, *, additive=False, method="BLENDED"):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()
    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (*color, 1)
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = emission.outputs[0]
    if additive:
        transparent = nodes.new("ShaderNodeBsdfTransparent")
        addition = nodes.new("ShaderNodeAddShader")
        material.node_tree.links.new(transparent.outputs[0], addition.inputs[0])
        material.node_tree.links.new(shader, addition.inputs[1])
        shader = addition.outputs[0]
        material.surface_render_method = method
    material.node_tree.links.new(shader, output.inputs["Surface"])
    return material


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--method", choices=("BLENDED", "DITHERED"), default="BLENDED")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    assert bpy.app.background and not sys.flags.optimize
    args.output_dir.mkdir(parents=True, exist_ok=False)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 256
    scene.render.resolution_y = 128
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_depth = "32"
    scene.view_settings.view_transform = "Standard"
    backgrounds = [(0.03, 0.05, 0.1), (0.6, 0.4, 0.2)]
    foreground = (0.15, 0.2, 0.05)
    material = emission_material("Additive", foreground, additive=True, method=args.method)
    for index, background in enumerate(backgrounds):
        for height, assigned in [(0, emission_material(f"Background{index}", background)), (0.1, material)]:
            bpy.ops.mesh.primitive_plane_add(size=2, location=(-1.1 + index * 2.2, 0, height))
            bpy.context.object.data.materials.append(assigned)
    bpy.ops.object.camera_add(location=(0, 0, 6))
    scene.camera = bpy.context.object
    scene.camera.data.type = "ORTHO"
    scene.camera.data.ortho_scale = 4.6
    scene.render.filepath = str((args.output_dir / "additive.exr").resolve())
    bpy.ops.render.render(write_still=True)
    image = bpy.data.images.load(scene.render.filepath)
    pixels = list(image.pixels)
    measured = [pixels[(64 * 256 + column) * 4:(64 * 256 + column) * 4 + 3] for column in (64, 192)]
    expected = [[back + front for back, front in zip(background, foreground)] for background in backgrounds]
    error = max(abs(actual - target) for actual_color, target_color in zip(measured, expected)
                for actual, target in zip(actual_color, target_color))
    report = {"method": args.method, "expected": expected, "actual": measured, "max_error": error}
    (args.output_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    assert error < .01, "Eevee additive nodes do not match framebuffer addition"
    print("QUAKEBLEND_Q3_ADDITIVE_OK")


if __name__ == "__main__":
    main()
