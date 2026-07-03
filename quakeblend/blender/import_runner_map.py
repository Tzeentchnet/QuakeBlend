"""Runner for the MAP import operator (Quake 1 standard / Valve220)."""

from __future__ import annotations

from pathlib import Path

import bpy

from ..formats import (
    brushdef3 as brushdef3_mod, map_q1, palette as palette_mod, patch as patch_mod,
    wad as wad_mod, wal as wal_mod,
)
from ..formats.csg import BrushFace, brush_faces
from ..utils import log as qb_log, paths as qb_paths
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


def _resolve_texture_root(operator: bpy.types.Operator,
                          context: bpy.types.Context) -> Path | None:
    """Use the operator's texture_root if set, else the addon preference."""
    raw = (getattr(operator, "texture_root", "") or "").strip()
    if not raw:
        try:
            raw = (get_prefs(context).default_texture_root or "").strip()
        except (KeyError, AttributeError):
            raw = ""
    return Path(raw) if raw else None


_Q3_TEXTURE_EXTS = (".tga", ".jpg", ".jpeg", ".png")


def _resolve_external_texture(texture_root: Path, name: str) -> tuple[Path, str] | None:
    """Find an external texture under ``texture_root``.

    Returns ``(path, kind)`` where ``kind`` is ``"wal"`` or ``"image"``, or ``None``.
    Searches both directly under the root and under a ``textures/`` subfolder, and
    falls back to a case-insensitive recursive walk.
    """
    # Direct WAL candidates (Quake 2). ``name`` comes from the untrusted map
    # file, so join it via ``safe_join_under_root`` to reject any attempt to
    # escape ``texture_root`` via absolute paths or ``..`` segments.
    wal_candidates = [
        qb_paths.safe_join_under_root(texture_root, f"{name}.wal"),
        qb_paths.safe_join_under_root(texture_root, "textures", f"{name}.wal"),
    ]
    for cand in wal_candidates:
        if cand is not None and cand.exists():
            return cand, "wal"
    # Direct image candidates (Quake 3).
    base = qb_paths.safe_join_under_root(texture_root, name)
    if base is not None:
        for ext in _Q3_TEXTURE_EXTS:
            cand = base.with_suffix(ext)
            if cand.exists():
                return cand, "image"
        if base.exists() and base.suffix.lower() in _Q3_TEXTURE_EXTS:
            return base, "image"
    # Case-insensitive walk fallback for WAL (already contained under root
    # because rglob only yields real paths beneath texture_root).
    needle = (name + ".wal").lower().replace("\\", "/")
    if texture_root.exists():
        for path in texture_root.rglob("*.wal"):
            try:
                rel = str(path.relative_to(texture_root)).lower().replace("\\", "/")
            except ValueError:
                continue
            if rel.endswith(needle) or rel == needle:
                return path, "wal"
    return None


def _material_for_external(operator: bpy.types.Operator,
                           name: str,
                           info: tuple[Path, str],
                           q2_palette: palette_mod.Palette) -> bpy.types.Material | None:
    path, kind = info
    if kind == "wal":
        try:
            wal = wal_mod.read_wal_path(path)
        except (OSError, ValueError):
            return None
        return builder_materials.material_from_wal(wal, q2_palette)
    # image (Q3-style)
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    output = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = 1.0
    nt.links.new(bsdf.outputs[0], output.inputs[0])
    try:
        img = bpy.data.images.load(str(path), check_existing=True)
        tex_node = nt.nodes.new("ShaderNodeTexImage")
        tex_node.image = img
        tex_node.interpolation = "Closest"
        nt.links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])
    except RuntimeError as exc:
        qb_log.report(
            operator,
            {"WARNING"},
            f"Failed to load texture image '{name}' from '{path}': {exc}",
        )
    return mat


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
    texture_root = _resolve_texture_root(operator, context)
    q2_palette = palette_mod.load_bundled("q2") if texture_root is not None else None
    map_path = Path(filepath)

    mf = map_q1.parse_path(map_path)

    scene = context.scene
    root = bpy.data.collections.new(map_path.stem)
    scene.collection.children.link(root)

    # Cache the source path + detected game so the export operator can later
    # re-parse the original file as its source of truth.
    root["qb_source_map"] = str(map_path.resolve())
    name_lower = map_path.name.lower()
    if "q3" in name_lower or "quake3" in name_lower:
        source_game = "q3"
    elif "q2" in name_lower or "quake2" in name_lower:
        source_game = "q2"
    else:
        source_game = "q1"
    # Also derive from brush content (presence of brushDef3/patchDef2 ⇒ q3).
    if any(b.raw_kind in ("brushDef3", "brushDef", "patchDef2", "patchDef3")
           for ent in mf.entities for b in ent.brushes):
        source_game = "q3"
    root["qb_source_game"] = source_game
    root["qb_source_projection"] = (
        "valve220" if any(face.tex.is_valve220
                          for ent in mf.entities for b in ent.brushes
                          for face in b.faces)
        else "standard"
    )

    for ent_idx, entity in enumerate(mf.entities):
        classname = entity.properties.get("classname", f"entity_{ent_idx}")
        ent_coll = bpy.data.collections.new(f"{ent_idx:04d}_{classname}")
        root.children.link(ent_coll)

        for brush_idx, brush in enumerate(entity.brushes):
            if brush.raw_kind == "patchDef2":
                _build_patch(operator, brush, ent_coll,
                             f"{classname}_patch_{brush_idx}", scale=scale)
                continue
            if brush.raw_kind in ("brushDef3", "brushDef"):
                try:
                    brush = brushdef3_mod.to_standard_brush(brush)
                except (ValueError, StopIteration) as exc:
                    operator.report({"WARNING"},
                                    f"Skipping {brush.raw_kind} brush in entity "
                                    f"{ent_idx}: {exc}")
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
                tex_name = src.tex.name
                # On-demand external texture resolution (Q2 WAL / Q3 image).
                if tex_name not in materials and texture_root is not None:
                    info = _resolve_external_texture(texture_root, tex_name)
                    if info is not None:
                        mat = _material_for_external(operator, tex_name, info, q2_palette)
                        if mat is not None:
                            materials[tex_name] = mat
                tex_size = (64, 64)
                mat = materials.get(tex_name)
                if mat is not None and mat.node_tree is not None:
                    for node in mat.node_tree.nodes:
                        if node.type == "TEX_IMAGE" and node.image is not None:
                            tex_size = (node.image.size[0], node.image.size[1])
                            break
                enriched.append(BrushFace(
                    plane=csg.plane,
                    vertices=csg.vertices,
                    texture=csg.texture,
                    metadata={
                        "tex": src.tex,
                        "tex_size": tex_size,
                        "normal": src.plane.normal,
                    },
                ))
            obj = builder_geometry.build_map_brush(
                brush, enriched, f"{classname}_brush_{brush_idx}",
                ent_coll, materials, scale=scale,
            )
            if obj is not None:
                obj["qb_entity_index"] = ent_idx
                obj["qb_brush_index"] = brush_idx

        if getattr(operator, "import_entities", True):
            if (not getattr(operator, "import_lights", True)
                    and classname.startswith("light")):
                continue
            built = builder_entities.build_entity(
                entity.properties,
                ent_coll,
                scale=scale,
                operator=operator,
            )
            if built is None and not entity.brushes:
                # Entities with no origin and no brushes — drop a marker empty.
                empty = bpy.data.objects.new(classname, None)
                empty.empty_display_type = "SPHERE"
                ent_coll.objects.link(empty)


def _build_patch(operator, brush, collection, name: str, scale: float) -> None:
    try:
        tex_name, p = patch_mod.parse_patch_def2_block(brush.raw_payload)
        tess = patch_mod.tessellate(p, level=int(getattr(operator, "patch_level", 5)))
    except Exception as exc:
        qb_log.report(operator, {"WARNING"}, f"Skipping patch {name}: {exc}")
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