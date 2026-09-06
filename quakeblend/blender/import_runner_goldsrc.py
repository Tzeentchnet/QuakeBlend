"""GoldSrc BSP import with source-scoped materials and brush origins."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import bpy

from ..formats import bsp_goldsrc, palette, wad
from ..formats.entities import parse_origin
from ..utils import log as qb_log, paths as qb_paths
from . import builder_materials, import_runner_bsp, map_assembly
from .prefs import get_prefs
from .import_options import ImportState


def _wad_textures(operator: bpy.types.Operator, context: bpy.types.Context,
                  ) -> dict[str, tuple[wad.MipTexture, Path]]:
    raw = (getattr(operator, "wad_paths", "") or "").strip()
    if not raw:
        preferences = get_prefs(context)
        raw = preferences.default_wad_path if preferences is not None else ""
    textures: dict[str, tuple[wad.MipTexture, Path]] = {}
    for token in raw.split(";"):
        if not token.strip():
            continue
        path = Path(token.strip())
        try:
            archive = wad.read_wad_path(path)
            if archive.flavour != "WAD3":
                raise ValueError("GoldSrc requires a WAD3 archive")
        except (OSError, ValueError, EOFError) as exc:
            qb_log.report(operator, {"WARNING"}, f"Skipping GoldSrc WAD '{path}': {exc}")
            continue
        for texture in archive.textures:
            if texture.palette is None:
                qb_log.report(operator, {"WARNING"},
                              f"Skipping WAD3 texture '{texture.name}' without a valid palette")
                continue
            textures.setdefault(texture.name.casefold(), (texture, path))
    return textures


def _materials(operator: bpy.types.Operator, context: bpy.types.Context,
                bsp: bsp_goldsrc.Bsp, source: Path,
                ) -> dict[int, bpy.types.Material]:
    external_needed = any(texture is not None and index not in bsp.embedded_textures
                          for index, texture in enumerate(bsp.miptextures))
    wad_textures = _wad_textures(operator, context) if external_needed else {}
    texture_root = import_runner_bsp._resolve_texture_root(operator, context)
    image_index = (qb_paths.TextureRootIndex(texture_root)
                   if texture_root is not None and external_needed else None)
    materials: dict[int, bpy.types.Material] = {}
    for index, reference in enumerate(bsp.miptextures):
        if reference is None:
            continue
        texture = bsp.embedded_textures.get(index)
        texture_source = source
        namespace = "goldsrc-bsp"
        if texture is None and reference.name.casefold() in wad_textures:
            texture, texture_source = wad_textures[reference.name.casefold()]
            namespace = "goldsrc-wad"
        if texture is not None:
            source_key = qb_paths.file_asset_key(texture_source, namespace=namespace,
                                                  member=reference.name)
            if namespace == "goldsrc-bsp":
                source_key += f"|{index}"
            materials[index] = builder_materials.material_from_miptex(
                texture, palette.from_bytes(texture.palette, fullbright=()),
                source_key=source_key,
            )
            continue
        image_info = image_index.resolve(reference.name, kind="image") if image_index is not None else None
        if image_info is not None:
            image_path, _ = image_info
            source_key = qb_paths.file_asset_key(image_path, namespace="goldsrc-image",
                                                  member=reference.name)
            try:
                image = builder_materials.load_external_image(
                    reference.name, image_path, asset_key=f"{source_key}|image",
                )
                materials[index] = builder_materials.get_or_create_material(
                    reference.name, image,
                    flags=builder_materials.MaterialFlags(
                        texture_alpha=reference.name.startswith("{"),
                        sky=reference.name.casefold().startswith("sky"),
                    ),
                    asset_key=f"{source_key}|material",
                )
                continue
            except (OSError, ValueError, RuntimeError) as exc:
                qb_log.report(operator, {"WARNING"}, f"Failed GoldSrc texture '{reference.name}': {exc}")
        qb_log.report(operator, {"WARNING"}, f"Missing GoldSrc texture '{reference.name}'")
    return materials


def run(operator: bpy.types.Operator, context: bpy.types.Context, filepath: Path) -> None:
    state = ImportState(operator, context, bsp=True)
    bsp = bsp_goldsrc.read_path(filepath)
    scale = float(getattr(operator, "scale", 1.0 / 32.0))
    create_materials = bool(getattr(operator, "create_materials", True))
    materials = _materials(operator, context, bsp, filepath) if create_materials else {}
    material_list: list[bpy.types.Material] = []
    slots: dict[int, int] = {}
    records: list[tuple] = []
    model_of_face = import_runner_bsp._model_of_face(bsp.models, len(bsp.faces))
    for face_index, face in enumerate(bsp.faces):
        if model_of_face[face_index] != 0 and not getattr(operator, "import_brush_entities", True):
            continue
        polygon = bsp.face_polygon(face)
        if len(polygon) < 3:
            continue
        texture_index = bsp.texinfos[face.texinfo_id].miptex_index
        slot = -1
        if create_materials:
            if texture_index not in slots:
                material = materials.get(texture_index)
                if material is None:
                    source_key = qb_paths.file_asset_key(filepath, namespace="goldsrc-bsp",
                                                          member=f"missing:{texture_index}")
                    material = builder_materials.get_or_create_placeholder_material(
                        "Missing GoldSrc texture", asset_key=f"{source_key}|placeholder",
                    )
                slots[texture_index] = len(material_list)
                material_list.append(material)
            slot = slots[texture_index]
        records.append((face_index, polygon, slot,
                        import_runner_bsp._project_face_uvs(bsp, face, polygon)))

    root = bpy.data.collections.new(filepath.stem)
    context.scene.collection.children.link(root)
    root["qb_source_bsp"] = str(filepath.resolve())
    root["qb_source_game"] = "goldsrc"
    root["qb_import_scale"] = scale
    root["qb_import_id"] = uuid4().hex
    root["qb_map_name"] = filepath.stem.casefold()
    root["qb_bsp_entities"] = bsp.raw_entities
    geometry = state.collection(root, f"{filepath.stem}_Geometry")
    import_runner_bsp._build_submodel_objects(
        bsp.entities, bsp.models, records, bsp.vertices, material_list, geometry, filepath.stem,
        face_count=len(bsp.faces), scale=scale,
        state=state,
    )
    owners = import_runner_bsp._entities_by_model(bsp.entities)
    for obj in geometry.objects:
        owner = owners.get(obj["qb_bsp_model_index"])
        if owner is None:
            continue
        origin = parse_origin(owner.get("origin", "0 0 0"))
        obj.location = tuple(component * scale for component in origin)
        if owner.get("rendermode", "0") != "0" or owner.get("renderfx", "0") != "0":
            qb_log.report(operator, {"WARNING"},
                          f"GoldSrc {owner.get('classname', 'brush')}: render mode/effects retained as metadata only")
    import_runner_bsp._build_bsp_entities(operator, bsp.entities, root, filepath.stem,
                                         scale=scale, game="goldsrc", state=state)
    map_assembly.create_root(root)
    if getattr(operator, "stitch_goldsrc", False):
        map_assembly.stitch_import(operator, context, root)
    state.finish(root)
