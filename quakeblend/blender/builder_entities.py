"""Build Blender objects from parsed entity dicts."""

from __future__ import annotations

import math

import bpy

from ..formats.entities import parse_color, parse_origin
from ..utils import log as qb_log
from ..utils.constants import DEFAULT_QUAKE_LIGHT, QUAKE_LIGHT_TO_WATTS


def _entity_label(entity: dict[str, str], classname: str) -> str:
    targetname = entity.get("targetname")
    return f"{classname} ({targetname})" if targetname else classname


def tag_entity_properties(obj: bpy.types.Object, entity: dict[str, str]) -> None:
    """Store every entity key/value on ``obj`` under the ``qb_prop_`` prefix.

    The prefix keeps map keys out of Blender's own custom-property namespace
    and is what :mod:`quakeblend.blender.exporter_map` reads back.
    """
    for key, value in entity.items():
        try:
            obj[f"qb_prop_{key}"] = value
        except (TypeError, KeyError):
            continue


def _light_energy(entity: dict[str, str], scale: float, multiplier: float) -> float:
    raw = entity.get("light", entity.get("_light", ""))
    try:
        value = float(str(raw).split()[0]) if str(raw).strip() else DEFAULT_QUAKE_LIGHT
    except (ValueError, IndexError):
        value = DEFAULT_QUAKE_LIGHT
    return value * QUAKE_LIGHT_TO_WATTS * scale * scale * multiplier


def build_entity(entity: dict[str, str], collection: bpy.types.Collection,
                 *,
                 scale: float,
                 light_multiplier: float = 1.0,
                 operator: bpy.types.Operator | None = None) -> bpy.types.Object | None:
    classname = entity.get("classname", "entity")
    origin_str = entity.get("origin")
    if not origin_str:
        return None
    try:
        ox, oy, oz = parse_origin(origin_str)
    except ValueError as exc:
        message = (
            f"Skipping entity {_entity_label(entity, classname)}: "
            f"invalid origin '{origin_str}' ({exc})"
        )
        if operator is not None:
            qb_log.report(operator, {"WARNING"}, message)
        else:
            qb_log.get_logger("blender").warning(message)
        return None
    location = (ox * scale, oy * scale, oz * scale)

    if classname.startswith("light"):
        light_data = bpy.data.lights.new(name=classname, type="POINT")
        # Quake "light" is an intensity in Quake units; convert to watts.
        light_data.energy = _light_energy(entity, scale, light_multiplier)
        if "_color" in entity:
            try:
                light_data.color = parse_color(entity["_color"])
            except ValueError:
                light_data.color = (1.0, 1.0, 1.0)
        obj = bpy.data.objects.new(classname, light_data)
    elif classname in ("info_player_start", "info_player_deathmatch",
                       "info_player_coop", "info_intermission"):
        cam_data = bpy.data.cameras.new(name=classname)
        obj = bpy.data.objects.new(classname, cam_data)
        try:
            yaw = float(entity.get("angle", "0"))
        except ValueError:
            yaw = 0.0
        # Quake camera looks down +X; Blender camera looks down -Z. Apply
        # Z-up yaw + a -90° X tilt to align.
        obj.rotation_euler = (math.radians(90), 0.0, math.radians(yaw - 90.0))
    else:
        obj = bpy.data.objects.new(classname, None)
        obj.empty_display_type = "PLAIN_AXES"

    obj.location = location
    tag_entity_properties(obj, entity)
    collection.objects.link(obj)
    return obj
