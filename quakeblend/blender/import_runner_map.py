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
            source_key = qb_paths.file_asset_key(
                path,
                namespace="wad",
                member=mt.name,
            )
            mat = builder_materials.material_from_miptex(
                mt,
                tex_pal,
                source_key=source_key,
            )
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


def _material_for_external(operator: bpy.types.Operator,
                           name: str,
                           info: tuple[Path, str],
                           q2_palette: palette_mod.Palette) -> bpy.types.Material | None:
    path, kind = info
    if kind == "wal":
        try:
            source_key = qb_paths.file_asset_key(path, namespace="wal", member=name)
            wal = wal_mod.read_wal_path(path)
            return builder_materials.material_from_wal(
                wal,
                q2_palette,
                source_key=source_key,
            )
        except (OSError, ValueError) as exc:
            qb_log.report(
                operator,
                {"WARNING"},
                f"Failed to load WAL texture '{name}' from '{path}': {exc}",
            )
            return builder_materials.get_or_create_placeholder_material(
                name,
                asset_key=(
                    f"placeholder|wal-load-failed|{path.as_posix().casefold()}|"
                    f"{name.casefold()}"
                ),
            )
    try:
        source_key = qb_paths.file_asset_key(path, namespace="q3-image", member=name)
        return builder_materials.material_from_external_image(
            name,
            path,
            source_key=source_key,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        qb_log.report(
            operator,
            {"WARNING"},
            f"Failed to load texture image '{name}' from '{path}': {exc}",
        )
        return builder_materials.get_or_create_placeholder_material(
            name,
            asset_key=(
                f"placeholder|q3-load-failed|{path.as_posix().casefold()}|"
                f"{name.casefold()}"
            ),
        )


def _tag_entity_anchor(obj: bpy.types.Object,
                       properties: dict[str, str],
                       entity_index: int,
                       *, has_valid_origin: bool) -> None:
    obj["qb_entity_role"] = "ENTITY"
    obj["qb_entity_index"] = entity_index
    obj["qb_entity_has_origin"] = has_valid_origin
    for key, value in properties.items():
        try:
            obj[f"qb_prop_{key}"] = value
        except (TypeError, KeyError):
            continue


def run(operator: bpy.types.Operator, context: bpy.types.Context, filepath: str) -> None:
    scale = float(getattr(operator, "scale", 1.0 / 32.0))
    wad_paths_str: str = getattr(operator, "wad_paths", "") or ""
    if not wad_paths_str.strip():
        try:
            wad_paths_str = (get_prefs(context).default_wad_path or "").strip()
        except (KeyError, AttributeError):
            wad_paths_str = ""
    wad_paths = [Path(p) for p in wad_paths_str.split(";") if p.strip()]
    texture_root = _resolve_texture_root(operator, context)
    map_path = Path(filepath)

    mf = map_q1.parse_path(map_path)
    requested_game = str(getattr(operator, "source_game", "AUTO")).lower()
    source_game = (
        map_q1.detect_game(mf)
        if requested_game == "auto"
        else requested_game
    )
    if source_game not in ("q1", "q2", "q3"):
        raise ValueError(f"unsupported MAP source game {source_game!r}")
    materials = _load_wad_materials(wad_paths)
    texture_index = (
        qb_paths.TextureRootIndex(texture_root)
        if texture_root is not None
        else None
    )
    external_texture_kind = {"q2": "wal", "q3": "image"}.get(source_game)
    q2_palette = palette_mod.load_bundled("q2") if texture_root is not None else None

    scene = context.scene
    root = bpy.data.collections.new(map_path.stem)
    scene.collection.children.link(root)

    # Cache the source path + detected game so the export operator can later
    # re-parse the original file as its source of truth.
    root["qb_source_map"] = str(map_path.resolve())
    root["qb_source_game"] = source_game
    root["qb_import_scale"] = scale
    projections = {
        "valve220" if face.tex.is_valve220 else "standard"
        for ent in mf.entities
        for brush in ent.brushes
        for face in brush.faces
    }
    root["qb_source_projection"] = (
        next(iter(projections)) if len(projections) == 1 else "mixed"
    )

    for ent_idx, entity in enumerate(mf.entities):
        classname = entity.properties.get("classname", f"entity_{ent_idx}")
        ent_coll = bpy.data.collections.new(f"{ent_idx:04d}_{classname}")
        root.children.link(ent_coll)

        for brush_idx, brush in enumerate(entity.brushes):
            if brush.raw_kind == "patchDef2":
                patch_obj = _build_patch(
                    operator,
                    brush,
                    ent_coll,
                    f"{classname}_patch_{brush_idx}",
                    materials,
                    texture_index,
                    external_texture_kind,
                    q2_palette,
                    scale=scale,
                )
                if patch_obj is not None:
                    patch_obj["qb_owner_entity_index"] = ent_idx
                    patch_obj["qb_brush_index"] = brush_idx
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
                if tex_name not in materials and texture_index is not None:
                    info = texture_index.resolve(
                        tex_name,
                        kind=external_texture_kind,
                    )
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
                obj["qb_owner_entity_index"] = ent_idx
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
            has_valid_origin = built is not None and bool(entity.properties.get("origin"))
            if built is None:
                empty = bpy.data.objects.new(classname, None)
                empty.empty_display_type = "SPHERE"
                ent_coll.objects.link(empty)
                built = empty
            _tag_entity_anchor(
                built,
                entity.properties,
                ent_idx,
                has_valid_origin=has_valid_origin,
            )


def _build_patch(operator, brush, collection, name: str,
                 materials: dict[str, bpy.types.Material],
                 texture_index: qb_paths.TextureRootIndex | None,
                 external_texture_kind: str | None,
                 q2_palette: palette_mod.Palette | None,
                 *, scale: float) -> bpy.types.Object | None:
    try:
        tex_name, p = patch_mod.parse_patch_def2_block(brush.raw_payload)
        tess = patch_mod.tessellate(p, level=int(getattr(operator, "patch_level", 5)))
    except Exception as exc:
        qb_log.report(operator, {"WARNING"}, f"Skipping patch {name}: {exc}")
        return None

    material = materials.get(tex_name)
    if material is None and texture_index is not None:
        info = texture_index.resolve(tex_name, kind=external_texture_kind)
        if info is not None and q2_palette is not None:
            material = _material_for_external(operator, tex_name, info, q2_palette)
            if material is not None:
                materials[tex_name] = material
    if material is None:
        material = builder_materials.get_or_create_placeholder_material(
            tex_name,
            asset_key=f"placeholder|map|{tex_name.casefold()}",
        )

    mesh = bpy.data.meshes.new(name)
    verts = [(v.x * scale, v.y * scale, v.z * scale) for v in tess.vertices]
    faces = [list(q) for q in tess.quads]
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    mesh.materials.append(material)
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
    return obj