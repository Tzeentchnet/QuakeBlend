"""Provenance and strict extraction for the opt-in MAP transform prototype."""

from __future__ import annotations

import hashlib
import json
import math

from ..formats import map_transform
from ..formats.common import Vec3


def mesh_signature(obj):
    mesh = obj.data
    attributes = {}
    for name in ("qb_source_face", "qb_texture_width", "qb_texture_height"):
        attribute = mesh.attributes.get(name)
        if attribute is None or attribute.domain != "FACE" or attribute.data_type != "INT":
            raise ValueError("Missing source-face provenance; reimport the MAP")
        attributes[name] = [item.value for item in attribute.data]
    payload = {
        "vertices": [tuple(vertex.co) for vertex in mesh.vertices],
        "edges": [tuple(edge.vertices) for edge in mesh.edges],
        "faces": [(tuple(face.vertices), face.material_index) for face in mesh.polygons],
        "attributes": attributes,
        "materials": [(slot.link, slot.material.name_full if slot.material else None)
                      for slot in obj.material_slots],
        "uv": [(layer.name, [tuple(loop.uv) for loop in layer.data]) for layer in mesh.uv_layers],
        "surface_metadata": {key: list(obj[key]) if not isinstance(obj[key], str) else obj[key]
                             for key in ("qb_face_textures", "qb_face_contents", "qb_face_flags", "qb_face_value")
                             if key in obj},
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode("utf-8")).hexdigest()


def capture_brush(root, obj):
    obj["qb_map_import_id"] = root["qb_map_import_id"]
    key = f"{obj['qb_owner_entity_index']}:{obj['qb_brush_index']}"
    root["qb_transform_baselines"][key] = mesh_signature(obj)


def apply_transforms(level, collection, source_bytes, *, entity_edits=False):
    if collection.get("qb_omitted_brushes"):
        raise ValueError("Transform export requires a complete import; reimport with all brushes included (viewport hiding is allowed)")
    if (collection.get("qb_source_sha256") != hashlib.sha256(source_bytes).hexdigest()
            or not collection.get("qb_map_import_id") or "qb_transform_baselines" not in collection):
        raise ValueError("Source changed or provenance is missing; reimport the MAP")
    scale = float(collection.get("qb_import_scale", 0))
    if not math.isfinite(scale) or scale <= 0 or scale != collection.get("qb_transform_scale"):
        raise ValueError("Recorded import scale changed or is invalid; reimport the MAP")
    expected = {(entity_index, brush_index)
                for entity_index, entity in enumerate(level.entities)
                for brush_index, brush in enumerate(entity.brushes)}
    found = {}
    anchors = set()
    for obj in collection.all_objects:
        if entity_edits and obj.get("qb_entity_role") == "ENTITY":
            index = obj.get("qb_entity_index")
            if index in anchors or obj.parent or obj.constraints or obj.animation_data:
                raise ValueError("Entity overlays require unique unparented, unanimated anchors")
            anchors.add(index)
        if obj.type != "MESH":
            continue
        identity = (obj.get("qb_owner_entity_index"), obj.get("qb_brush_index"))
        if identity not in expected or identity in found or obj.get("qb_map_import_id") != collection["qb_map_import_id"]:
            raise ValueError("Missing, duplicate or foreign brush ownership")
        if obj.mode != "OBJECT" or obj.modifiers or obj.data.shape_keys:
            raise ValueError("Transform export requires Object Mode with no modifiers or shape keys")
        ancestor = obj
        while ancestor is not None:
            if ancestor.constraints or ancestor.animation_data or (ancestor.parent and ancestor.parent_type != "OBJECT"):
                raise ValueError("Animated, constrained or deforming object hierarchies are unsupported")
            ancestor = ancestor.parent
        baseline = collection["qb_transform_baselines"].get(f"{identity[0]}:{identity[1]}")
        if baseline != mesh_signature(obj):
            raise ValueError("Brush vertices, topology, UVs, material assignments or source metadata changed")
        face_ids = [item.value for item in obj.data.attributes["qb_source_face"].data]
        brush = level.entities[identity[0]].brushes[identity[1]]
        if sorted(face_ids) != list(range(len(brush.faces))):
            raise ValueError("Source-face mapping is incomplete or ambiguous")
        edge_uses = {}
        for polygon in obj.data.polygons:
            for edge in polygon.edge_keys:
                edge_uses[edge] = edge_uses.get(edge, 0) + 1
        if not edge_uses or any(count != 2 for count in edge_uses.values()):
            raise ValueError("Imported brush mesh is not closed")
        matrix = obj.matrix_world
        columns = tuple(Vec3(*matrix.to_3x3().col[index]) for index in range(3))
        offset = Vec3(*matrix.translation) * (1 / scale)
        found[identity] = map_transform.transform_brush(brush, columns, offset)
    if set(found) != expected:
        raise ValueError("Missing brush objects; deletion is unsupported")
    for (entity_index, brush_index), brush in found.items():
        level.entities[entity_index].brushes[brush_index] = brush
