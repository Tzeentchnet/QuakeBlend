"""Import policy shared by Blender adapters and pure tests."""

from __future__ import annotations

from dataclasses import dataclass, fields

from .constants import Q2_CONTENTS_CLIP, Q3_CONTENTS_CLIP, Q3_CONTENTS_TRIGGER, Q3_SURF_HINT


TOOL_ITEMS = (
    ("VISIBLE", "Visible", "Import and show in the viewport"),
    ("HIDDEN", "Hidden in Viewport", "Import with the Outliner eye closed; render visibility is unchanged"),
    ("SKIP", "Skip", "Do not create these objects; source MAP export still retains their source data"),
)
LIGHTING_ITEMS = (
    ("FULLBRIGHT", "Fullbright", "Unlit shader colors without lightmaps or baked vertex shading"),
    ("RELIT", "Blender Lighting", "Use scene lighting without baked shading; retain shader glow"),
    ("BAKED", "Baked", "Use compiled Q3 lightmaps and vertex shading"),
)


def is_trigger(properties):
    return properties.get("classname", "").casefold().startswith("trigger_")


@dataclass(frozen=True)
class ImportOptions:
    worldspawn_only: bool = False
    group_entities: bool = True
    create_materials: bool = True
    import_brush_entities: bool = True
    import_entities: bool = True
    import_lights: bool = True
    import_cameras: bool = True
    trigger_handling: str = "HIDDEN"
    clip_handling: str = "HIDDEN"
    hint_handling: str = "HIDDEN"
    q3_lighting: str = "RELIT"
    q3_animate_shaders: bool = True
    q3_deform_geometry: bool = True

    @classmethod
    def from_operator(cls, operator, *, bsp=False):
        defaults = cls(q3_lighting="FULLBRIGHT" if bsp else "RELIT")
        values = {field.name: getattr(operator, field.name, getattr(defaults, field.name)) for field in fields(cls)}
        for name in ("trigger_handling", "clip_handling", "hint_handling"):
            if values[name] not in {"VISIBLE", "HIDDEN", "SKIP"}:
                raise ValueError(f"Invalid {name}: {values[name]}")
        if values["q3_lighting"] not in {"FULLBRIGHT", "RELIT", "BAKED"}:
            raise ValueError(f"Invalid lighting mode: {values['q3_lighting']}")
        if not bsp and values["q3_lighting"] == "BAKED":
            raise ValueError("Source MAP files do not contain baked lightmaps")
        return cls(**values)

    def disposition(self, categories):
        modes = [getattr(self, f"{category}_handling") for category in categories]
        return "SKIP" if "SKIP" in modes else "HIDDEN" if "HIDDEN" in modes else "VISIBLE"

    def model_allowed(self, index, properties):
        return (index == 0 or (not self.worldspawn_only and self.import_brush_entities)) and not (
            is_trigger(properties) and self.trigger_handling == "SKIP")

    def shader_kwargs(self):
        return {"lighting": self.q3_lighting, "animate_shaders": self.q3_animate_shaders,
                "deform_geometry": self.q3_deform_geometry}


@dataclass(frozen=True)
class ToolSurface:
    name: str
    contents: int = 0
    flags: int = 0
    surfaceparms: tuple[str, ...] = ()
    resolved: bool = True


def classify_tool_brush(surfaces, game):
    surfaces = tuple(surfaces)
    if any(not surface.resolved for surface in surfaces):
        return frozenset(), "Unresolved tool-brush metadata; kept visible"
    semantic = set()
    names = set()
    for surface in surfaces:
        name = surface.name.replace("\\", "/").casefold()
        names.add(name)
        if game == "q2" and surface.contents & Q2_CONTENTS_CLIP:
            semantic.add("clip")
        if game == "q3":
            parms = {value.casefold() for value in surface.surfaceparms}
            if surface.contents & Q3_CONTENTS_CLIP or parms & {"clip", "playerclip", "monsterclip", "botclip"}:
                semantic.add("clip")
            if surface.flags & Q3_SURF_HINT or "hint" in parms:
                semantic.add("hint")
            if surface.contents & Q3_CONTENTS_TRIGGER or "trigger" in parms:
                semantic.add("trigger")
    if len(semantic) > 1:
        return frozenset(), "Conflicting tool-brush semantics; kept visible"
    if semantic:
        return frozenset(semantic), ""
    tools = {"clip": {"clip"}, "hint": {"hint"}}
    neutral = {"skip", "hintskip"}
    if game == "q3":
        tools = {"clip": {"textures/common/clip", "textures/common/playerclip", "textures/common/monsterclip", "textures/common/botclip"},
                 "hint": {"textures/common/hint"}}
        neutral = {"textures/common/skip", "textures/common/hintskip", "textures/common/nodraw"}
    for category, identifiers in tools.items():
        if names & identifiers:
            if names <= identifiers | neutral:
                return frozenset({category}), ""
            return frozenset(), "Mixed tool and ordinary textures; kept visible"
    return frozenset(), ""
