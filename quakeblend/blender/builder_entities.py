"""Build Blender objects from parsed entity dicts."""

from __future__ import annotations

import math

import bpy
from mathutils import Euler, Quaternion

from ..formats.entities import parse_camera_angles, parse_color, parse_goldsrc_light, parse_origin
from ..utils import log as qb_log
from ..utils.constants import (
    CAMERA_ENTITY_CLASSNAMES, DEFAULT_CAMERA_FOV, DEFAULT_QUAKE_LIGHT, QUAKE_LIGHT_TO_WATTS,
)


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
                 game: str = "q1",
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

    unsupported_light = game == "goldsrc" and classname.startswith("light") and (
        classname != "light" or bool(entity.get("target")) or entity.get("_sky", "0") != "0"
    )
    if unsupported_light:
        message = f"GoldSrc {classname}: directional light rendering is unsupported; imported as an empty"
        if operator is not None:
            qb_log.report(operator, {"WARNING"}, message)
        else:
            qb_log.get_logger("blender").warning(message)
        obj = bpy.data.objects.new(classname, None)
        obj.empty_display_type = "PLAIN_AXES"
    elif classname.startswith("light"):
        light_data = bpy.data.lights.new(name=classname, type="POINT")
        # Quake "light" is an intensity in Quake units; convert to watts.
        if game == "goldsrc":
            try:
                color, intensity = parse_goldsrc_light(entity.get("_light", str(DEFAULT_QUAKE_LIGHT)))
            except ValueError as exc:
                message = f"GoldSrc {classname}: invalid _light ({exc}); using default brightness"
                if operator is not None:
                    qb_log.report(operator, {"WARNING"}, message)
                else:
                    qb_log.get_logger("blender").warning(message)
                color, intensity = (1.0, 1.0, 1.0), DEFAULT_QUAKE_LIGHT
            light_data.color = color
            light_data.energy = intensity * QUAKE_LIGHT_TO_WATTS * scale * scale * light_multiplier
        else:
            light_data.energy = _light_energy(entity, scale, light_multiplier)
        if game != "goldsrc" and "_color" in entity:
            try:
                light_data.color = parse_color(entity["_color"])
            except ValueError:
                light_data.color = (1.0, 1.0, 1.0)
        obj = bpy.data.objects.new(classname, light_data)
    elif classname in CAMERA_ENTITY_CLASSNAMES:
        cam_data = bpy.data.cameras.new(name=classname)
        cam_data.sensor_fit = "HORIZONTAL"
        cam_data.lens = cam_data.sensor_width / (2.0 * math.tan(math.radians(DEFAULT_CAMERA_FOV) / 2.0))
        cam_data.lens_unit = "FOV"
        obj = bpy.data.objects.new(classname, cam_data)
        try:
            camera_entity = (
                {**entity, "mangle": entity["angles"]}
                if game == "goldsrc" and "angles" in entity else entity
            )
            pitch, yaw, roll = parse_camera_angles(camera_entity)
        except ValueError as exc:
            message = f"Camera {_entity_label(entity, classname)}: {exc}; using yaw fallback"
            if operator is not None:
                qb_log.report(operator, {"WARNING"}, message)
            else:
                qb_log.get_logger("blender").warning(message)
            try:
                pitch, yaw, roll = parse_camera_angles({"angle": entity.get("angle", "0")})
            except ValueError:
                pitch, yaw, roll = 0.0, 0.0, 0.0
        orientation = Euler((math.radians(90.0 - pitch), 0.0,
                             math.radians(yaw - 90.0))).to_quaternion()
        obj.rotation_euler = (
            orientation @ Quaternion((0.0, 0.0, 1.0), math.radians(-roll))
        ).to_euler()
    else:
        obj = bpy.data.objects.new(classname, None)
        obj.empty_display_type = "PLAIN_AXES"

    obj.location = location
    tag_entity_properties(obj, entity)
    collection.objects.link(obj)
    return obj
