"""Runner for the BSP import operator (Q1 v29 implemented in this phase)."""

from __future__ import annotations

import struct
from pathlib import Path

import bpy

from ..formats import bsp_q1, bsp_q2, bsp_q3, palette as palette_mod, patch as patch_mod, wal as wal_mod
from ..formats.common import Vec3
from ..utils.constants import BSP_VERSION_Q1, BSP_VERSION_Q2, BSP_VERSION_Q3, IBSP_MAGIC
from ..utils import log as qb_log, paths as qb_paths
from . import builder_entities, builder_geometry, builder_materials
from .prefs import get_prefs


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


def _detect_version(filepath: Path) -> tuple[str, int]:
    with open(filepath, "rb") as fh:
        head = fh.read(8)
    if len(head) < 4:
        raise ValueError("file too short to contain a BSP header")
    if head[:4] == IBSP_MAGIC:
        version = struct.unpack("<i", head[4:8])[0]
        if version == BSP_VERSION_Q2:
            return "q2", version
        if version == BSP_VERSION_Q3:
            return "q3", version
        raise ValueError(f"unsupported IBSP version {version}")
    version = struct.unpack("<i", head[:4])[0]
    if version == BSP_VERSION_Q1:
        return "q1", version
    raise ValueError(f"unrecognised BSP signature (first int = {version})")


def _build_q1_materials(bsp: bsp_q1.Bsp) -> dict[int, bpy.types.Material]:
    pal = palette_mod.load_bundled("q1")
    out: dict[int, bpy.types.Material] = {}
    for idx, mt in enumerate(bsp.miptextures):
        if mt is None:
            continue
        # Adapt to the wad miptex shape used by builder_materials.
        from ..formats.wad import MipTexture as WadMip
        mip = WadMip(name=mt.name, width=mt.width, height=mt.height,
                     pixels=mt.pixels, mip_pixels=(mt.pixels, b"", b"", b""),
                     palette=None)
        out[idx] = builder_materials.material_from_miptex(mip, pal)
    return out


def _project_face_uvs(bsp: bsp_q1.Bsp, face: bsp_q1.Face,
                      poly_indices: list[int]) -> list[tuple[float, float]]:
    if face.texinfo_id < 0 or face.texinfo_id >= len(bsp.texinfos):
        return [(0.0, 0.0)] * len(poly_indices)
    ti = bsp.texinfos[face.texinfo_id]
    mt = bsp.miptextures[ti.miptex_index] if 0 <= ti.miptex_index < len(bsp.miptextures) else None
    w = mt.width if mt is not None else 64
    h = mt.height if mt is not None else 64
    out: list[tuple[float, float]] = []
    for vi in poly_indices:
        v = bsp.vertices[vi]
        u = (v.dot(ti.s_axis) + ti.s_offset) / max(w, 1)
        t = (v.dot(ti.t_axis) + ti.t_offset) / max(h, 1)
        out.append((u, 1.0 - t))
    return out


def _import_q1(operator: bpy.types.Operator, context: bpy.types.Context,
               filepath: Path) -> None:
    scale = float(getattr(operator, "scale", 1.0 / 32.0))
    bsp = bsp_q1.read_path(filepath)
    materials_by_miptex = _build_q1_materials(bsp)

    # Build a flat material list + per-face material index.
    material_list: list[bpy.types.Material] = []
    miptex_to_slot: dict[int, int] = {}
    for idx, mat in materials_by_miptex.items():
        miptex_to_slot[idx] = len(material_list)
        material_list.append(mat)

    face_polygons: list[list[int]] = []
    face_mats: list[int] = []
    face_uvs: list[list[tuple[float, float]]] = []
    for face in bsp.faces:
        poly = bsp.face_polygon(face)
        if len(poly) < 3:
            continue
        face_polygons.append(poly)
        ti_idx = bsp.texinfos[face.texinfo_id].miptex_index if 0 <= face.texinfo_id < len(bsp.texinfos) else -1
        face_mats.append(miptex_to_slot.get(ti_idx, -1))
        face_uvs.append(_project_face_uvs(bsp, face, poly))

    scene = context.scene
    root = bpy.data.collections.new(filepath.stem)
    scene.collection.children.link(root)
    geom_coll = bpy.data.collections.new(f"{filepath.stem}_Geometry")
    root.children.link(geom_coll)

    builder_geometry.build_bsp_geometry(
        name=filepath.stem,
        vertices=bsp.vertices,
        face_polygons=face_polygons,
        face_materials=face_mats,
        face_uvs=face_uvs,
        collection=geom_coll,
        material_list=material_list,
        scale=scale,
    )

    if getattr(operator, "import_entities", True):
        ent_coll = bpy.data.collections.new(f"{filepath.stem}_Entities")
        root.children.link(ent_coll)
        for entity in bsp.entities:
            classname = entity.get("classname", "entity")
            if not getattr(operator, "import_lights", True) and classname.startswith("light"):
                continue
            builder_entities.build_entity(entity, ent_coll, scale=scale, operator=operator)


def run(operator: bpy.types.Operator, context: bpy.types.Context, filepath: str) -> None:
    path = Path(filepath)
    flavour, version = _detect_version(path)
    if flavour == "q1":
        _import_q1(operator, context, path)
        return
    if flavour == "q2":
        _import_q2(operator, context, path)
        return
    if flavour == "q3":
        _import_q3(operator, context, path)
        return
    raise NotImplementedError(
        f"BSP version {version} ({flavour}) import is implemented in a later phase"
    )


# ============================================================ Quake 2 ======


def _resolve_wal(texture_root: Path | None, texture_name: str) -> Path | None:
    if texture_root is None:
        return None
    # ``texture_name`` comes from the untrusted BSP file; reject any attempt
    # to escape ``texture_root`` via absolute paths or ``..`` segments.
    candidates = [
        qb_paths.safe_join_under_root(texture_root, f"{texture_name}.wal"),
        qb_paths.safe_join_under_root(texture_root, "textures", f"{texture_name}.wal"),
    ]
    for cand in candidates:
        if cand is not None and cand.exists():
            return cand
    # Case-insensitive walk fallback (already contained under root because
    # rglob only yields real paths beneath texture_root).
    needle = (texture_name + ".wal").lower().replace("\\", "/")
    if texture_root.exists():
        for path in texture_root.rglob("*.wal"):
            rel = str(path.relative_to(texture_root)).lower().replace("\\", "/")
            if rel.endswith(needle) or rel == needle:
                return path
    return None


def _build_q2_materials(bsp: bsp_q2.Bsp,
                        texture_root: Path | None) -> dict[str, bpy.types.Material]:
    pal = palette_mod.load_bundled("q2")
    out: dict[str, bpy.types.Material] = {}
    for ti in bsp.texinfos:
        if ti.texture_name in out:
            continue
        wal_path = _resolve_wal(texture_root, ti.texture_name)
        if wal_path is None:
            # Fallback: blank 64×64 magenta material so the slot index stays valid.
            placeholder = bpy.data.materials.get(ti.texture_name) or bpy.data.materials.new(
                ti.texture_name
            )
            out[ti.texture_name] = placeholder
            continue
        wal = wal_mod.read_wal_path(wal_path)
        out[ti.texture_name] = builder_materials.material_from_wal(wal, pal)
    return out


def _project_q2_face_uvs(bsp: bsp_q2.Bsp, face: bsp_q2.Face,
                         poly_indices: list[int],
                         texture_sizes: dict[str, tuple[int, int]]) -> list[tuple[float, float]]:
    if face.texinfo_id < 0 or face.texinfo_id >= len(bsp.texinfos):
        return [(0.0, 0.0)] * len(poly_indices)
    ti = bsp.texinfos[face.texinfo_id]
    w, h = texture_sizes.get(ti.texture_name, (64, 64))
    out: list[tuple[float, float]] = []
    for vi in poly_indices:
        v = bsp.vertices[vi]
        u = (v.dot(ti.u_axis) + ti.u_offset) / max(w, 1)
        t = (v.dot(ti.v_axis) + ti.v_offset) / max(h, 1)
        out.append((u, 1.0 - t))
    return out


def _import_q2(operator: bpy.types.Operator, context: bpy.types.Context,
               filepath: Path) -> None:
    scale = float(getattr(operator, "scale", 1.0 / 32.0))
    texture_root = _resolve_texture_root(operator, context)

    bsp = bsp_q2.read_path(filepath)
    materials_by_name = _build_q2_materials(bsp, texture_root)

    material_list: list[bpy.types.Material] = []
    name_to_slot: dict[str, int] = {}
    texture_sizes: dict[str, tuple[int, int]] = {}
    for name, mat in materials_by_name.items():
        name_to_slot[name] = len(material_list)
        material_list.append(mat)
        # Pick up image size from the material's first image texture node.
        size = (64, 64)
        if mat.use_nodes and mat.node_tree is not None:
            for node in mat.node_tree.nodes:
                if node.type == "TEX_IMAGE" and node.image is not None:
                    size = (node.image.size[0], node.image.size[1])
                    break
        texture_sizes[name] = size

    face_polygons: list[list[int]] = []
    face_mats: list[int] = []
    face_uvs: list[list[tuple[float, float]]] = []
    for face in bsp.faces:
        poly = bsp.face_polygon(face)
        if len(poly) < 3:
            continue
        face_polygons.append(poly)
        if 0 <= face.texinfo_id < len(bsp.texinfos):
            face_mats.append(name_to_slot.get(bsp.texinfos[face.texinfo_id].texture_name, -1))
        else:
            face_mats.append(-1)
        face_uvs.append(_project_q2_face_uvs(bsp, face, poly, texture_sizes))

    scene = context.scene
    root = bpy.data.collections.new(filepath.stem)
    scene.collection.children.link(root)
    geom_coll = bpy.data.collections.new(f"{filepath.stem}_Geometry")
    root.children.link(geom_coll)

    builder_geometry.build_bsp_geometry(
        name=filepath.stem,
        vertices=bsp.vertices,
        face_polygons=face_polygons,
        face_materials=face_mats,
        face_uvs=face_uvs,
        collection=geom_coll,
        material_list=material_list,
        scale=scale,
    )

    if getattr(operator, "import_entities", True):
        ent_coll = bpy.data.collections.new(f"{filepath.stem}_Entities")
        root.children.link(ent_coll)
        for entity in bsp.entities:
            classname = entity.get("classname", "entity")
            if not getattr(operator, "import_lights", True) and classname.startswith("light"):
                continue
            builder_entities.build_entity(entity, ent_coll, scale=scale, operator=operator)


# ============================================================ Quake 3 ======


_Q3_TEXTURE_EXTS = (".tga", ".jpg", ".jpeg", ".png")


def _resolve_q3_texture(texture_root: Path | None, name: str) -> Path | None:
    if texture_root is None:
        return None
    base = qb_paths.safe_join_under_root(texture_root, name)
    if base is None:
        return None
    for ext in _Q3_TEXTURE_EXTS:
        cand = base.with_suffix(ext)
        if cand.exists():
            return cand
    # Some BSPs already include the extension on the texture name.
    if base.exists() and base.suffix.lower() in _Q3_TEXTURE_EXTS:
        return base
    return None


def _build_q3_materials(operator: bpy.types.Operator,
                        bsp: bsp_q3.Bsp,
                        texture_root: Path | None) -> list[bpy.types.Material]:
    out: list[bpy.types.Material] = []
    for tex in bsp.textures:
        mat = bpy.data.materials.get(tex.name)
        if mat is None:
            mat = bpy.data.materials.new(tex.name)
            mat.use_nodes = True
            nt = mat.node_tree
            nt.nodes.clear()
            output = nt.nodes.new("ShaderNodeOutputMaterial")
            bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
            bsdf.inputs["Roughness"].default_value = 1.0
            nt.links.new(bsdf.outputs[0], output.inputs[0])

            path = _resolve_q3_texture(texture_root, tex.name)
            if path is not None:
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
                        f"Failed to load texture image '{tex.name}' from '{path}': {exc}",
                    )
        out.append(mat)
    return out


def _import_q3(operator: bpy.types.Operator, context: bpy.types.Context,
               filepath: Path) -> None:
    scale = float(getattr(operator, "scale", 1.0 / 32.0))
    patch_level = int(getattr(operator, "patch_level", 5))
    texture_root = _resolve_texture_root(operator, context)

    bsp = bsp_q3.read_path(filepath)
    material_list = _build_q3_materials(operator, bsp, texture_root)

    scene = context.scene
    root = bpy.data.collections.new(filepath.stem)
    scene.collection.children.link(root)
    geom_coll = bpy.data.collections.new(f"{filepath.stem}_Geometry")
    root.children.link(geom_coll)

    # Pass 1: polygon + mesh face types use shared vertex buffer.
    poly_indices: list[list[int]] = []
    poly_uvs: list[list[tuple[float, float]]] = []
    poly_mats: list[int] = []
    for face in bsp.faces:
        if face.type == bsp_q3.FACE_TYPE_POLY or face.type == bsp_q3.FACE_TYPE_MESH:
            base = face.vertex
            indices: list[int] = []
            if face.n_meshverts > 0:
                # meshverts are triangle indices relative to face.vertex.
                tri_indices = bsp.meshverts[face.meshvert:face.meshvert + face.n_meshverts]
                # Group into triangles, emit each as a 3-vert poly.
                for k in range(0, len(tri_indices), 3):
                    tri = tri_indices[k:k + 3]
                    if len(tri) == 3:
                        poly_indices.append([base + tri[0], base + tri[1], base + tri[2]])
                        poly_uvs.append([bsp.vertices[base + i].tex_uv for i in tri])
                        poly_mats.append(face.texture)
                continue
            indices = list(range(base, base + face.n_vertexes))
            if len(indices) >= 3:
                poly_indices.append(indices)
                poly_uvs.append([bsp.vertices[i].tex_uv for i in indices])
                poly_mats.append(face.texture)

    # Convert tex_uvs to (u, 1-v) for Blender convention.
    flipped_uvs = [[(u, 1.0 - v) for (u, v) in poly] for poly in poly_uvs]
    poly_vert_positions = [bsp.vertices[i].pos for i in range(len(bsp.vertices))]
    builder_geometry.build_bsp_geometry(
        name=filepath.stem,
        vertices=poly_vert_positions,
        face_polygons=poly_indices,
        face_materials=poly_mats,
        face_uvs=flipped_uvs,
        collection=geom_coll,
        material_list=material_list,
        scale=scale,
    )

    # Pass 2: patches → tessellated quads, one mesh per patch (preserves
    # the original control grid as a custom property for future round-trip).
    patches_coll = bpy.data.collections.new(f"{filepath.stem}_Patches")
    root.children.link(patches_coll)
    for fi, face in enumerate(bsp.faces):
        if face.type != bsp_q3.FACE_TYPE_PATCH:
            continue
        cw, ch = face.size
        if cw < 3 or ch < 3 or cw * ch != face.n_vertexes:
            continue
        controls: list[patch_mod.Control] = []
        for k in range(face.n_vertexes):
            v = bsp.vertices[face.vertex + k]
            controls.append(patch_mod.Control(pos=v.pos, uv=v.tex_uv))
        patch = patch_mod.Patch(width=cw, height=ch, controls=controls)
        try:
            tess = patch_mod.tessellate(patch, level=patch_level)
        except Exception as exc:
            qb_log.report(
                operator,
                {"WARNING"},
                f"Skipping patch {filepath.stem}_patch_{fi}: {exc}",
            )
            continue

        flipped_quads = [[(u, 1.0 - v) for (u, v) in (tess.uvs[i] for i in q)] for q in tess.quads]
        builder_geometry.build_bsp_geometry(
            name=f"{filepath.stem}_patch_{fi}",
            vertices=tess.vertices,
            face_polygons=[list(q) for q in tess.quads],
            face_materials=[face.texture] * len(tess.quads),
            face_uvs=flipped_quads,
            collection=patches_coll,
            material_list=material_list,
            scale=scale,
        )
        # Stash the original control grid for future export.
        patch_obj_name = f"{filepath.stem}_patch_{fi}"
        obj = bpy.data.objects.get(patch_obj_name)
        if obj is not None:
            obj["qb_patch_control_grid"] = [
                [c.pos.x, c.pos.y, c.pos.z, c.uv[0], c.uv[1]] for c in controls
            ]
            obj["qb_patch_size"] = [cw, ch]

    if getattr(operator, "import_entities", True):
        ent_coll = bpy.data.collections.new(f"{filepath.stem}_Entities")
        root.children.link(ent_coll)
        for entity in bsp.entities:
            classname = entity.get("classname", "entity")
            if not getattr(operator, "import_lights", True) and classname.startswith("light"):
                continue
            builder_entities.build_entity(entity, ent_coll, scale=scale, operator=operator)