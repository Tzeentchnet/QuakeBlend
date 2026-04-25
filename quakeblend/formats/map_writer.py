"""Serialize an in-memory :class:`~quakeblend.formats.map_q1.MapFile` back to
``.map`` text targeting Q1, Q2, or Q3.

Companion to :mod:`quakeblend.formats.map_q1` (parser). For brush-primitive
faces (``brushDef3``) and Bezier patches (``patchDef2``) we delegate to
:mod:`~quakeblend.formats.brushdef3` and :mod:`~quakeblend.formats.patch`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from . import brushdef3 as bd3_mod
from . import patch as patch_mod
from .map_q1 import MapBrush, MapEntity, MapFace, MapFile, TexInfo


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
    return '"' + s.replace('"', '\\"') + '"'


# --------------------------------------------------------------- face text


def _serialize_face_standard(face: MapFace, *, dialect: Dialect) -> str:
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
    tex = face.tex
    if tex.s_axis is None or tex.t_axis is None:
        # Fall back to standard if axes are missing.
        return _serialize_face_standard(face, dialect=dialect)
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
        # Re-parse and re-emit so we round-trip cleanly. ``brush.raw_payload``
        # is preserved verbatim from the original parser.
        try:
            name, patch = patch_mod.parse_patch_def2_block(brush.raw_payload)
        except (ValueError, StopIteration) as exc:
            raise ValueError(f"failed to re-parse patchDef2 payload: {exc}")
        body = patch_mod.serialize_patch_def2(name, patch, indent=indent)
        for line in body.splitlines():
            lines.append(indent + line)
    elif brush.raw_kind in ("brushDef3", "brushDef"):
        body = bd3_mod.serialize_brushdef3(brush, indent=indent)
        for line in body.splitlines():
            lines.append(indent + line)
    elif brush.raw_kind == "patchDef3":
        # Not implemented — preserve verbatim.
        lines.append(indent + "patchDef3")
        lines.append(indent + "{")
        lines.append(brush.raw_payload.rstrip())
        lines.append(indent + "}")
    else:
        face_writer = _choose_face_writer(brush.faces[0], projection) if brush.faces \
            else _serialize_face_standard
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
    """Serialize ``mf`` and write it to ``path`` as UTF-8."""
    text = serialize(mf, **kwargs)
    Path(path).write_text(text, encoding="utf-8", newline="\n")
