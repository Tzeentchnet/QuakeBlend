"""Build Blender meshes from parsed brushes and BSP face data."""

from __future__ import annotations

import math
from typing import Iterable, Sequence

import bmesh
import bpy

from ..formats.common import Vec3
from ..formats.csg import BrushFace
from ..formats.map_q1 import MapBrush, TexInfo as MapTexInfo


# --------------------------------------------------------------- mesh helpers


def _new_mesh_object(name: str, collection: bpy.types.Collection) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    return obj


def _ensure_collection(scene: bpy.types.Scene, name: str,
                       parent: bpy.types.Collection | None = None) -> bpy.types.Collection:
    coll = bpy.data.collections.get(name)
    if coll is not None:
        return coll
    coll = bpy.data.collections.new(name)
    (parent or scene.collection).children.link(coll)
    return coll


# --------------------------------------------------------------- map brushes


def build_map_brush(brush: MapBrush, faces: Sequence[BrushFace], name: str,
                    collection: bpy.types.Collection,
                    materials: dict[str, bpy.types.Material],
                    *, scale: float) -> bpy.types.Object | None:
    """Build a Blender object for one CSG brush.

    ``faces`` are the polygons produced by :func:`quakeblend.formats.csg.brush_faces`
    in the same order as ``brush.faces``.
    """
    valid = [f for f in faces if len(f.vertices) >= 3]
    if not valid:
        return None

    obj = _new_mesh_object(name, collection)
    bm = bmesh.new()

    # Material slots (preserve order; first occurrence wins).
    slot_index: dict[str, int] = {}
    for face in valid:
        if face.texture and face.texture not in slot_index:
            slot_index[face.texture] = len(slot_index)
            mat = materials.get(face.texture)
            if mat is not None:
                obj.data.materials.append(mat)
            else:
                obj.data.materials.append(bpy.data.materials.new(face.texture))
                slot_index[face.texture] = len(obj.data.materials) - 1

    uv_layer = bm.loops.layers.uv.new("UVMap")
    for face in valid:
        bm_verts = [bm.verts.new((v.x * scale, v.y * scale, v.z * scale))
                    for v in face.vertices]
        try:
            bm_face = bm.faces.new(bm_verts)
        except ValueError:
            # Duplicate face — possible on coplanar brush parts; skip.
            continue
        if face.texture and face.texture in slot_index:
            bm_face.material_index = slot_index[face.texture]
        # UVs (Standard or Valve220 — see _project_uv below).
        # We need the original MapBrush texinfo, attached via face.metadata.
        if face.metadata and "tex" in face.metadata:
            tex: MapTexInfo = face.metadata["tex"]
            tex_size = face.metadata.get("tex_size", (64, 64))
            for loop, vert in zip(bm_face.loops, face.vertices):
                u, v = _project_uv(tex, vert, tex_size)
                loop[uv_layer].uv = (u, 1.0 - v)

    bm.normal_update()
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    return obj


def _project_uv(tex: MapTexInfo, p: Vec3, tex_size: tuple[int, int]) -> tuple[float, float]:
    """Project a world-space point to UV using either Valve220 or Standard math."""
    w, h = tex_size
    if tex.is_valve220 and tex.s_axis is not None and tex.t_axis is not None:
        u = (p.dot(tex.s_axis) / max(tex.xscale, 1e-6) + tex.s_offset) / max(w, 1)
        v = (p.dot(tex.t_axis) / max(tex.yscale, 1e-6) + tex.t_offset) / max(h, 1)
        return u, v
    # Standard projection: pick the dominant axis of the face normal and
    # use the corresponding planar projection. We don't have the normal here
    # (the caller could pass it via metadata) — approximate via world axes.
    # This is the textbook reference projection from idTech.
    # Choose s/t axes per the face's dominant normal.
    # Without the normal we assume X-Y plane (most common for flat surfaces).
    # The full per-axis selector lives in :mod:`quakeblend.formats.csg` callers.
    s_axis = Vec3(1, 0, 0)
    t_axis = Vec3(0, -1, 0)
    if "axis" in (getattr(tex, "_meta", None) or {}):
        s_axis, t_axis = tex._meta["axis"]  # type: ignore[attr-defined]
    cos_r = math.cos(math.radians(tex.rotation))
    sin_r = math.sin(math.radians(tex.rotation))
    s = p.dot(s_axis)
    t = p.dot(t_axis)
    # Apply rotation around (0,0).
    sr = s * cos_r - t * sin_r
    tr = s * sin_r + t * cos_r
    u = (sr / max(tex.xscale, 1e-6) + tex.xoffset) / max(w, 1)
    v = (tr / max(tex.yscale, 1e-6) + tex.yoffset) / max(h, 1)
    return u, v


# --------------------------------------------------------------- BSP faces


def build_bsp_geometry(name: str, vertices: Sequence[Vec3],
                       face_polygons: Iterable[Sequence[int]],
                       face_materials: Iterable[int],
                       face_uvs: Iterable[Sequence[tuple[float, float]]],
                       collection: bpy.types.Collection,
                       material_list: Sequence[bpy.types.Material],
                       *, scale: float) -> bpy.types.Object:
    """Build a single mesh from BSP-style face data."""
    obj = _new_mesh_object(name, collection)
    for mat in material_list:
        obj.data.materials.append(mat)

    bm = bmesh.new()
    bm_verts = [bm.verts.new((v.x * scale, v.y * scale, v.z * scale)) for v in vertices]
    bm.verts.ensure_lookup_table()

    uv_layer = bm.loops.layers.uv.new("UVMap")

    polys = list(face_polygons)
    mats = list(face_materials)
    uvs = list(face_uvs)
    for poly_indices, mat_idx, poly_uvs in zip(polys, mats, uvs):
        if len(poly_indices) < 3:
            continue
        try:
            face = bm.faces.new([bm_verts[i] for i in poly_indices])
        except ValueError:
            continue
        if 0 <= mat_idx < len(material_list):
            face.material_index = mat_idx
        for loop, uv in zip(face.loops, poly_uvs):
            loop[uv_layer].uv = uv

    bm.normal_update()
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    return obj
