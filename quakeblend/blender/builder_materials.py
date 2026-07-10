"""Build Blender images and materials from decoded Quake textures.

The blender layer is the only place that touches ``bpy`` for asset creation.
Decoded RGBA byte buffers come from the formats layer.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import bpy

from ..formats import palette as palette_mod
from ..formats.wad import MipTexture
from ..formats.wal import (
    SURF_LIGHT, SURF_SKY, SURF_TRANS33, SURF_TRANS66, SURF_WARP, Wal,
)


# --------------------------------------------------------------------- images


def _flip_rows(rgba: bytes, width: int, height: int) -> bytes:
    """Flip a top-down RGBA buffer so it matches Blender's bottom-up convention."""
    row = width * 4
    out = bytearray(len(rgba))
    for y in range(height):
        src = y * row
        dst = (height - 1 - y) * row
        out[dst:dst + row] = rgba[src:src + row]
    return bytes(out)


def _bytes_to_floats(rgba: bytes) -> list[float]:
    return [b / 255.0 for b in rgba]


def _find_asset_by_key(items, asset_key: str):
    for item in items:
        if item.get("qb_asset_key") == asset_key:
            return item
    return None


def _asset_name(items, name: str, asset_key: str | None) -> str:
    existing = items.get(name)
    if existing is None or asset_key is None:
        return name
    digest = hashlib.sha256(asset_key.encode("utf-8")).hexdigest()[:8]
    return f"{name} [{digest}]"


def create_image(name: str, width: int, height: int, rgba_top_down: bytes,
                 *, alpha: bool = True,
                 asset_key: str | None = None) -> bpy.types.Image:
    """Create a Blender image from a top-down RGBA byte buffer."""
    existing = (
        _find_asset_by_key(bpy.data.images, asset_key)
        if asset_key is not None
        else bpy.data.images.get(name)
    )
    if existing is not None:
        return existing
    if width <= 0 or height <= 0 or len(rgba_top_down) != width * height * 4:
        raise ValueError(
            f"invalid RGBA image {name!r}: {width}×{height}, "
            f"buffer={len(rgba_top_down)} bytes"
        )
    img = bpy.data.images.new(
        _asset_name(bpy.data.images, name, asset_key),
        width=width,
        height=height,
        alpha=alpha,
    )
    if asset_key is not None:
        img["qb_asset_key"] = asset_key
    img.pixels = _bytes_to_floats(_flip_rows(rgba_top_down, width, height))
    img.pack()
    return img


def load_external_image(name: str, path: Path, *, asset_key: str) -> bpy.types.Image:
    existing = _find_asset_by_key(bpy.data.images, asset_key)
    if existing is not None:
        return existing
    image = bpy.data.images.load(str(path), check_existing=False)
    image.name = _asset_name(bpy.data.images, name, asset_key)
    image["qb_asset_key"] = asset_key
    return image


# ------------------------------------------------------------------ materials


@dataclass(frozen=True)
class MaterialFlags:
    sky: bool = False
    warp: bool = False
    transparent_alpha: float = 1.0   # 1.0 = opaque
    texture_alpha: bool = False
    emissive: bool = False           # SURF_LIGHT or fullbright pixels


def _flags_from_wal(w: Wal) -> MaterialFlags:
    return MaterialFlags(
        sky=bool(w.flags & SURF_SKY),
        warp=bool(w.flags & SURF_WARP),
        transparent_alpha=(0.33 if w.flags & SURF_TRANS33 else
                           0.66 if w.flags & SURF_TRANS66 else 1.0),
        emissive=bool(w.flags & SURF_LIGHT),
    )


def _enable_transparency(mat: bpy.types.Material) -> None:
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "DITHERED"
    elif hasattr(mat, "blend_method"):
        mat.blend_method = "BLEND"


def _build_node_tree(mat: bpy.types.Material, color_image: bpy.types.Image,
                     emission_image: Optional[bpy.types.Image],
                     flags: MaterialFlags) -> None:
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (400, 0)

    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (0, 0)
    bsdf.inputs["Roughness"].default_value = 1.0
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = 0.0
    elif "Specular" in bsdf.inputs:
        bsdf.inputs["Specular"].default_value = 0.0

    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.location = (-400, 0)
    tex.image = color_image
    tex.interpolation = "Closest"   # crisp pixel-art look
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])

    if flags.texture_alpha:
        if flags.transparent_alpha < 1.0:
            alpha_multiply = nt.nodes.new("ShaderNodeMath")
            alpha_multiply.operation = "MULTIPLY"
            alpha_multiply.inputs[1].default_value = flags.transparent_alpha
            nt.links.new(tex.outputs["Alpha"], alpha_multiply.inputs[0])
            nt.links.new(alpha_multiply.outputs[0], bsdf.inputs["Alpha"])
        else:
            nt.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
        _enable_transparency(mat)
    elif flags.transparent_alpha < 1.0:
        bsdf.inputs["Alpha"].default_value = flags.transparent_alpha
        _enable_transparency(mat)

    if emission_image is not None or flags.emissive or flags.sky:
        if "Emission Color" in bsdf.inputs:
            emission_color = bsdf.inputs["Emission Color"]
        elif "Emission" in bsdf.inputs:
            emission_color = bsdf.inputs["Emission"]
        else:
            emission_color = None
        if emission_color is not None:
            if emission_image is not None:
                mask_tex = nt.nodes.new("ShaderNodeTexImage")
                mask_tex.location = (-400, -350)
                mask_tex.image = emission_image
                mask_tex.interpolation = "Closest"
                multiply = nt.nodes.new("ShaderNodeMixRGB")
                multiply.blend_type = "MULTIPLY"
                multiply.inputs["Fac"].default_value = 1.0
                nt.links.new(tex.outputs["Color"], multiply.inputs[1])
                nt.links.new(mask_tex.outputs["Color"], multiply.inputs[2])
                nt.links.new(multiply.outputs["Color"], emission_color)
            else:
                nt.links.new(tex.outputs["Color"], emission_color)
            if "Emission Strength" in bsdf.inputs:
                bsdf.inputs["Emission Strength"].default_value = (
                    5.0 if flags.sky else 2.0
                )

    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])


def get_or_create_material(
    name: str, color_image: bpy.types.Image,
    emission_image: Optional[bpy.types.Image] = None,
    flags: MaterialFlags = MaterialFlags(),
    *, asset_key: str | None = None,
) -> bpy.types.Material:
    """Return the named material, creating it if missing."""
    mat = (
        _find_asset_by_key(bpy.data.materials, asset_key)
        if asset_key is not None
        else bpy.data.materials.get(name)
    )
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(_asset_name(bpy.data.materials, name, asset_key))
    if asset_key is not None:
        mat["qb_asset_key"] = asset_key
    _build_node_tree(mat, color_image, emission_image, flags)
    return mat


def get_or_create_placeholder_material(name: str, *, asset_key: str) -> bpy.types.Material:
    mat = _find_asset_by_key(bpy.data.materials, asset_key)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(_asset_name(bpy.data.materials, name, asset_key))
    mat["qb_asset_key"] = asset_key
    mat["qb_placeholder"] = True
    return mat


def material_from_external_image(name: str, path: Path, *,
                                 source_key: str) -> bpy.types.Material:
    image = load_external_image(name, path, asset_key=f"{source_key}|image")
    return get_or_create_material(
        name,
        image,
        flags=MaterialFlags(texture_alpha=path.suffix.lower() in (".png", ".tga")),
        asset_key=f"{source_key}|material",
    )


# ---------------------------------------------------- texture-source helpers


def material_from_miptex(mt: MipTexture, pal: palette_mod.Palette, *,
                         source_key: str | None = None) -> bpy.types.Material:
    """Create a material from a Quake 1 miptex."""
    rgba = palette_mod.decode_indexed(
        mt.pixels, pal,
        opaque_index=255 if mt.name.startswith("{") else None,
    )
    img = create_image(
        mt.name,
        mt.width,
        mt.height,
        rgba,
        asset_key=f"{source_key}|image" if source_key is not None else None,
    )

    emission_img: bpy.types.Image | None = None
    if palette_mod.has_fullbright(mt.pixels, pal):
        mask = palette_mod.fullbright_mask(mt.pixels, pal)
        # Promote single-channel mask to RGBA for Blender.
        rgba_mask = bytearray(len(mask) * 4)
        for i, m in enumerate(mask):
            rgba_mask[i * 4 + 0] = m
            rgba_mask[i * 4 + 1] = m
            rgba_mask[i * 4 + 2] = m
            rgba_mask[i * 4 + 3] = 255
        emission_img = create_image(
            f"{mt.name}__fullbright",
            mt.width,
            mt.height,
            bytes(rgba_mask),
            asset_key=(
                f"{source_key}|fullbright" if source_key is not None else None
            ),
        )

    flags = MaterialFlags(
        sky=mt.name.lower().startswith("sky"),
        warp=mt.name.startswith("*"),
        texture_alpha=mt.name.startswith("{"),
        emissive=emission_img is not None,
    )
    return get_or_create_material(
        mt.name,
        img,
        emission_img,
        flags,
        asset_key=f"{source_key}|material" if source_key is not None else None,
    )


def material_from_wal(w: Wal, pal: palette_mod.Palette, *,
                      source_key: str | None = None) -> bpy.types.Material:
    """Create a material from a Quake 2 WAL texture."""
    rgba = palette_mod.decode_indexed(w.pixels, pal, opaque_index=None)
    img = create_image(
        w.name,
        w.width,
        w.height,
        rgba,
        asset_key=f"{source_key}|image" if source_key is not None else None,
    )
    flags = _flags_from_wal(w)
    emission_img: bpy.types.Image | None = None
    if palette_mod.has_fullbright(w.pixels, pal):
        mask = palette_mod.fullbright_mask(w.pixels, pal)
        rgba_mask = bytearray(len(mask) * 4)
        for i, m in enumerate(mask):
            rgba_mask[i * 4 + 0] = m
            rgba_mask[i * 4 + 1] = m
            rgba_mask[i * 4 + 2] = m
            rgba_mask[i * 4 + 3] = 255
        emission_img = create_image(
            f"{w.name}__fullbright",
            w.width,
            w.height,
            bytes(rgba_mask),
            asset_key=(
                f"{source_key}|fullbright" if source_key is not None else None
            ),
        )
        flags = MaterialFlags(
            sky=flags.sky, warp=flags.warp,
            transparent_alpha=flags.transparent_alpha,
            texture_alpha=flags.texture_alpha,
            emissive=True,
        )
    return get_or_create_material(
        w.name,
        img,
        emission_img,
        flags,
        asset_key=f"{source_key}|material" if source_key is not None else None,
    )
