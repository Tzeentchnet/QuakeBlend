"""Build Blender images and materials from decoded Quake textures.

The blender layer is the only place that touches ``bpy`` for asset creation.
Decoded RGBA byte buffers come from the formats layer.
"""

from __future__ import annotations

from dataclasses import dataclass
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


def create_image(name: str, width: int, height: int, rgba_top_down: bytes,
                 *, alpha: bool = True) -> bpy.types.Image:
    """Create a Blender image from a top-down RGBA byte buffer."""
    existing = bpy.data.images.get(name)
    if existing is not None:
        return existing
    img = bpy.data.images.new(name, width=width, height=height, alpha=alpha)
    img.pixels = _bytes_to_floats(_flip_rows(rgba_top_down, width, height))
    img.pack()
    return img


# ------------------------------------------------------------------ materials


@dataclass(frozen=True)
class MaterialFlags:
    sky: bool = False
    warp: bool = False
    transparent_alpha: float = 1.0   # 1.0 = opaque
    emissive: bool = False           # SURF_LIGHT or fullbright pixels


def _flags_from_wal(w: Wal) -> MaterialFlags:
    return MaterialFlags(
        sky=bool(w.flags & SURF_SKY),
        warp=bool(w.flags & SURF_WARP),
        transparent_alpha=(0.33 if w.flags & SURF_TRANS33 else
                           0.66 if w.flags & SURF_TRANS66 else 1.0),
        emissive=bool(w.flags & SURF_LIGHT),
    )


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
    bsdf.inputs["Specular IOR Level"].default_value = 0.0 \
        if "Specular IOR Level" in bsdf.inputs else 0.0

    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.location = (-400, 0)
    tex.image = color_image
    tex.interpolation = "Closest"   # crisp pixel-art look
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])

    if flags.transparent_alpha < 1.0:
        bsdf.inputs["Alpha"].default_value = flags.transparent_alpha
        mat.blend_method = "BLEND" if hasattr(mat, "blend_method") else "BLEND"

    final_shader = bsdf
    if emission_image is not None or flags.emissive or flags.sky:
        emit = nt.nodes.new("ShaderNodeEmission")
        emit.location = (0, -250)
        emit.inputs["Strength"].default_value = 5.0 if flags.sky else 2.0
        nt.links.new(tex.outputs["Color"], emit.inputs["Color"])

        if emission_image is not None:
            mask_tex = nt.nodes.new("ShaderNodeTexImage")
            mask_tex.location = (-400, -350)
            mask_tex.image = emission_image
            mask_tex.interpolation = "Closest"
            mix = nt.nodes.new("ShaderNodeMixShader")
            mix.location = (200, -100)
            nt.links.new(mask_tex.outputs["Color"], mix.inputs["Fac"])
            nt.links.new(bsdf.outputs["BSDF"], mix.inputs[1])
            nt.links.new(emit.outputs["Emission"], mix.inputs[2])
            final_shader = mix
        else:
            final_shader = emit

    out_in = "Surface"
    if hasattr(final_shader, "outputs"):
        first_out = final_shader.outputs[0]
        nt.links.new(first_out, out.inputs[out_in])


def get_or_create_material(
    name: str, color_image: bpy.types.Image,
    emission_image: Optional[bpy.types.Image] = None,
    flags: MaterialFlags = MaterialFlags(),
) -> bpy.types.Material:
    """Return the named material, creating it if missing."""
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(name)
    _build_node_tree(mat, color_image, emission_image, flags)
    return mat


# ---------------------------------------------------- texture-source helpers


def material_from_miptex(mt: MipTexture, pal: palette_mod.Palette) -> bpy.types.Material:
    """Create a material from a Quake 1 miptex."""
    rgba = palette_mod.decode_indexed(
        mt.pixels, pal,
        opaque_index=255 if mt.name.startswith("{") else None,
    )
    img = create_image(mt.name, mt.width, mt.height, rgba)

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
            f"{mt.name}__fullbright", mt.width, mt.height, bytes(rgba_mask)
        )

    flags = MaterialFlags(
        sky=mt.name.lower().startswith("sky"),
        warp=mt.name.startswith("*"),
        emissive=emission_img is not None,
    )
    return get_or_create_material(mt.name, img, emission_img, flags)


def material_from_wal(w: Wal, pal: palette_mod.Palette) -> bpy.types.Material:
    """Create a material from a Quake 2 WAL texture."""
    rgba = palette_mod.decode_indexed(w.pixels, pal, opaque_index=None)
    img = create_image(w.name, w.width, w.height, rgba)
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
            f"{w.name}__fullbright", w.width, w.height, bytes(rgba_mask)
        )
        flags = MaterialFlags(
            sky=flags.sky, warp=flags.warp,
            transparent_alpha=flags.transparent_alpha, emissive=True,
        )
    return get_or_create_material(w.name, img, emission_img, flags)
