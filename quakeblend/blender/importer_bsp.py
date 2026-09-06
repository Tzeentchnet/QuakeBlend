"""Operator: import a Quake or GoldSrc .bsp file, autodetected by version."""

from __future__ import annotations

import os

import bpy
from bpy_extras.io_utils import ImportHelper

from ..utils.constants import DEFAULT_IMPORT_SCALE, DEFAULT_PATCH_LEVEL
from .map_assembly import target_items
from .import_options import configure_import_operator


@configure_import_operator(bsp=True)
class IMPORT_OT_quake_bsp(bpy.types.Operator, ImportHelper):
    bl_idname = "quakeblend.import_bsp"
    bl_label = "Import Quake BSP"
    bl_description = "Import a Quake 1/2/3 or GoldSrc compiled .bsp file"
    bl_options = {"PRESET", "UNDO"}

    filename_ext = ".bsp"
    filter_glob: bpy.props.StringProperty(default="*.bsp", options={"HIDDEN"})  # type: ignore[valid-type]

    scale: bpy.props.FloatProperty(  # type: ignore[valid-type]
        name="Scale", default=DEFAULT_IMPORT_SCALE, min=0.0001, max=10.0
    )
    texture_root: bpy.props.StringProperty(  # type: ignore[valid-type]
        name="Texture root",
        description="Folder searched for external Q2 WAL or Q3/GoldSrc texture images",
        subtype="DIR_PATH",
        default="",
    )
    q3_material_mode: bpy.props.EnumProperty(
        name="Q3 materials",
        items=(("SHADERS", "Shaders", "Use scripts and textures from a prepared asset root; skies deferred"),
               ("DIRECT", "Direct images", "Legacy same-name images only")),
        default="SHADERS",
    )
    wad_paths: bpy.props.StringProperty(  # type: ignore[valid-type]
        name="GoldSrc WAD files",
        description="Semicolon-separated WAD3 paths, searched in order for GoldSrc textures",
        default="",
    )
    stitch_goldsrc: bpy.props.BoolProperty(  # type: ignore[valid-type]
        name="Stitch GoldSrc landmarks",
        description="Translate this GoldSrc map to matching imported changelevel landmarks",
        default=False,
    )
    stitch_target: bpy.props.EnumProperty(  # type: ignore[valid-type]
        name="Stitch target",
        description="Choose an imported instance when automatic matching is ambiguous",
        items=target_items,
    )
    import_brush_entities: bpy.props.BoolProperty(  # type: ignore[valid-type]
        name="Import brush models",
        description="Include BSP submodels beyond worldspawn; independent of point entities",
        default=True,
    )
    create_materials: bpy.props.BoolProperty(  # type: ignore[valid-type]
        name="Create materials",
        description="Create texture images and materials; disabling keeps geometry and UVs",
        default=True,
    )
    import_entities: bpy.props.BoolProperty(name="Import entities", default=True)  # type: ignore[valid-type]
    import_lights: bpy.props.BoolProperty(name="Import lights", default=True)  # type: ignore[valid-type]
    import_cameras: bpy.props.BoolProperty(name="Import cameras", default=True)  # type: ignore[valid-type]
    light_energy: bpy.props.FloatProperty(  # type: ignore[valid-type]
        name="Light energy multiplier",
        description=(
            "Scales converted light wattage. Quake light values are converted "
            "to watts for the chosen world scale; raise or lower this to taste"
        ),
        default=1.0,
        min=0.0,
        soft_max=100.0,
    )
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
