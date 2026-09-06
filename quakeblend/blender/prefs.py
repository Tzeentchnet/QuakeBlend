"""Addon preferences for QuakeBlend."""

from __future__ import annotations

import bpy

from ..utils.constants import DEFAULT_IMPORT_SCALE, DEFAULT_PATCH_LEVEL
from .import_options import import_option_properties

PACKAGE = (
    __package__.rsplit(".", 1)[0]
    if __package__ and "." in __package__
    else "quakeblend"
)


def _preference_properties():
    props = import_option_properties()
    props["q3_map_lighting"] = props.pop("q3_lighting")
    props["q3_bsp_lighting"] = import_option_properties(bsp=True)["q3_lighting"]
    props.update({
        "import_entities": bpy.props.BoolProperty(name="Entity Objects", default=True),
        "import_lights": bpy.props.BoolProperty(name="Lights", default=True),
        "import_cameras": bpy.props.BoolProperty(name="Cameras", default=True),
        "scale": bpy.props.FloatProperty(name="Scale", default=DEFAULT_IMPORT_SCALE, min=0.0001, max=10.0),
        "light_energy": bpy.props.FloatProperty(name="Light Energy", default=1.0, min=0.0, soft_max=100.0),
        "patch_level": bpy.props.IntProperty(name="Patch Detail", default=DEFAULT_PATCH_LEVEL, min=1, max=16),
        "q3_material_mode": bpy.props.EnumProperty(name="Q3 Materials", default="SHADERS",
            items=(("SHADERS", "Shaders", "Use prepared shader assets; sky rendering remains deferred"),
                   ("DIRECT", "Direct Images", "Legacy same-name image lookup without shader effects"))),
        "stitch_goldsrc": bpy.props.BoolProperty(name="Stitch Landmarks", default=False,
            description="Align newly imported GoldSrc BSPs using matching landmarks"),
    })
    return props


IMPORT_DEFAULT_NAMES = tuple(_preference_properties())


def _configure_preferences(cls):
    cls.__annotations__.update({f"default_{name}": prop for name, prop in _preference_properties().items()})
    return cls


@_configure_preferences
class QuakeBlendPreferences(bpy.types.AddonPreferences):
    bl_idname = PACKAGE

    default_texture_root: bpy.props.StringProperty(  # type: ignore[valid-type]
        name="Default texture root",
        description=(
            "Filesystem folder searched for external textures (Q2 .wal, "
            "Q3/GoldSrc images) when no per-import path is supplied"
        ),
        subtype="DIR_PATH",
        default="",
    )

    default_wad_path: bpy.props.StringProperty(  # type: ignore[valid-type]
        name="Default WAD",
        description="Default WAD for MAP imports or WAD3 for GoldSrc BSP imports",
        subtype="FILE_PATH",
        default="",
    )

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, "default_texture_root")
        layout.prop(self, "default_wad_path")
        layout.separator()
        layout.label(text="Import Defaults")
        layout.prop(self, "default_scale")
        layout.prop(self, "default_worldspawn_only")
        layout.prop(self, "default_group_entities", text="Collections")
        content = layout.column()
        content.enabled = not self.default_worldspawn_only
        content.prop(self, "default_import_brush_entities", text="Brush Entities")
        content.prop(self, "default_import_entities")
        entities = content.column()
        entities.enabled = self.default_import_entities
        entities.prop(self, "default_import_lights")
        lights = entities.column()
        lights.enabled = self.default_import_lights
        lights.prop(self, "default_light_energy")
        entities.prop(self, "default_import_cameras")
        layout.prop(self, "default_create_materials")
        layout.separator()
        layout.label(text="Tool Geometry")
        triggers = layout.column()
        triggers.enabled = not self.default_worldspawn_only
        triggers.prop(self, "default_trigger_handling")
        layout.prop(self, "default_clip_handling", text="Clip Brushes (MAP)")
        layout.prop(self, "default_hint_handling", text="Hint Brushes (MAP)")
        layout.separator()
        layout.label(text="Quake 3")
        layout.prop(self, "default_patch_level")
        materials = layout.column()
        materials.enabled = self.default_create_materials
        materials.prop(self, "default_q3_material_mode")
        shaders = materials.column()
        shaders.enabled = self.default_q3_material_mode == "SHADERS"
        shaders.prop(self, "default_q3_map_lighting", text="MAP Lighting")
        shaders.prop(self, "default_q3_bsp_lighting", text="BSP Lighting")
        shaders.prop(self, "default_q3_animate_shaders", text="Animation")
        shaders.prop(self, "default_q3_deform_geometry", text="Deformation")
        layout.separator()
        layout.label(text="GoldSrc BSP")
        layout.prop(self, "default_stitch_goldsrc")


def get_prefs(context: bpy.types.Context) -> QuakeBlendPreferences | None:
    addon = context.preferences.addons.get(PACKAGE)
    if addon is None:
        return None
    return addon.preferences  # type: ignore[return-value]


def apply_import_defaults(operator, context):
    preferences = get_prefs(context)
    if preferences is None:
        return
    bsp = hasattr(operator, "detected_game")
    for name in IMPORT_DEFAULT_NAMES:
        property_name = "q3_lighting" if name == ("q3_bsp_lighting" if bsp else "q3_map_lighting") else name
        if hasattr(operator, property_name) and not operator.properties.is_property_set(property_name, ghost=False):
            setattr(operator, property_name, getattr(preferences, f"default_{name}"))


def register() -> None:
    bpy.utils.register_class(QuakeBlendPreferences)


def unregister() -> None:
    bpy.utils.unregister_class(QuakeBlendPreferences)
