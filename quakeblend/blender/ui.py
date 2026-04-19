"""File > Import menu entries."""

from __future__ import annotations

import bpy

from .importer_bsp import IMPORT_OT_quake_bsp
from .importer_map import IMPORT_OT_quake_map
from .importer_wad import IMPORT_OT_quake_wad


def _menu_func_import(self, _context: bpy.types.Context) -> None:
    self.layout.operator(IMPORT_OT_quake_map.bl_idname, text="Quake MAP (.map)")
    self.layout.operator(IMPORT_OT_quake_bsp.bl_idname, text="Quake BSP (.bsp)")
    self.layout.operator(IMPORT_OT_quake_wad.bl_idname, text="Quake textures (.wad/.wal)")


def register() -> None:
    bpy.types.TOPBAR_MT_file_import.append(_menu_func_import)


def unregister() -> None:
    bpy.types.TOPBAR_MT_file_import.remove(_menu_func_import)
