"""Runner for the MAP import operator (Quake 1 standard / Valve220)."""

from __future__ import annotations

from pathlib import Path

import bpy

from ..formats import map_q1, palette as palette_mod, patch as patch_mod, wad as wad_mod
from ..formats.csg import BrushFace, brush_faces
from . import builder_entities, builder_geometry, builder_materials
from .prefs import get_prefs


def _load_wad_materials(wad_paths: list[Path]) -> dict[str, bpy.types.Material]:
    """Load all WAD textures from the supplied paths and build materials."""
    pal = palette_mod.load_bundled("q1")
    out: dict[str, bpy.types.Material] = {}
    for path in wad_paths:
        if not path.exists():
            continue
        archive = wad_mod.read_wad_path(path)
        for mt in archive.textures:
            tex_pal = palette_mod.from_bytes(mt.palette) if mt.palette else pal
            mat = builder_materials.material_from_miptex(mt, tex_pal)
            out.setdefault(mt.name, mat)
    return out


def run(operator: bpy.types.Operator, context: bpy.types.Context, filepath: str) -> None:
    scale = float(getattr(operator, "scale", 1.0 / 32.0))
    wad_paths_str: str = getattr(operator, "wad_paths", "") or ""
    if not wad_paths_str.strip():
        try:
            wad_paths_str = (get_prefs(context).default_wad_path or "").strip()
        except (KeyError, AttributeError):
            wad_paths_str = ""
    wad_paths = [Path(p) for p in wad_paths_str.split(";") if p.strip()]
    materials = _load_wad_materials(wad_paths)
    map_path = Path(filepath)

    mf = map_q1.parse_path(map_path)

    scene = context.scene
    root = bpy.data.collections.new(map_path.stem)
    scene.collection.children.link(root)

    for ent_idx, entity in enumerate(mf.entities):
        classname = entity.properties.get("classname", f"entity_{ent_idx}")
        ent_coll = bpy.data.collections.new(f"{ent_idx:04d}_{classname}")
        root.children.link(ent_coll)

        for brush_idx, brush in enumerate(entity.brushes):
            if brush.raw_kind == "patchDef2":
                _build_patch(operator, brush, ent_coll,
                             f"{classname}_patch_{brush_idx}", scale=scale)
                continue
            if brush.raw_kind != "standard":
                operator.report({"WARNING"},
                                f"Skipping {brush.raw_kind} brush in entity {ent_idx} "
                                "(supported in a later phase)")
                continue
            planes = [face.plane for face in brush.faces]
            face_textures = [face.tex.name for face in brush.faces]
            csg_faces = brush_faces(planes, face_textures)
            # Attach metadata so the geometry builder can compute UVs.
            enriched: list[BrushFace] = []
            for csg, src in zip(csg_faces, brush.faces):
                tex_size = (64, 64)
                mat = materials.get(src.tex.name)
                if mat is not None and mat.node_tree is not None:
                    for node in mat.node_tree.nodes:
                        if node.type == "TEX_IMAGE" and node.image is not None:
                            tex_size = (node.image.size[0], node.image.size[1])
                            break
                enriched.append(BrushFace(
                    plane=csg.plane,
                    vertices=csg.vertices,
                    texture=csg.texture,
                    metadata={"tex": src.tex, "tex_size": tex_size},
                ))
            obj = builder_geometry.build_map_brush(
                brush, enriched, f"{classname}_brush_{brush_idx}",
                ent_coll, materials, scale=scale,
            )
            if obj is not None:
                obj["qb_entity_index"] = ent_idx
                obj["qb_brush_index"] = brush_idx

        if getattr(operator, "import_entities", True):
            built = builder_entities.build_entity(entity.properties, ent_coll, scale=scale)
            if built is None and not entity.brushes:
                # Entities with no origin and no brushes — drop a marker empty.
                empty = bpy.data.objects.new(classname, None)
                empty.empty_display_type = "SPHERE"
                ent_coll.objects.link(empty)


def _build_patch(operator, brush, collection, name: str, scale: float) -> None:
    try:
        tex_name, p = patch_mod.parse_patch_def2_block(brush.raw_payload)
        tess = patch_mod.tessellate(p, level=int(getattr(operator, "patch_level", 5)))
    except (ValueError, StopIteration) as exc:
        operator.report({"WARNING"}, f"Skipping patch {name}: {exc}")
        return

    mesh = bpy.data.meshes.new(name)
    verts = [(v.x * scale, v.y * scale, v.z * scale) for v in tess.vertices]
    faces = [list(q) for q in tess.quads]
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    if mesh.uv_layers:
        uv_layer = mesh.uv_layers.active.data
    else:
        uv_layer = mesh.uv_layers.new().data
    li = 0
    for q, idx_quad in zip(faces, tess.quads):
        for vert_idx in q:
            u, v = tess.uvs[vert_idx]
            uv_layer[li].uv = (u, 1.0 - v)
            li += 1

    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj["qb_patch_texture"] = tex_name
    obj["qb_patch_size"] = [p.width, p.height]
    obj["qb_patch_control_grid"] = [
        [c.pos.x, c.pos.y, c.pos.z, c.uv[0], c.uv[1]] for c in p.controls
    ]