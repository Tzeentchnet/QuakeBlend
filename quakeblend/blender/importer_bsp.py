"""Operator: import a Quake .bsp file (Q1/Q2/Q3, autodetected by version)."""

from __future__ import annotations

import os

import bpy
from bpy_extras.io_utils import ImportHelper

from ..utils.constants import DEFAULT_IMPORT_SCALE, DEFAULT_PATCH_LEVEL


class IMPORT_OT_quake_bsp(bpy.types.Operator, ImportHelper):
    bl_idname = "quakeblend.import_bsp"
    bl_label = "Import Quake BSP"
    bl_description = "Import a Quake 1/2/3 compiled .bsp file"
    bl_options = {"PRESET", "UNDO"}

    filename_ext = ".bsp"
    filter_glob: bpy.props.StringProperty(default="*.bsp", options={"HIDDEN"})  # type: ignore[valid-type]

    scale: bpy.props.FloatProperty(  # type: ignore[valid-type]
        name="Scale", default=DEFAULT_IMPORT_SCALE, min=0.0001, max=10.0
    )
    texture_root: bpy.props.StringProperty(  # type: ignore[valid-type]
        name="Texture root",
        description="Folder searched for external Q2 .wal / Q3 .tga|.jpg|.png",
        subtype="DIR_PATH",
        default="",
    )
    import_entities: bpy.props.BoolProperty(name="Import entities", default=True)  # type: ignore[valid-type]
    import_lights: bpy.props.BoolProperty(name="Import lights", default=True)  # type: ignore[valid-type]
    patch_level: bpy.props.IntProperty(  # type: ignore[valid-type]
        name="Patch tessellation level",
        description="Q3 patch subdivision (segments per Bezier span)",
        default=DEFAULT_PATCH_LEVEL,
        min=1,
        max=16,
    )

    def execute(self, context: bpy.types.Context) -> set[str]:
        from . import import_runner_bsp
        from .transaction import ImportTransaction

        try:
            with ImportTransaction():
                import_runner_bsp.run(self, context, os.fspath(self.filepath))
        except Exception as exc:  # pragma: no cover
            self.report({"ERROR"}, f"BSP import failed: {exc}")
            return {"CANCELLED"}
        return {"FINISHED"}


def register() -> None:
    bpy.utils.register_class(IMPORT_OT_quake_bsp)


def unregister() -> None:
    bpy.utils.unregister_class(IMPORT_OT_quake_bsp)
