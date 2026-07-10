"""Build Blender objects from parsed entity dicts."""

from __future__ import annotations

import math

import bpy

from ..formats.entities import parse_color, parse_origin
from ..utils import log as qb_log


def _entity_label(entity: dict[str, str], classname: str) -> str:
    targetname = entity.get("targetname")
    return f"{classname} ({targetname})" if targetname else classname


def build_entity(entity: dict[str, str], collection: bpy.types.Collection,
                 *,
                 scale: float,
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
        # Quake "light" key is a brightness value (default 300).
        try:
            energy = float(entity.get("light", "300"))
        except ValueError:
            energy = 300.0
        light_data.energy = energy
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
    for key, value in entity.items():
        try:
            obj[key] = value
        except (TypeError, KeyError):
            pass
    collection.objects.link(obj)
    return obj
