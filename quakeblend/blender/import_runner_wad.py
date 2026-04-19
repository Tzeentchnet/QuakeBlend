"""Runner for the WAD/WAL import operator."""

from __future__ import annotations

from pathlib import Path

import bpy

from ..formats import palette as palette_mod
from ..formats import wad as wad_mod
from ..formats import wal as wal_mod
from . import builder_materials


def run(operator: bpy.types.Operator, context: bpy.types.Context, filepath: str) -> int:
    path = Path(filepath)
    suffix = path.suffix.lower()
    create_materials = getattr(operator, "create_materials", True)

    if suffix == ".wad":
        archive = wad_mod.read_wad_path(path)
        # WAD2 uses the bundled Q1 palette; WAD3 textures may carry their own.
        default_pal = palette_mod.load_bundled("q1")
        count = 0
        for mt in archive.textures:
            pal = palette_mod.from_bytes(mt.palette) if mt.palette else default_pal
            if create_materials:
                builder_materials.material_from_miptex(mt, pal)
            else:
                rgba = palette_mod.decode_indexed(mt.pixels, pal, opaque_index=None)
                builder_materials.create_image(mt.name, mt.width, mt.height, rgba)
            count += 1
        return count

    if suffix == ".wal":
        w = wal_mod.read_wal_path(path)
        pal = palette_mod.load_bundled("q2")
        if create_materials:
            builder_materials.material_from_wal(w, pal)
        else:
            rgba = palette_mod.decode_indexed(w.pixels, pal, opaque_index=None)
            builder_materials.create_image(w.name, w.width, w.height, rgba)
        return 1

    raise ValueError(f"unsupported texture archive extension: {suffix!r}")
