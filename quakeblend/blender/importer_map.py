"""Operator: import a Quake .map file (Q1/Q2/Q3, autodetected)."""

from __future__ import annotations

import os

import bpy
from bpy_extras.io_utils import ImportHelper

from ..utils.constants import DEFAULT_IMPORT_SCALE, DEFAULT_PATCH_LEVEL


class IMPORT_OT_quake_map(bpy.types.Operator, ImportHelper):
    bl_idname = "quakeblend.import_map"
    bl_label = "Import Quake MAP"
    bl_description = "Import a Quake 1/2/3 .map file (text/CSG brushes)"
    bl_options = {"PRESET", "UNDO"}

    filename_ext = ".map"
    filter_glob: bpy.props.StringProperty(default="*.map", options={"HIDDEN"})  # type: ignore[valid-type]

    scale: bpy.props.FloatProperty(  # type: ignore[valid-type]
        name="Scale",
        description="World-unit scale (default 1/32: 32 Quake units → 1 metre)",
        default=DEFAULT_IMPORT_SCALE,
        min=0.0001,
        max=10.0,
    )
    projection: bpy.props.EnumProperty(  # type: ignore[valid-type]
        name="Texture projection",
        items=(
            ("AUTO", "Auto", "Detect Standard vs Valve220 per face"),
            ("STANDARD", "Standard", "Force standard Quake projection"),
            ("VALVE220", "Valve220", "Force Valve220 projection"),
        ),
        default="AUTO",
    )
    texture_root: bpy.props.StringProperty(  # type: ignore[valid-type]
        name="Texture root",
        description="Folder searched for external textures",
        subtype="DIR_PATH",
        default="",
    )
    wad_paths: bpy.props.StringProperty(  # type: ignore[valid-type]
        name="WAD files",
        description="Semicolon-separated list of Quake 1 .wad files to consult",
        default="",
    )
    import_entities: bpy.props.BoolProperty(  # type: ignore[valid-type]
        name="Import entities",
        default=True,
    )
    import_lights: bpy.props.BoolProperty(  # type: ignore[valid-type]
        name="Import lights",
        default=True,
    )
    patch_level: bpy.props.IntProperty(  # type: ignore[valid-type]
        name="Patch tessellation level",
        description="Q3 patch subdivision (segments per Bezier span)",
        default=DEFAULT_PATCH_LEVEL,
        min=1,
        max=16,
    )

    def execute(self, context: bpy.types.Context) -> set[str]:
        from . import import_runner_map

        try:
            import_runner_map.run(self, context, os.fspath(self.filepath))
        except Exception as exc:  # pragma: no cover - surfaced through UI
            self.report({"ERROR"}, f"MAP import failed: {exc}")
            return {"CANCELLED"}
        return {"FINISHED"}


def register() -> None:
    bpy.utils.register_class(IMPORT_OT_quake_map)


def unregister() -> None:
    bpy.utils.unregister_class(IMPORT_OT_quake_map)
