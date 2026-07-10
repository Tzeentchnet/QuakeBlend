"""Serialize an in-memory :class:`~quakeblend.formats.map_q1.MapFile` back to
``.map`` text targeting Q1, Q2, or Q3.

Companion to :mod:`quakeblend.formats.map_q1` (parser). Parsed brush-primitive
faces (``brushDef3``) are serialized through :mod:`~quakeblend.formats.brushdef3`;
captured Bezier patch payloads are preserved verbatim.
"""

from __future__ import annotations

import math
import os
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Literal

from . import brushdef3 as bd3_mod
from .map_q1 import MapBrush, MapEntity, MapFace, MapFile


Dialect = Literal["q1", "q2", "q3"]
Projection = Literal["auto", "standard", "valve220"]


# ----------------------------------------------------------------- helpers


def _fmt_num(x: float) -> str:
    if x == 0.0:
        return "0"
    if x == int(x) and abs(x) < 1e15:
        return str(int(x))
    return f"{x:.6f}".rstrip("0").rstrip(".")


def _fmt_vec(v) -> str:
    return f"( {_fmt_num(v.x)} {_fmt_num(v.y)} {_fmt_num(v.z)} )"


def _quote(s: str) -> str:
    escaped = (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    return '"' + escaped + '"'


def _as_valve220(face: MapFace) -> MapFace:
    if face.tex.is_valve220:
        return face
    s_base, t_base = bd3_mod.base_axes_for_normal(face.plane.normal)
    radians = math.radians(face.tex.rotation)
    cos_r = math.cos(radians)
    sin_r = math.sin(radians)
    s_axis = s_base * cos_r - t_base * sin_r
    t_axis = s_base * sin_r + t_base * cos_r
    tex = replace(
        face.tex,
        s_axis=s_axis,
        s_offset=face.tex.xoffset,
        t_axis=t_axis,
        t_offset=face.tex.yoffset,
        rotation=0.0,
    )
    return replace(face, tex=tex)


def _valve_axis_components(face: MapFace, axis) -> tuple[float, float, float]:
    """Decompose an axis into Standard S/T axes plus the face normal."""
    s_base, t_base = bd3_mod.base_axes_for_normal(face.plane.normal)
    normal = face.plane.normal
    determinant = s_base.dot(t_base.cross(normal))
    if abs(determinant) <= 1e-9:
        raise ValueError("face basis is degenerate")
    return (
        axis.dot(t_base.cross(normal)) / determinant,
        axis.dot(normal.cross(s_base)) / determinant,
        axis.dot(s_base.cross(t_base)) / determinant,
    )


def _standard_projection_loss(face: MapFace) -> str | None:
    if not face.tex.is_valve220:
        return None
    assert face.tex.s_axis is not None and face.tex.t_axis is not None
    try:
        s_x, s_y, _ = _valve_axis_components(face, face.tex.s_axis)
        t_x, t_y, _ = _valve_axis_components(face, face.tex.t_axis)
    except ValueError as exc:
        return str(exc)
    s_length = math.hypot(s_x, s_y)
    t_length = math.hypot(t_x, t_y)
    if s_length <= 1e-9 or t_length <= 1e-9:
        return "one or both texture axes are degenerate"
    if abs(face.tex.xscale) <= 1e-9 or abs(face.tex.yscale) <= 1e-9:
        return "one or both texture scales are zero"
    s_unit = (s_x / s_length, s_y / s_length)
    t_unit = (t_x / t_length, t_y / t_length)
    expected_t = (-s_unit[1], s_unit[0])
    if max(abs(t_unit[i] - expected_t[i]) for i in range(2)) > 1e-5:
        return "the texture axes contain shear or independent rotation"
    return None


def projection_conversion_warnings(
    mf: MapFile,
    projection: Projection,
    *,
    limit: int = 20,
) -> list[str]:
    """Describe Valve220 faces that forced Standard output must approximate."""
    if projection != "standard":
        return []
    messages: list[str] = []
    omitted = 0
    for entity_index, entity in enumerate(mf.entities):
        for brush_index, brush in enumerate(entity.brushes):
            for face_index, face in enumerate(brush.faces):
                reason = _standard_projection_loss(face)
                if reason is None:
                    continue
                if len(messages) < limit:
                    messages.append(
                        f"Valve220 projection on entity {entity_index} brush "
                        f"{brush_index} face {face_index} ({face.tex.name!r}) is not "
                        f"exactly representable as Standard: {reason}; export will "
                        "approximate it"
                    )
                else:
                    omitted += 1
    if omitted:
        messages.append(f"{omitted} additional projection warning(s) omitted")
    return messages


def _as_standard(face: MapFace) -> MapFace:
    if not face.tex.is_valve220:
        return face
    assert face.tex.s_axis is not None and face.tex.t_axis is not None
    s_cos, s_neg_sin, s_normal = _valve_axis_components(
        face, face.tex.s_axis
    )
    t_sin, t_cos, t_normal = _valve_axis_components(face, face.tex.t_axis)
    s_length = math.hypot(s_cos, s_neg_sin)
    t_length = math.hypot(t_sin, t_cos)
    if s_length > 1e-9:
        rotation = math.degrees(math.atan2(-s_neg_sin, s_cos))
    elif t_length > 1e-9:
        rotation = math.degrees(math.atan2(t_sin, t_cos))
    else:
        rotation = face.tex.rotation
    tex = replace(
        face.tex,
        xoffset=(
            face.tex.s_offset + s_normal * face.plane.dist / face.tex.xscale
            if abs(face.tex.xscale) > 1e-9
            else face.tex.s_offset
        ),
        yoffset=(
            face.tex.t_offset + t_normal * face.plane.dist / face.tex.yscale
            if abs(face.tex.yscale) > 1e-9
            else face.tex.t_offset
        ),
        rotation=rotation,
        xscale=(face.tex.xscale / s_length if s_length > 1e-9 else face.tex.xscale),
        yscale=(face.tex.yscale / t_length if t_length > 1e-9 else face.tex.yscale),
        s_axis=None,
        t_axis=None,
    )
    return replace(face, tex=tex)


# --------------------------------------------------------------- face text


def _serialize_face_standard(face: MapFace, *, dialect: Dialect) -> str:
    face = _as_standard(face)
    tex = face.tex
    parts = [
        _fmt_vec(face.p1), _fmt_vec(face.p2), _fmt_vec(face.p3),
        tex.name,
        _fmt_num(tex.xoffset), _fmt_num(tex.yoffset),
        _fmt_num(tex.rotation),
        _fmt_num(tex.xscale), _fmt_num(tex.yscale),
    ]
    if dialect == "q2":
        # Always emit the trailing trio so editors that expect them parse cleanly.
        parts.extend([
            str(int(tex.contents)),
            str(int(tex.surface_flags)),
            str(int(tex.value)),
        ])
    return " ".join(parts)


def _serialize_face_valve220(face: MapFace, *, dialect: Dialect) -> str:
    face = _as_valve220(face)
    tex = face.tex
    assert tex.s_axis is not None and tex.t_axis is not None
    s = tex.s_axis
    t = tex.t_axis
    parts = [
        _fmt_vec(face.p1), _fmt_vec(face.p2), _fmt_vec(face.p3),
        tex.name,
        f"[ {_fmt_num(s.x)} {_fmt_num(s.y)} {_fmt_num(s.z)} {_fmt_num(tex.s_offset)} ]",
        f"[ {_fmt_num(t.x)} {_fmt_num(t.y)} {_fmt_num(t.z)} {_fmt_num(tex.t_offset)} ]",
        _fmt_num(tex.rotation),
        _fmt_num(tex.xscale), _fmt_num(tex.yscale),
    ]
    if dialect == "q2":
        parts.extend([
            str(int(tex.contents)),
            str(int(tex.surface_flags)),
            str(int(tex.value)),
        ])
    return " ".join(parts)


def _choose_face_writer(face: MapFace, projection: Projection):
    if projection == "valve220":
        return _serialize_face_valve220
    if projection == "standard":
        return _serialize_face_standard
    # auto: pick per-face based on TexInfo shape.
    return _serialize_face_valve220 if face.tex.is_valve220 else _serialize_face_standard


# --------------------------------------------------------------- brush text


def _serialize_brush(brush: MapBrush, *, dialect: Dialect, projection: Projection,
                     indent: str) -> list[str]:
    lines = [indent + "{"]
    if brush.raw_kind == "patchDef2":
        lines.append(indent + "patchDef2")
        payload = brush.raw_payload.strip()
        if not payload.startswith("{"):
            lines.append(indent + "{")
        for line in payload.splitlines():
            lines.append(indent + line)
        if not payload.endswith("}"):
            lines.append(indent + "}")
    elif brush.raw_kind in ("brushDef3", "brushDef"):
        if brush.faces:
            body = bd3_mod.serialize_brushdef3(brush, indent=indent)
            for line in body.splitlines():
                lines.append(indent + line)
        else:
            lines.append(indent + brush.raw_kind)
            for line in brush.raw_payload.strip().splitlines():
                lines.append(indent + line)
    elif brush.raw_kind == "patchDef3":
        lines.append(indent + "patchDef3")
        for line in brush.raw_payload.strip().splitlines():
            lines.append(indent + line)
    else:
        for face in brush.faces:
            # Re-pick per-face for "auto"; respect the requested mode otherwise.
            writer = _choose_face_writer(face, projection)
            lines.append(indent * 2 + writer(face, dialect=dialect))
    lines.append(indent + "}")
    return lines


# --------------------------------------------------------------- entity / file


def _serialize_entity(ent: MapEntity, *, dialect: Dialect, projection: Projection,
                      indent: str) -> list[str]:
    lines = ["{"]
    for key, value in ent.properties.items():
        lines.append(f"{indent}{_quote(key)} {_quote(value)}")
    for brush in ent.brushes:
        lines.extend(_serialize_brush(brush, dialect=dialect,
                                      projection=projection, indent=indent))
    lines.append("}")
    return lines


def serialize(mf: MapFile, *, dialect: Dialect = "q1",
              projection: Projection = "auto", indent: str = " ") -> str:
    """Serialize ``mf`` back to ``.map`` text.

    ``dialect`` selects per-game face syntax:

    * ``"q1"`` — standard / Valve220 only; trailing ``contents flags value``
      ints are stripped from face lines.
    * ``"q2"`` — like Q1 but always emits the three trailing ints.
    * ``"q3"`` — like Q1 plus support for ``brushDef3``/``patchDef2`` brushes
      preserved as raw blocks.

    ``projection`` controls Standard vs Valve220 face syntax:

    * ``"auto"`` — per-face: Valve220 syntax for faces with both S/T axes,
      Standard otherwise.
    * ``"standard"`` / ``"valve220"`` — force the chosen mode for every face.
    """
    if dialect not in ("q1", "q2", "q3"):
        raise ValueError(f"unknown dialect {dialect!r}")
    if projection not in ("auto", "standard", "valve220"):
        raise ValueError(f"unknown projection {projection!r}")
    out: list[str] = []
    for ent in mf.entities:
        out.extend(_serialize_entity(ent, dialect=dialect,
                                     projection=projection, indent=indent))
    out.append("")  # trailing newline
    return "\n".join(out)


def serialize_path(mf: MapFile, path: str | Path, **kwargs) -> None:
    """Serialize ``mf`` and atomically replace ``path`` with UTF-8 text."""
    text = serialize(mf, **kwargs)
    destination = Path(path)
    descriptor, temp_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    os.close(descriptor)
    temporary = Path(temp_name)
    try:
        temporary.write_text(text, encoding="utf-8", newline="\n")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
