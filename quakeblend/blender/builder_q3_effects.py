"""Saved, non-destructive Q3 corner UV animation and vertex waves."""

from __future__ import annotations

import bpy

from .builder_q3_materials import Nodes, stage_coordinates, uv_attribute


def apply_effects(obj, shaders, scene, scale, *, animate_shaders=True, deform_geometry=True):
    used_slots = {polygon.material_index for polygon in obj.data.polygons}
    selected = [(index, shaders[material.name]) for index, material in enumerate(obj.data.materials)
                if index in used_slots and material and material.name in shaders]
    if not selected or not any((deform_geometry and shader.get("deformvertexes")) or
                              any(stage.get("tcmod") for stage in shader.stages) for _, shader in selected):
        return
    tree = bpy.data.node_groups.new(f"{obj.name} Q3 shader coordinates", "GeometryNodeTree")
    tree.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    tree["qb_q3_effects"] = True
    nodes = Nodes(tree)
    geometry = nodes.node("NodeGroupInput").outputs["Geometry"]
    has_deformation = deform_geometry and any(shader.get("deformvertexes") for _, shader in selected)
    time = nodes.time(scene) if animate_shaders or has_deformation else 0
    stage_time = time if animate_shaders else 0

    def attribute(name):
        node = nodes.node("GeometryNodeInputNamedAttribute")
        node.data_type = "FLOAT_VECTOR"
        node.inputs["Name"].default_value = name
        return node.outputs["Attribute"]

    def store(geometry_input, name, value, *, domain="CORNER", selection=True):
        node = nodes.node("GeometryNodeStoreNamedAttribute")
        node.data_type = "FLOAT_VECTOR"
        node.domain = domain
        node.inputs["Name"].default_value = name
        nodes.put(node.inputs["Geometry"], geometry_input)
        nodes.put(node.inputs["Selection"], selection)
        nodes.put(node.inputs["Value"], value)
        return node.outputs["Geometry"]

    normal = attribute("qb_q3_normal") if obj.data.attributes.get("qb_q3_normal") else nodes.node("GeometryNodeInputNormal").outputs[0]
    geometry = store(geometry, "qb_q3_effect_normal", normal)
    if has_deformation:
        split = nodes.node("GeometryNodeSplitEdges")
        nodes.put(split.inputs["Mesh"], geometry)
        geometry = split.outputs["Mesh"]
    material_index = nodes.node("GeometryNodeInputMaterialIndex").outputs[0]
    base_uv = attribute(obj.data.uv_layers.active.name)
    base_horizontal, base_vertical, _ = nodes.separate(base_uv)
    source_uv = nodes.combine(base_horizontal, nodes.math("SUBTRACT", 1, base_vertical))
    light_uv = attribute("Q3Lightmap") if obj.data.uv_layers.get("Q3Lightmap") else source_uv
    if obj.data.uv_layers.get("Q3Lightmap"):
        light_horizontal, light_vertical, _ = nodes.separate(light_uv)
        light_uv = nodes.combine(light_horizontal, nodes.math("SUBTRACT", 1, light_vertical))
    position = nodes.scale(nodes.node("GeometryNodeInputPosition").outputs[0], 1 / scale)
    processed = set()
    for slot, shader in selected:
        selection = nodes.math("LESS_THAN", nodes.math("ABSOLUTE", nodes.math("SUBTRACT", material_index, slot)), .5)
        for directive in shader.directives:
            if not deform_geometry or directive.name != "deformvertexes":
                continue
            divisor = float(directive.args[1])
            horizontal, vertical, depth = nodes.separate(position)
            phase_offset = nodes.math("DIVIDE", nodes.math("ADD", nodes.math("ADD", horizontal, vertical), depth), divisor)
            displacement = nodes.wave(directive.args[2:], time, phase_offset)
            set_position = nodes.node("GeometryNodeSetPosition")
            nodes.put(set_position.inputs["Geometry"], geometry)
            nodes.put(set_position.inputs["Selection"], selection)
            nodes.put(set_position.inputs["Offset"], nodes.scale(attribute("qb_q3_effect_normal"), nodes.math("MULTIPLY", displacement, scale)))
            geometry = set_position.outputs["Geometry"]
        for index, stage in enumerate(shader.stages):
            if not stage.get("tcmod"):
                continue
            name = uv_attribute(shader, index)
            if name in processed:
                continue
            processed.add(name)
            tcgen = stage.get("tcgen")
            uses_lightmap = (tcgen and tcgen.args[0].casefold() == "lightmap") or (not tcgen and tuple(name.casefold() for name in stage.images()) == ("$lightmap",))
            uv = stage_coordinates(nodes, stage, light_uv if uses_lightmap else source_uv, position, stage_time)
            geometry = store(geometry, name, uv)
    output = nodes.node("NodeGroupOutput")
    nodes.put(output.inputs["Geometry"], geometry)
    modifier = obj.modifiers.new("Q3 shader animation", "NODES")
    modifier.node_group = tree
