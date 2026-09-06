"""Runner for the MAP import operator (Quake 1 standard / Valve220)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

import bpy

from ..formats import (
    brushdef3 as brushdef3_mod, map_q1, palette as palette_mod, patch as patch_mod,
    wad as wad_mod, wal as wal_mod,
)
from ..formats.csg import BrushFace, brush_faces
from ..utils.constants import CAMERA_ENTITY_CLASSNAMES
from ..utils import log as qb_log, paths as qb_paths
from ..utils.import_options import classify_tool_brush, is_trigger
from ..utils.map_resources import MapResources
from ..utils.q3_assets import Q3Assets
from .import_options import ImportState
from . import builder_entities, builder_geometry, builder_materials, builder_q3_materials, map_scene_export
from .prefs import get_prefs


def _load_wad_materials(wad_paths: list[Path], *, create_materials=True, sizes=None) -> builder_materials.MaterialCache:
    """Load all WAD textures from the supplied paths and build materials."""
    pal = palette_mod.load_bundled("q1")
    out = builder_materials.MaterialCache()
    for path in wad_paths:
        if not path.exists():
            continue
        archive = wad_mod.read_wad_path(path)
        for mt in archive.textures:
            if sizes is not None:
                sizes.setdefault(mt.name.casefold(), (mt.width, mt.height))
            if not create_materials:
                continue
            if mt.name in out:
                continue
            tex_pal = (
                palette_mod.from_bytes(mt.palette, fullbright=())
                if mt.palette else pal
            )
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
    builder_entities.tag_entity_properties(obj, properties)


def _tag_face_surface_flags(obj: bpy.types.Object, brush: map_q1.MapBrush) -> None:
    """Expose Quake 2 ``contents flags value`` face trailers on the object.

    The arrays are indexed by *source* face order (``brush.faces``), which is
    not the mesh polygon order -- CSG drops faces that clip away to nothing.
    ``qb_face_textures`` is written alongside so the rows stay interpretable;
    it is a newline-joined string because Blender ID properties cannot hold
    arrays of strings (``.map`` texture tokens never contain whitespace).
    """
    if not any(face.tex.has_q2_trailing_fields for face in brush.faces):
        return
    obj["qb_face_textures"] = "\n".join(face.tex.name for face in brush.faces)
    obj["qb_face_contents"] = [int(face.tex.contents) for face in brush.faces]
    obj["qb_face_flags"] = [int(face.tex.surface_flags) for face in brush.faces]
    obj["qb_face_value"] = [int(face.tex.value) for face in brush.faces]


def run(operator: bpy.types.Operator, context: bpy.types.Context, filepath: str) -> None:
    state = ImportState(operator, context)
    options = state.options
    scale = float(getattr(operator, "scale", 1.0 / 32.0))
    light_multiplier = float(getattr(operator, "light_energy", 1.0))
    wad_paths_str: str = getattr(operator, "wad_paths", "") or ""
    if not wad_paths_str.strip():
        try:
            wad_paths_str = (get_prefs(context).default_wad_path or "").strip()
        except (KeyError, AttributeError):
            wad_paths_str = ""
    wad_paths = [Path(p) for p in wad_paths_str.split(";") if p.strip()]
    texture_root = _resolve_texture_root(operator, context)
    map_path = Path(filepath)

    source_bytes = map_path.read_bytes()
    mf = map_q1.parse(source_bytes.decode("latin-1"))
    requested_game = str(getattr(operator, "source_game", "AUTO")).lower()
    source_game = (
        map_q1.detect_game(mf)
        if requested_game == "auto"
        else requested_game
    )
    if source_game not in ("q1", "q2", "q3"):
        raise ValueError(f"unsupported MAP source game {source_game!r}")
    if options.worldspawn_only and (not mf.entities or mf.entities[0].properties.get("classname", "").casefold() != "worldspawn"):
        raise ValueError("Worldspawn Only requires the first MAP entity to be worldspawn")
    shader_mode = source_game == "q3" and getattr(operator, "q3_material_mode", "SHADERS") == "SHADERS"
    q3_materials = (builder_q3_materials.Q3Materials(texture_root, context.scene,
        source_key=hashlib.sha256(source_bytes).hexdigest(), scale=scale, **options.shader_kwargs())
        if shader_mode and options.create_materials else None)
    sizes = {}
    materials = builder_materials.MaterialCache() if shader_mode else _load_wad_materials(
        wad_paths, create_materials=options.create_materials, sizes=sizes)
    q3_assets = q3_materials.assets if q3_materials else (
        Q3Assets.from_folder(texture_root) if source_game == "q3" and texture_root else Q3Assets({}))
    texture_index = (
        qb_paths.TextureRootIndex(texture_root)
        if texture_root is not None
        else None
    )
    # An explicit override pins the on-disk texture flavour; an auto-detected
    # game may be wrong (a Q3 map with no Q3-specific syntax parses as Q1), so
    # probe both .wal and image files in that case.
    external_texture_kind = (
        None
        if requested_game == "auto"
        else {"q2": "wal", "q3": "image"}.get(source_game)
    )
    q2_palette = palette_mod.load_bundled("q2") if texture_root is not None else None
    resources = MapResources(texture_index, source_game, external_texture_kind,
        sizes=sizes, q3_assets=q3_assets, shader_mode=shader_mode, warn=state.warn)

    scene = context.scene
    root = bpy.data.collections.new(map_path.stem)
    scene.collection.children.link(root)

    # Cache the source path + detected game so the export operator can later
    # re-parse the original file as its source of truth.
    root["qb_source_map"] = str(map_path.resolve())
    root["qb_source_game"] = source_game
    root["qb_import_scale"] = scale
    root["qb_map_import_id"] = uuid4().hex
    root["qb_source_sha256"] = hashlib.sha256(source_bytes).hexdigest()
    root["qb_transform_scale"] = scale
    root["qb_transform_baselines"] = {}
    root["qb_omitted_brushes"] = {}
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
        entity_categories = {"trigger"} if is_trigger(entity.properties) else set()
        if (options.worldspawn_only and ent_idx != 0) or options.disposition(entity_categories) == "SKIP":
            for brush_idx in range(len(entity.brushes)):
                root["qb_omitted_brushes"][f"{ent_idx}:{brush_idx}"] = "Entity excluded"
            if entity_categories and not options.worldspawn_only:
                state.counts["skipped"] += (len(entity.brushes) if options.import_brush_entities else 0) + int(options.import_entities)
            continue
        ent_coll = state.collection(root, f"{ent_idx:04d}_{classname}")

        for brush_idx, brush in enumerate(entity.brushes):
            if ent_idx != 0 and not options.import_brush_entities:
                root["qb_omitted_brushes"][f"{ent_idx}:{brush_idx}"] = "Brush entities excluded"
                continue
            if brush.raw_kind in ("brushDef3", "brushDef"):
                try:
                    brush = brushdef3_mod.to_standard_brush(brush)
                except (ValueError, StopIteration) as exc:
                    state.warn(f"Skipping {brush.raw_kind} brush in entity {ent_idx}: {exc}")
                    continue
            if brush.raw_kind == "patchDef2":
                try:
                    texture_name, _ = patch_mod.parse_patch_def2_block(brush.raw_payload)
                    surfaces = [resources.surface(map_q1.TexInfo(texture_name))]
                except ValueError as exc:
                    state.warn(f"Skipping patch in entity {ent_idx}: {exc}")
                    continue
            else:
                surfaces = [resources.surface(face.tex) for face in brush.faces]
            categories, diagnostic = classify_tool_brush(surfaces, source_game)
            categories = categories | entity_categories
            if diagnostic:
                state.warn(f"Entity {ent_idx} brush {brush_idx}: {diagnostic}")
            if options.disposition(categories) == "SKIP":
                root["qb_omitted_brushes"][f"{ent_idx}:{brush_idx}"] = ",".join(sorted(categories))
                state.counts["skipped"] += 1
                continue
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
                    q3_materials=q3_materials,
                    create_materials=options.create_materials,
                )
                if patch_obj is not None:
                    patch_obj["qb_owner_entity_index"] = ent_idx
                    patch_obj["qb_brush_index"] = brush_idx
                    state.mark(patch_obj, categories)
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
                if options.create_materials and tex_name not in materials and q3_materials is not None:
                    materials.add(tex_name, q3_materials.get(tex_name))
                elif options.create_materials and tex_name not in materials and texture_index is not None:
                    info = texture_index.resolve(
                        tex_name,
                        kind=external_texture_kind,
                    )
                    if info is not None:
                        mat = _material_for_external(operator, tex_name, info, q2_palette)
                        if mat is not None:
                            materials.add(tex_name, mat)
                tex_size = resources.dimensions(tex_name)
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
                ent_coll, materials, scale=scale, create_materials=options.create_materials,
            )
            if obj is not None:
                obj["qb_owner_entity_index"] = ent_idx
                obj["qb_brush_index"] = brush_idx
                _tag_face_surface_flags(obj, brush)
                map_scene_export.capture_brush(root, obj)
                state.mark(obj, categories)
                if q3_materials:
                    q3_materials.apply(obj)

        if options.import_entities and not options.worldspawn_only:
            if (not getattr(operator, "import_lights", True)
                    and classname.startswith("light")):
                continue
            if (not getattr(operator, "import_cameras", True)
                    and classname in CAMERA_ENTITY_CLASSNAMES):
                continue
            built = builder_entities.build_entity(
                entity.properties,
                ent_coll,
                scale=scale,
                light_multiplier=light_multiplier,
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
            state.mark(built, entity_categories)


    if q3_materials:
        root["qb_q3_material_mode"] = "SHADERS"
        for name, diagnostic in q3_materials.diagnostics.items():
            qb_log.report(operator, {"WARNING"}, f"Q3 shader {name}: {diagnostic}")
    state.finish(root)


def _build_patch(operator, brush, collection, name: str,
                 materials: builder_materials.MaterialCache,
                 texture_index: qb_paths.TextureRootIndex | None,
                 external_texture_kind: str | None,
                 q2_palette: palette_mod.Palette | None,
                 *, scale: float, q3_materials=None, create_materials=True) -> bpy.types.Object | None:
    try:
        tex_name, p = patch_mod.parse_patch_def2_block(brush.raw_payload)
        tess = patch_mod.tessellate(p, level=int(getattr(operator, "patch_level", 5)))
    except ValueError as exc:
        qb_log.report(operator, {"WARNING"}, f"Skipping patch {name}: {exc}")
        return None

    material = materials.get(tex_name)
    if create_materials and material is None and q3_materials is not None:
        material = q3_materials.get(tex_name)
        materials.add(tex_name, material)
    elif create_materials and material is None and texture_index is not None:
        info = texture_index.resolve(tex_name, kind=external_texture_kind)
        if info is not None and q2_palette is not None:
            material = _material_for_external(operator, tex_name, info, q2_palette)
            if material is not None:
                materials.add(tex_name, material)
    if create_materials and material is None:
        material = builder_materials.get_or_create_placeholder_material(
            tex_name,
            asset_key=f"placeholder|map|{tex_name.casefold()}",
        )

    mesh = bpy.data.meshes.new(name)
    verts = [(v.x * scale, v.y * scale, v.z * scale) for v in tess.vertices]
    faces = [list(q) for q in tess.quads]
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    if create_materials:
        mesh.materials.append(material)
    if mesh.uv_layers:
        uv_layer = mesh.uv_layers.active.data
    else:
        uv_layer = mesh.uv_layers.new().data
    li = 0
    for q in faces:
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
    if q3_materials:
        q3_materials.apply(obj)
    return obj
