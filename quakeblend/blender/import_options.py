"""Native import controls and import-local visibility state."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

import bpy

from ..utils.import_options import ImportOptions, LIGHTING_ITEMS, TOOL_ITEMS


def import_option_properties(*, bsp=False):
    props = {
        "worldspawn_only": bpy.props.BoolProperty(name="Worldspawn Only", default=False,
            description="Import world geometry only, without non-world brushes or entity objects"),
        "group_entities": bpy.props.BoolProperty(name="Organize in Collections", default=True,
            description="Group objects in subcollections; disabling does not change parenting or transforms"),
        "trigger_handling": bpy.props.EnumProperty(name="Triggers", items=TOOL_ITEMS, default="HIDDEN"),
        "q3_lighting": bpy.props.EnumProperty(name="Lighting", items=LIGHTING_ITEMS if bsp else LIGHTING_ITEMS[:2],
            default="FULLBRIGHT" if bsp else "RELIT"),
        "q3_animate_shaders": bpy.props.BoolProperty(name="Animate Shaders", default=True,
            description="Animate textures, UVs and colors; disabling freezes stage time at zero, not vertex waves"),
        "q3_deform_geometry": bpy.props.BoolProperty(name="Deform Geometry", default=True,
            description="Enable supported vertex waves, independently of texture animation"),
    }
    if not bsp:
        props.update({
            "create_materials": bpy.props.BoolProperty(name="Create Materials", default=True,
                description="Create materials and images; disabling preserves geometry, UVs and source data"),
            "import_brush_entities": bpy.props.BoolProperty(name="Import Brush Entities", default=True,
                description="Include non-world brushes independently of entity objects"),
            "clip_handling": bpy.props.EnumProperty(name="Clip Brushes", items=TOOL_ITEMS, default="HIDDEN"),
            "hint_handling": bpy.props.EnumProperty(name="Hint Brushes", items=TOOL_ITEMS, default="HIDDEN"),
        })
    return props


def configure_import_operator(*, bsp=False):
    def decorate(cls):
        cls.__annotations__.update(import_option_properties(bsp=bsp))
        if bsp:
            cls.__annotations__["detected_game"] = bpy.props.StringProperty(options={"HIDDEN", "SKIP_SAVE"})
            cls.__annotations__["detected_path"] = bpy.props.StringProperty(options={"HIDDEN", "SKIP_SAVE"})
        cls.draw = draw_import_options
        cls.check = check_import_options
        cls.invoke = invoke_import_options
        return cls
    return decorate


def invoke_import_options(operator, context, event):
    from bpy_extras.io_utils import ImportHelper

    from .prefs import apply_import_defaults

    apply_import_defaults(operator, context)
    return ImportHelper.invoke(operator, context, event)


def check_import_options(operator, context):
    if not hasattr(operator, "detected_game") or operator.detected_path == operator.filepath:
        return False
    operator.detected_path = operator.filepath
    try:
        from .import_runner_bsp import _detect_version

        operator.detected_game = _detect_version(Path(operator.filepath))[0].upper()
    except (OSError, ValueError):
        operator.detected_game = ""
    return True


def draw_import_options(operator, context):
    layout = operator.layout
    layout.use_property_split = True
    layout.use_property_decorate = False
    bsp = hasattr(operator, "detected_game")
    game = operator.detected_game if bsp else operator.source_game

    def panel(key, label, closed=False):
        header, body = layout.panel(key, default_closed=closed)
        header.label(text=label)
        return body

    body = panel("qb_source", "Source")
    if body:
        if not bsp:
            body.prop(operator, "source_game")
        body.prop(operator, "scale")
    body = panel("qb_content", "Content")
    if body:
        body.prop(operator, "worldspawn_only")
        body.prop(operator, "group_entities", text="Collections")
        content = body.column()
        content.enabled = not operator.worldspawn_only
        content.prop(operator, "import_brush_entities", text="Brush Entities")
        content.prop(operator, "import_entities", text="Entity Objects")
        entities = content.column()
        entities.enabled = operator.import_entities
        entities.prop(operator, "import_lights", text="Lights")
        lights = entities.column()
        lights.enabled = operator.import_lights
        lights.prop(operator, "light_energy", text="Light Energy")
        entities.prop(operator, "import_cameras", text="Cameras")
    body = panel("qb_materials", "Materials")
    if body:
        body.prop(operator, "create_materials")
        body.prop(operator, "texture_root")
        if not bsp:
            body.prop(operator, "wad_paths")
    body = panel("qb_tools", "Tool Geometry")
    if body:
        triggers = body.column()
        triggers.enabled = not operator.worldspawn_only
        triggers.prop(operator, "trigger_handling")
        if not bsp:
            body.prop(operator, "clip_handling")
            body.prop(operator, "hint_handling")
    if game in {"", "AUTO", "Q3"}:
        body = panel("qb_q3", "Quake 3", game != "Q3")
        if body:
            body.prop(operator, "patch_level", text="Patch Detail")
            materials = body.column()
            materials.enabled = operator.create_materials
            materials.prop(operator, "q3_material_mode")
            shaders = materials.column()
            shaders.enabled = operator.q3_material_mode == "SHADERS"
            shaders.prop(operator, "q3_lighting")
            shaders.prop(operator, "q3_animate_shaders", text="Animation")
            shaders.prop(operator, "q3_deform_geometry", text="Deformation")
    if bsp and game in {"", "GOLDSRC"}:
        body = panel("qb_goldsrc", "GoldSrc", game != "GOLDSRC")
        if body:
            body.prop(operator, "wad_paths")
            body.prop(operator, "stitch_goldsrc", text="Stitch Landmarks")
            target = body.column()
            target.enabled = operator.stitch_goldsrc
            target.prop(operator, "stitch_target")


class ImportState:
    def __init__(self, operator, context, *, bsp=False):
        self.operator = operator
        self.context = context
        self.options = ImportOptions.from_operator(operator, bsp=bsp)
        self.hidden = []
        self.counts = {"visible": 0, "hidden": 0, "skipped": 0}
        self.warnings = set()

    def warn(self, message):
        if message not in self.warnings:
            self.warnings.add(message)
            self.operator.report({"WARNING"}, message)

    def collection(self, root, name):
        if not self.options.group_entities:
            return root
        child = bpy.data.collections.new(name)
        root.children.link(child)
        return child

    def mark(self, obj, categories):
        if obj is None or not categories:
            return
        disposition = self.options.disposition(categories)
        obj["qb_tool_categories"] = ",".join(sorted(categories))
        obj["qb_tool_handling"] = disposition
        self.counts[disposition.lower()] += 1
        if disposition == "HIDDEN":
            self.hidden.append(obj)

    def finish(self, root):
        self.context.view_layer.update()
        for obj in self.hidden:
            obj.hide_set(True, view_layer=self.context.view_layer)
        root["qb_import_options"] = json.dumps(asdict(self.options), sort_keys=True)
        root["qb_tool_counts"] = self.counts
        if any(self.counts.values()):
            self.operator.report({"INFO"}, "Tool objects: " + ", ".join(f"{count} {key}" for key, count in self.counts.items()))
