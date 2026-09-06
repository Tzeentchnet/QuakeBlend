"""Build Blender meshes from parsed brushes and BSP face data."""

from __future__ import annotations

import math
from typing import Iterable, Sequence

import bmesh
import bpy

from ..formats.brushdef3 import base_axes_for_normal
from ..formats.common import Vec3
from ..formats.csg import BrushFace
from ..formats.map_q1 import MapBrush, TexInfo as MapTexInfo
from . import builder_materials


# --------------------------------------------------------------- mesh helpers


def _new_mesh_object(name: str, collection: bpy.types.Collection) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    return obj


# --------------------------------------------------------------- map brushes


def build_map_brush(brush: MapBrush, faces: Sequence[BrushFace], name: str,
                    collection: bpy.types.Collection,
                    materials: builder_materials.MaterialCache,
                    *, scale: float, create_materials: bool = True) -> bpy.types.Object | None:
    """Build a Blender object for one CSG brush.

    ``faces`` are the polygons produced by :func:`quakeblend.formats.csg.brush_faces`
    in the same order as ``brush.faces``.
    """
    valid = [(index, face) for index, face in enumerate(faces) if len(face.vertices) >= 3]
    if not valid:
        return None

    obj = _new_mesh_object(name, collection)
    bm = bmesh.new()

    # Material slots (preserve order; first occurrence wins).
    slot_index: dict[str, int] = {}
    for _, face in valid:
        if create_materials and face.texture and face.texture not in slot_index:
            slot_index[face.texture] = len(slot_index)
            mat = materials.get(face.texture)
            if mat is not None:
                obj.data.materials.append(mat)
            else:
                obj.data.materials.append(
                    builder_materials.get_or_create_placeholder_material(
                        face.texture,
                        asset_key=f"placeholder|map|{face.texture.casefold()}",
                    )
                )
                slot_index[face.texture] = len(obj.data.materials) - 1

    uv_layer = bm.loops.layers.uv.new("UVMap")
    source_layer = bm.faces.layers.int.new("qb_source_face")
    width_layer = bm.faces.layers.int.new("qb_texture_width")
    height_layer = bm.faces.layers.int.new("qb_texture_height")
    bm_vertex_by_position = {}
    for source_index, face in valid:
        bm_verts = []
        for vertex in face.vertices:
            position = (vertex.x * scale, vertex.y * scale, vertex.z * scale)
            bm_vertex = bm_vertex_by_position.get(position)
            if bm_vertex is None:
                bm_vertex = bm.verts.new(position)
                bm_vertex_by_position[position] = bm_vertex
            bm_verts.append(bm_vertex)
        try:
            bm_face = bm.faces.new(bm_verts)
        except ValueError:
            # Duplicate face — possible on coplanar brush parts; skip.
            continue
        bm_face[source_layer] = source_index
        dimensions = (face.metadata or {}).get("tex_size", (64, 64))
        bm_face[width_layer], bm_face[height_layer] = dimensions
        if face.texture and face.texture in slot_index:
            bm_face.material_index = slot_index[face.texture]
        # UVs (Standard or Valve220 — see _project_uv below).
        # We need the original MapBrush texinfo, attached via face.metadata.
        if face.metadata and "tex" in face.metadata:
            tex: MapTexInfo = face.metadata["tex"]
            tex_size = face.metadata.get("tex_size", (64, 64))
            normal = face.metadata.get("normal")
            for loop, vert in zip(bm_face.loops, face.vertices):
                u, v = _project_uv(tex, vert, tex_size, normal)
                loop[uv_layer].uv = (u, 1.0 - v)

    bm.normal_update()
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    return obj


def _project_uv(tex: MapTexInfo, p: Vec3, tex_size: tuple[int, int],
                normal: Vec3 | None = None) -> tuple[float, float]:
    """Project a world-space point to UV using either Valve220 or Standard math."""
    w, h = tex_size
    xscale = math.copysign(max(abs(tex.xscale), 1e-6), tex.xscale or 1.0)
    yscale = math.copysign(max(abs(tex.yscale), 1e-6), tex.yscale or 1.0)
    if tex.is_valve220 and tex.s_axis is not None and tex.t_axis is not None:
        u = (p.dot(tex.s_axis) / xscale + tex.s_offset) / max(w, 1)
        v = (p.dot(tex.t_axis) / yscale + tex.t_offset) / max(h, 1)
        return u, v
    # Standard projection: pick s/t axes from the face normal using the
    # idTech ``TextureAxisFromPlane`` table. Fall back to the X/Y plane
    # (most common for flat surfaces) when no normal is supplied.
    if normal is not None:
        s_axis, t_axis = base_axes_for_normal(normal)
    else:
        s_axis = Vec3(1, 0, 0)
        t_axis = Vec3(0, -1, 0)
    cos_r = math.cos(math.radians(tex.rotation))
    sin_r = math.sin(math.radians(tex.rotation))
    s = p.dot(s_axis)
    t = p.dot(t_axis)
    # Apply rotation around (0,0).
    sr = s * cos_r - t * sin_r
    tr = s * sin_r + t * cos_r
    u = (sr / xscale + tex.xoffset) / max(w, 1)
    v = (tr / yscale + tex.yoffset) / max(h, 1)
    return u, v


# --------------------------------------------------------------- BSP faces


def build_bsp_geometry(name: str, vertices: Sequence[Vec3],
                       face_polygons: Iterable[Sequence[int]],
                       face_materials: Iterable[int],
                       face_uvs: Iterable[Sequence[tuple[float, float]]],
                       collection: bpy.types.Collection,
                       material_list: Sequence[bpy.types.Material],
                       *, scale: float, corner_channels=None,
                       source_faces=None, shader_indices=None) -> bpy.types.Object:
    """Build a single mesh from BSP-style face data."""
    obj = _new_mesh_object(name, collection)
    for mat in material_list:
        obj.data.materials.append(mat)

    bm = bmesh.new()
    bm_verts = [bm.verts.new((v.x * scale, v.y * scale, v.z * scale)) for v in vertices]
    bm.verts.ensure_lookup_table()

    uv_layer = bm.loops.layers.uv.new("UVMap")
    light_layer = bm.loops.layers.uv.new("Q3Lightmap") if corner_channels is not None else None
    color_layer = bm.loops.layers.float_color.new("qb_q3_color") if corner_channels is not None else None
    normal_layer = bm.loops.layers.float_vector.new("qb_q3_normal") if corner_channels is not None else None
    source_layer = bm.faces.layers.int.new("qb_q3_source_face") if source_faces is not None else None
    shader_layer = bm.faces.layers.int.new("qb_q3_shader_index") if shader_indices is not None else None

    polys = list(face_polygons)
    mats = list(face_materials)
    uvs = list(face_uvs)
    for face_index, (poly_indices, mat_idx, poly_uvs) in enumerate(zip(polys, mats, uvs)):
        channels = corner_channels[face_index] if corner_channels is not None else None
        if channels and len(poly_indices) >= 3:
            first, second, third = (vertices[index] for index in poly_indices[:3])
            source_normal = Vec3(*channels[0][6:9])
            if (second - first).cross(third - first).dot(source_normal) < 0:
                poly_indices = list(reversed(poly_indices))
                poly_uvs = list(reversed(poly_uvs))
                channels = list(reversed(channels))
        if len(poly_indices) < 3:
            continue
        try:
            face = bm.faces.new([bm_verts[i] for i in poly_indices])
        except ValueError:
            continue
        if 0 <= mat_idx < len(material_list):
            face.material_index = mat_idx
        if source_layer is not None:
            face[source_layer] = source_faces[face_index]
        if shader_layer is not None:
            face[shader_layer] = shader_indices[face_index]
        for loop, uv in zip(face.loops, poly_uvs):
            loop[uv_layer].uv = uv
        if corner_channels is not None:
            for loop, values in zip(face.loops, channels):
                loop[light_layer].uv = values[:2]
                loop[color_layer] = values[2:6]
                length = math.sqrt(sum(value * value for value in values[6:9]))
                loop[normal_layer] = tuple(value / length for value in values[6:9]) if length else (0, 0, 1)

    bm.normal_update()
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    if corner_channels is not None:
        obj.data.uv_layers.active_index = 0
        obj.data.normals_split_custom_set([tuple(item.vector) for item in obj.data.attributes["qb_q3_normal"].data])
    return obj
