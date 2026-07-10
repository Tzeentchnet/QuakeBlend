"""Operator: import textures from a Quake WAD or WAL file."""

from __future__ import annotations

import os

import bpy
from bpy_extras.io_utils import ImportHelper


class IMPORT_OT_quake_wad(bpy.types.Operator, ImportHelper):
    bl_idname = "quakeblend.import_wad"
    bl_label = "Import Quake textures"
    bl_description = "Import textures from a Quake WAD2/WAD3 archive or single WAL file"
    bl_options = {"UNDO"}

    filename_ext = ".wad"
    filter_glob: bpy.props.StringProperty(default="*.wad;*.wal", options={"HIDDEN"})  # type: ignore[valid-type]

    create_materials: bpy.props.BoolProperty(  # type: ignore[valid-type]
        name="Create materials",
        description="Create one Blender material per texture",
        default=True,
    )

    def execute(self, context: bpy.types.Context) -> set[str]:
        from . import import_runner_wad
        from .transaction import ImportTransaction

        try:
            with ImportTransaction():
                count = import_runner_wad.run(self, context, os.fspath(self.filepath))
        except Exception as exc:  # pragma: no cover
            self.report({"ERROR"}, f"Texture import failed: {exc}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Imported {count} texture(s)")
        return {"FINISHED"}


def register() -> None:
    bpy.utils.register_class(IMPORT_OT_quake_wad)


def unregister() -> None:
    bpy.utils.unregister_class(IMPORT_OT_quake_wad)
