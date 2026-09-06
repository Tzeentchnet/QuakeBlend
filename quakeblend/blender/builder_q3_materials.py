"""Q3-only stage composition, packed resources, and persistent shader timing."""

from __future__ import annotations

import hashlib
import math

import bpy

from ..formats.shader_q3 import Directive, Shader, Stage
from ..formats.shader_q3_math import blend, validate
from ..utils.q3_assets import Q3Assets
from . import builder_materials


class Nodes:
    def __init__(self, tree):
        self.tree = tree

    def node(self, kind):
        return self.tree.nodes.new(kind)

    def put(self, socket, value):
        if isinstance(value, bpy.types.NodeSocket):
            self.tree.links.new(value, socket)
        else:
            socket.default_value = value

    def math(self, operation, left, right=0):
        node = self.node("ShaderNodeMath")
        node.operation = operation
        self.put(node.inputs[0], left)
        self.put(node.inputs[1], right)
        return node.outputs[0]

    def vector(self, operation, left, right=(0, 0, 0)):
        node = self.node("ShaderNodeVectorMath")
        node.operation = operation
        self.put(node.inputs[0], left)
        self.put(node.inputs[1], right)
        return node.outputs["Value" if operation in {"DOT_PRODUCT", "LENGTH"} else "Vector"]

    def scale(self, value, factor):
        return self.vector("MULTIPLY", value, self.combine(factor, factor, factor))

    def combine(self, horizontal, vertical, depth=0):
        node = self.node("ShaderNodeCombineXYZ")
        for socket, value in zip(node.inputs, (horizontal, vertical, depth)):
            self.put(socket, value)
        return node.outputs[0]

    def separate(self, value):
        node = self.node("ShaderNodeSeparateXYZ")
        self.put(node.inputs[0], value)
        return tuple(node.outputs)

    def clamp(self, value):
        return self.math("MINIMUM", 1, self.math("MAXIMUM", 0, value))

    def wave(self, args, time, phase_offset=0):
        kind = args[0].casefold()
        base, amplitude, phase, frequency = map(float, args[1:])
        cycle = self.math("ADD", self.math("ADD", self.math("MULTIPLY", time, frequency), phase), phase_offset)
        fraction = self.math("FRACT", cycle)
        if kind == "sin":
            value = self.math("SINE", self.math("MULTIPLY", cycle, math.tau))
        elif kind == "square":
            value = self.math("SUBTRACT", self.math("MULTIPLY", self.math("LESS_THAN", fraction, .5), 2), 1)
        elif kind == "triangle":
            shifted = self.math("FRACT", self.math("ADD", fraction, .25))
            value = self.math("SUBTRACT", 1, self.math("MULTIPLY", 4, self.math("ABSOLUTE", self.math("SUBTRACT", shifted, .5))))
        elif kind == "sawtooth":
            value = fraction
        else:
            value = self.math("SUBTRACT", 1, fraction)
        return self.math("ADD", base, self.math("MULTIPLY", amplitude, value))

    def time(self, scene):
        value = self.node("ShaderNodeValue")
        value.label = "Q3 seconds from scene start"
        driver = value.outputs[0].driver_add("default_value").driver
        for name, path in (("start", "frame_start"), ("fps", "render.fps"), ("base", "render.fps_base")):
            variable = driver.variables.new()
            variable.name = name
            variable.type = "SINGLE_PROP"
            variable.targets[0].id_type = "SCENE"
            variable.targets[0].id = scene
            variable.targets[0].data_path = path
        driver.expression = "(frame-start)*base/fps"
        return value.outputs[0]


def uv_attribute(shader: Shader, index: int) -> str:
    digest = hashlib.sha256((shader.source + shader.sha256 + shader.name).encode()).hexdigest()[:12]
    return f"qb_q3_uv_{digest}_{index}"


def stage_coordinates(nodes, stage, coordinates, position, time):
    horizontal, vertical, _ = nodes.separate(coordinates)
    for directive in stage.directives:
        if directive.name != "tcmod":
            continue
        kind = directive.args[0].casefold()
        if kind == "stretch":
            stretch = nodes.wave(directive.args[1:], time)
            factor = nodes.math("DIVIDE", 1, stretch)
            horizontal = nodes.math("ADD", .5, nodes.math("MULTIPLY", nodes.math("SUBTRACT", horizontal, .5), factor))
            vertical = nodes.math("ADD", .5, nodes.math("MULTIPLY", nodes.math("SUBTRACT", vertical, .5), factor))
            continue
        values = directive.numbers(1)
        if kind == "scale":
            horizontal = nodes.math("MULTIPLY", horizontal, values[0])
            vertical = nodes.math("MULTIPLY", vertical, values[1])
        elif kind == "scroll":
            horizontal = nodes.math("ADD", horizontal, nodes.math("FRACT", nodes.math("MULTIPLY", time, values[0])))
            vertical = nodes.math("ADD", vertical, nodes.math("FRACT", nodes.math("MULTIPLY", time, values[1])))
        elif kind == "rotate":
            angle = nodes.math("MULTIPLY", time, -math.radians(values[0]))
            cosine, sine = nodes.math("COSINE", angle), nodes.math("SINE", angle)
            centered_horizontal = nodes.math("SUBTRACT", horizontal, .5)
            centered_vertical = nodes.math("SUBTRACT", vertical, .5)
            horizontal = nodes.math("ADD", .5, nodes.math("SUBTRACT", nodes.math("MULTIPLY", centered_horizontal, cosine), nodes.math("MULTIPLY", centered_vertical, sine)))
            vertical = nodes.math("ADD", .5, nodes.math("ADD", nodes.math("MULTIPLY", centered_horizontal, sine), nodes.math("MULTIPLY", centered_vertical, cosine)))
        elif kind == "transform":
            old_horizontal = horizontal
            horizontal = nodes.math("ADD", values[4], nodes.math("ADD", nodes.math("MULTIPLY", horizontal, values[0]), nodes.math("MULTIPLY", vertical, values[2])))
            vertical = nodes.math("ADD", values[5], nodes.math("ADD", nodes.math("MULTIPLY", old_horizontal, values[1]), nodes.math("MULTIPLY", vertical, values[3])))
        elif kind == "turb":
            position_horizontal, position_vertical, position_depth = nodes.separate(position)
            phase = nodes.math("ADD", values[2], nodes.math("MULTIPLY", time, values[3]))
            phase_horizontal = nodes.math("ADD", phase, nodes.math("DIVIDE", nodes.math("ADD", position_horizontal, position_depth), 1024))
            phase_vertical = nodes.math("ADD", phase, nodes.math("DIVIDE", position_vertical, 1024))
            horizontal = nodes.math("ADD", horizontal, nodes.math("MULTIPLY", values[1], nodes.math("SINE", nodes.math("MULTIPLY", math.tau, phase_horizontal))))
            vertical = nodes.math("ADD", vertical, nodes.math("MULTIPLY", values[1], nodes.math("SINE", nodes.math("MULTIPLY", math.tau, phase_vertical))))
    return nodes.combine(horizontal, nodes.math("SUBTRACT", 1, vertical))


class Q3Materials:
    def __init__(self, root, scene, *, baked=False, lighting=None, lightmaps=(), source_key="", scale=1 / 32,
                 animate_shaders=True, deform_geometry=True):
        self.lighting = lighting or ("BAKED" if baked else "RELIT")
        if self.lighting not in {"BAKED", "FULLBRIGHT", "RELIT"}:
            raise ValueError(f"Unsupported Q3 lighting mode: {self.lighting}")
        self.assets = Q3Assets.from_folder(root) if root is not None else Q3Assets({})
        self.scene = scene
        self.baked = self.lighting == "BAKED"
        self.animate_shaders = animate_shaders
        self.deform_geometry = deform_geometry
        self.lightmaps = lightmaps
        self.source_key = source_key
        self.scale = scale
        self.cache = {}
        self.effects = {}
        self.diagnostics = {}

    def image(self, resource):
        digest = hashlib.sha256(self.assets.read(resource)).hexdigest()
        image = builder_materials.load_external_image(resource.name, resource.path, asset_key=f"q3-stage-image|{resource.path}|{digest}")
        image.alpha_mode = "CHANNEL_PACKED"
        if not image.packed_file:
            image.pack()
        return image

    def lightmap(self, index):
        if not self.baked or not 0 <= index < len(self.lightmaps):
            return None
        data = self.lightmaps[index]
        rgba = bytes(component for offset in range(0, len(data), 3) for component in (*data[offset:offset + 3], 255))
        return builder_materials.create_image(f"Q3 lightmap {index}", 128, 128, rgba,
            asset_key=f"q3-lightmap|{self.source_key}|{index}")

    def get(self, name, lightmap_index=-1):
        key = name.casefold(), lightmap_index
        if key in self.cache:
            return self.cache[key]
        try:
            spec = self.assets.material(name)
            shader = spec.shader
            if shader and (shader.get("skyparms") or any(item.name == "surfaceparm" and tuple(value.casefold() for value in item.args) == ("sky",) for item in shader.directives)):
                raise ValueError("Sky rendering deferred")
            if shader is None:
                stages = [Stage((Directive("map", (name,), 0), Directive("rgbgen", ("identity" if not self.baked or lightmap_index >= 0 else "vertex",), 0)))]
                if self.baked and lightmap_index >= 0:
                    stages.append(Stage((Directive("map", ("$lightmap",), 0), Directive("blendfunc", ("filter",), 0))))
                shader = Shader(name, (), tuple(stages), "<implicit>", 0, "")
            validate(shader)
            if spec.missing:
                raise ValueError("Missing images: " + ", ".join(spec.missing))
            if not shader.stages:
                raise ValueError("Non-rendering utility shader")
        except (ValueError, OSError) as exc:
            reason = str(exc)
            self.diagnostics[name] = reason
            material = builder_materials.get_or_create_placeholder_material(name,
                asset_key=f"q3-unavailable|{self.source_key}|{name.casefold()}|{reason}")
            material["qb_q3_status"] = "deferred_sky" if reason == "Sky rendering deferred" else "unavailable"
            material["qb_q3_diagnostic"] = reason
            material["qb_q3_shader"] = name
            material["qb_q3_projection_size"] = [64, 64]
        else:
            material = self.build(spec, shader, lightmap_index)
        self.cache[key] = material
        return material

    def build(self, spec, shader, lightmap_index):
        images = {name: self.image(resource) for name, resource in spec.images}
        if spec.editor_image:
            self.image(spec.editor_image)
        material = bpy.data.materials.new(spec.name)
        material.use_nodes = True
        material.node_tree.nodes.clear()
        material["qb_q3_shader"] = spec.name
        material["qb_q3_source"] = shader.source
        material["qb_q3_shader_sha256"] = shader.sha256
        material["qb_q3_bsp_source"] = self.source_key
        material["qb_asset_key"] = f"q3-shader|{self.source_key}|{shader.source}|{shader.sha256}|{spec.name}|{lightmap_index}|{self.lighting}|{self.animate_shaders}|{self.deform_geometry}"
        material["qb_q3_status"] = "shader" if spec.shader else "implicit"
        material["qb_q3_lighting"] = self.lighting.lower()
        material["qb_q3_animate_shaders"] = self.animate_shaders
        material["qb_q3_deform_geometry"] = self.deform_geometry
        material["qb_q3_lightmap"] = lightmap_index
        try:
            material["qb_q3_projection_size"] = list(self.assets.projection_size(spec))
        except (OSError, ValueError) as exc:
            self.diagnostics[spec.name] = f"{exc}; using 64x64 MAP projection"
            material["qb_q3_projection_size"] = [64, 64]
        cull = shader.get("cull")
        cull_mode = cull.args[0].casefold() if cull else "front"
        material.use_backface_culling = cull_mode == "front"
        nodes = Nodes(material.node_tree)
        time = nodes.time(self.scene) if self.animate_shaders else 0
        vertex = nodes.node("ShaderNodeVertexColor")
        vertex.layer_name = "qb_q3_color"
        lit, unlit = (0, 0, 0), (0, 0, 0)
        destination_alpha = 0
        background = 1
        coverage = 1
        if cull_mode in {"back", "backsided"}:
            coverage = nodes.node("ShaderNodeNewGeometry").outputs["Backfacing"]
        for index, stage in enumerate(shader.stages):
            names = stage.images()
            image_nodes = []
            tcgen = stage.get("tcgen")
            if stage.get("tcmod"):
                coordinates = nodes.node("ShaderNodeAttribute")
                coordinates.attribute_name = uv_attribute(shader, index)
                uv = coordinates.outputs["Vector"]
            else:
                coordinates = nodes.node("ShaderNodeUVMap")
                uses_lightmap = (tcgen and tcgen.args[0].casefold() == "lightmap") or (not tcgen and tuple(name.casefold() for name in names) == ("$lightmap",))
                coordinates.uv_map = "Q3Lightmap" if uses_lightmap else "UVMap"
                uv = coordinates.outputs["UV"]
            if tcgen and tcgen.args[0].casefold() == "environment":
                geometry = nodes.node("ShaderNodeNewGeometry")
                reflected = nodes.vector("REFLECT", nodes.scale(geometry.outputs["Incoming"], -1), geometry.outputs["Normal"])
                _, reflected_vertical, reflected_depth = nodes.separate(reflected)
                uv = nodes.combine(nodes.math("ADD", .5, nodes.math("MULTIPLY", reflected_vertical, .5)),
                                   nodes.math("ADD", .5, nodes.math("MULTIPLY", reflected_depth, .5)))
                material["qb_q3_environment_sampling"] = "per_fragment"
            for name in names:
                if name.casefold() in {"$whiteimage", "$lightmap"}:
                    image = self.lightmap(lightmap_index) if name.casefold() == "$lightmap" else None
                    if image is None:
                        image_nodes.append(((1, 1, 1), 1))
                        continue
                else:
                    image = images[name]
                texture = nodes.node("ShaderNodeTexImage")
                texture.image = image
                texture.extension = "EXTEND" if stage.get("clampmap") else "REPEAT"
                texture.interpolation = "Linear"
                nodes.put(texture.inputs["Vector"], uv)
                image_nodes.append((texture.outputs["Color"], texture.outputs["Alpha"]))
            source, source_alpha = image_nodes[0]
            if len(image_nodes) > 1:
                frequency = float(stage.get("animmap").args[0])
                frame = nodes.math("MODULO", nodes.math("FLOOR", nodes.math("MAXIMUM", 0, nodes.math("MULTIPLY", time, frequency))), len(image_nodes))
                source, source_alpha = (0, 0, 0), 0
                for frame_index, (color, alpha) in enumerate(image_nodes):
                    selected = nodes.math("LESS_THAN", nodes.math("ABSOLUTE", nodes.math("SUBTRACT", frame, frame_index)), .5)
                    source = nodes.vector("ADD", source, nodes.scale(color, selected))
                    source_alpha = nodes.math("ADD", source_alpha, nodes.math("MULTIPLY", alpha, selected))
            rgb = stage.get("rgbgen")
            if rgb and rgb.args[0].casefold() == "wave":
                source = nodes.scale(source, nodes.clamp(nodes.wave(rgb.args[1:], time)))
            elif self.baked and rgb and rgb.args[0].casefold() in {"vertex", "exactvertex", "oneminusvertex"}:
                color = vertex.outputs["Color"]
                if rgb.args[0].casefold() == "oneminusvertex":
                    color = nodes.vector("SUBTRACT", (1, 1, 1), color)
                source = nodes.vector("MULTIPLY", source, color)
            elif rgb and rgb.args[0].casefold() == "const":
                source = nodes.vector("MULTIPLY", source, rgb.numbers(1))
            alpha_gen = stage.get("alphagen")
            if alpha_gen:
                kind = alpha_gen.args[0].casefold()
                if kind == "wave":
                    source_alpha = nodes.math("MULTIPLY", source_alpha, nodes.clamp(nodes.wave(alpha_gen.args[1:], time)))
                elif kind == "const":
                    source_alpha = nodes.math("MULTIPLY", source_alpha, alpha_gen.numbers(1)[0])
                elif kind in {"vertex", "exactvertex", "oneminusvertex"}:
                    alpha = vertex.outputs["Alpha"]
                    if kind == "oneminusvertex":
                        alpha = nodes.math("SUBTRACT", 1, alpha)
                    source_alpha = nodes.math("MULTIPLY", source_alpha, alpha)
            alpha_test = stage.get("alphafunc")
            if alpha_test:
                kind = alpha_test.args[0].casefold()
                passed = nodes.math("GREATER_THAN", source_alpha, 0) if kind == "gt0" else nodes.math("LESS_THAN", source_alpha, 128 / 255)
                if kind == "ge128":
                    passed = nodes.math("SUBTRACT", 1, passed)
                coverage = nodes.math("MULTIPLY", coverage, passed)
            source_factor, destination_factor = blend(stage)
            destination = nodes.vector("ADD", lit, unlit)

            def factor(kind):
                inverse = kind.startswith("one_minus_")
                kind = kind.removeprefix("one_minus_")
                value = {"zero": (0, 0, 0), "one": (1, 1, 1), "src_color": source,
                         "dst_color": destination, "src_alpha": nodes.combine(source_alpha, source_alpha, source_alpha),
                         "dst_alpha": nodes.combine(destination_alpha, destination_alpha, destination_alpha)}[kind]
                return nodes.vector("SUBTRACT", (1, 1, 1), value) if inverse else value

            destination_weight = factor(destination_factor)
            if source_factor == "dst_color":
                weight = nodes.vector("ADD", source, destination_weight)
                lit, unlit = nodes.vector("MULTIPLY", lit, weight), nodes.vector("MULTIPLY", unlit, weight)
            else:
                contribution = nodes.vector("MULTIPLY", source, factor(source_factor))
                lit, unlit = nodes.vector("MULTIPLY", lit, destination_weight), nodes.vector("MULTIPLY", unlit, destination_weight)
                if self.lighting != "RELIT" or (source_factor, destination_factor) == ("one", "one") or any(item.name == "surfaceparm" and tuple(value.casefold() for value in item.args) == ("nolightmap",) for item in shader.directives):
                    unlit = nodes.vector("ADD", unlit, contribution)
                else:
                    lit = nodes.vector("ADD", lit, contribution)
            alpha_source_weight = {"one": 1, "zero": 0, "src_alpha": source_alpha, "dst_alpha": destination_alpha,
                                   "one_minus_src_alpha": nodes.math("SUBTRACT", 1, source_alpha),
                                   "one_minus_dst_alpha": nodes.math("SUBTRACT", 1, destination_alpha)}
            source_weight = alpha_source_weight.get(source_factor, source_alpha if "src" in source_factor else destination_alpha)
            dest_weight = alpha_source_weight.get(destination_factor, destination_alpha if "dst" in destination_factor else source_alpha)
            destination_alpha = nodes.clamp(nodes.math("ADD", nodes.math("MULTIPLY", source_alpha, source_weight), nodes.math("MULTIPLY", destination_alpha, dest_weight)))
            background = nodes.math("MULTIPLY", background, dest_weight)
        emission = nodes.node("ShaderNodeEmission")
        nodes.put(emission.inputs["Color"], unlit)
        output_shader = emission.outputs[0]
        if self.lighting == "RELIT":
            diffuse = nodes.node("ShaderNodeBsdfDiffuse")
            nodes.put(diffuse.inputs["Color"], lit)
            addition = nodes.node("ShaderNodeAddShader")
            nodes.put(addition.inputs[0], output_shader)
            nodes.put(addition.inputs[1], diffuse.outputs[0])
            output_shader = addition.outputs[0]
        transparent = nodes.node("ShaderNodeBsdfTransparent")
        nodes.put(transparent.inputs["Color"], nodes.combine(background, background, background))
        addition = nodes.node("ShaderNodeAddShader")
        nodes.put(addition.inputs[0], transparent.outputs[0])
        nodes.put(addition.inputs[1], output_shader)
        mask = nodes.node("ShaderNodeMixShader")
        empty = nodes.node("ShaderNodeBsdfTransparent")
        nodes.put(mask.inputs[0], coverage)
        nodes.put(mask.inputs[1], empty.outputs[0])
        nodes.put(mask.inputs[2], addition.outputs[0])
        out = nodes.node("ShaderNodeOutputMaterial")
        nodes.put(out.inputs["Surface"], mask.outputs[0])
        material.surface_render_method = "DITHERED" if blend(shader.stages[0]) == ("one", "zero") else "BLENDED"
        self.effects[material.name] = shader
        return material

    def apply(self, obj):
        from .builder_q3_effects import apply_effects

        apply_effects(obj, self.effects, self.scene, self.scale,
                  animate_shaders=self.animate_shaders, deform_geometry=self.deform_geometry)
