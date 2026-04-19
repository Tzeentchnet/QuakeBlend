"""Addon preferences for QuakeBlend."""

from __future__ import annotations

import bpy

PACKAGE = __package__.split(".")[0] if __package__ else "quakeblend"


class QuakeBlendPreferences(bpy.types.AddonPreferences):
    bl_idname = PACKAGE

    default_texture_root: bpy.props.StringProperty(  # type: ignore[valid-type]
        name="Default texture root",
        description=(
            "Filesystem folder searched for external textures (Q2 .wal, "
            "Q3 .tga/.jpg/.png) when no per-import path is supplied"
        ),
        subtype="DIR_PATH",
        default="",
    )

    default_wad_path: bpy.props.StringProperty(  # type: ignore[valid-type]
        name="Default WAD",
        description="Default Quake 1 WAD file used when importing .map files",
        subtype="FILE_PATH",
        default="",
    )

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.prop(self, "default_texture_root")
        layout.prop(self, "default_wad_path")


def get_prefs(context: bpy.types.Context) -> QuakeBlendPreferences:
    return context.preferences.addons[PACKAGE].preferences  # type: ignore[return-value]


def register() -> None:
    bpy.utils.register_class(QuakeBlendPreferences)


def unregister() -> None:
    bpy.utils.unregister_class(QuakeBlendPreferences)
