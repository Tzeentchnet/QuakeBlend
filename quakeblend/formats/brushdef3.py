"""Quake 3 ``brushDef3`` (a.k.a. brush primitives) parser and serializer.

Face syntax inside a ``brushDef3 { ... }`` block::

    ( nx ny nz d ) ( ( a b c ) ( d e f ) ) TEXNAME contents flags value

Each face stores a plane equation directly (``normal · p = d``) plus a 2×3
texture matrix that maps a 2D projected point — produced from the world-space
position via the standard Quake "base axes" lookup — into ``(s, t)``
normalised texture coordinates::

    proj_x, proj_y = base_project(world_pos, plane.normal)
    s = a * proj_x + b * proj_y + c
    t = d * proj_x + e * proj_y + f

This module keeps the matrix verbatim on :class:`~quakeblend.formats.map_q1.TexInfo.tex_matrix`
so a Q3 → Q3 round-trip is bit-for-bit identical. Lossy conversion to a
Standard face for Q1/Q2 export lives in :mod:`quakeblend.formats.map_convert`.
"""

from __future__ import annotations

import math
from typing import List

from .common import Plane, Vec3
from .map_q1 import MapBrush, MapFace, TexInfo


# ---------------------------------------------------------------- tokenizer


def _tokenize(text: str) -> List[str]:
    out: List[str] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c in "(){}":
            out.append(c)
            i += 1
            continue
        j = i
        while j < n and text[j] not in " \t\r\n(){}":
            j += 1
        out.append(text[i:j])
        i = j
    return out


# ----------------------------------------------------------- base axes table


# Mirror of the idTech ``baseaxis`` lookup used in Q3 brush primitives.
# Each row is ``(reference_normal, s_axis, t_axis)``; the row whose reference
# normal has the largest positive dot with the face normal wins.
_BASE_AXES: tuple[tuple[Vec3, Vec3, Vec3], ...] = (
    (Vec3(0, 0, 1),  Vec3(1, 0, 0),  Vec3(0, -1, 0)),   # floor
    (Vec3(0, 0, -1), Vec3(1, 0, 0),  Vec3(0, -1, 0)),   # ceiling
    (Vec3(1, 0, 0),  Vec3(0, 1, 0),  Vec3(0, 0, -1)),   # west wall
    (Vec3(-1, 0, 0), Vec3(0, 1, 0),  Vec3(0, 0, -1)),   # east wall
    (Vec3(0, 1, 0),  Vec3(1, 0, 0),  Vec3(0, 0, -1)),   # south wall
    (Vec3(0, -1, 0), Vec3(1, 0, 0),  Vec3(0, 0, -1)),   # north wall
)


def base_axes_for_normal(normal: Vec3) -> tuple[Vec3, Vec3]:
    """Return the ``(s_axis, t_axis)`` pair selected by Quake's ``baseaxis``."""
    best_dot = -1.0
    best_s = _BASE_AXES[0][1]
    best_t = _BASE_AXES[0][2]
    for ref, s, t in _BASE_AXES:
        d = normal.dot(ref)
        if d > best_dot:
            best_dot = d
            best_s = s
            best_t = t
    return best_s, best_t


# -------------------------------------------------- plane → three points


def _three_points_from_plane(plane: Plane) -> tuple[Vec3, Vec3, Vec3]:
    """Synthesize three plane points usable for :class:`MapFace`.

    The points are picked so :meth:`Plane.from_points` round-trips back to
    the same normal (within float tolerance).
    """
    n = plane.normal
    # Pick a stable up vector that is not parallel to the normal.
    if abs(n.x) < 0.5 and abs(n.y) < 0.5:
        up = Vec3(1, 0, 0)
    else:
        up = Vec3(0, 0, 1)
    s_axis = up.cross(n).normalized()
    t_axis = n.cross(s_axis).normalized()
    origin = n * plane.dist
    # Scale by 64 so the points land on the typical Quake grid; magnitude
    # does not matter for plane reconstruction but helps editors.
    a = origin
    b = origin + s_axis * 64.0
    c = origin + t_axis * 64.0
    # Quake winding: ``Plane.from_points`` uses ``(c - a) x (b - a)``.
    # Order the three points so the resulting normal matches ``plane.normal``.
    # Try (a, b, c); if the normal flips, swap b and c.
    test = Plane.from_points(a, b, c)
    if test.normal.dot(plane.normal) < 0.0:
        b, c = c, b
    return a, b, c


# ----------------------------------------------------------------- parsing


def parse_brushdef3_block(payload: str) -> MapBrush:
    """Parse the inner body of a ``brushDef3 { ... }`` block."""
    tokens = _tokenize(payload)
    if tokens and tokens[0] == "{":
        tokens = tokens[1:]
    if tokens and tokens[-1] == "}":
        tokens = tokens[:-1]

    faces: List[MapFace] = []
    i = 0
    n = len(tokens)

    def expect(idx: int, want: str) -> int:
        if idx >= n or tokens[idx] != want:
            got = tokens[idx] if idx < n else "<eof>"
            raise ValueError(f"expected {want!r}, got {got!r}")
        return idx + 1

    while i < n:
        # Plane: ( nx ny nz d )
        i = expect(i, "(")
        nx = float(tokens[i]); ny = float(tokens[i + 1])
        nz = float(tokens[i + 2]); dist = float(tokens[i + 3])
        i += 4
        i = expect(i, ")")
        # Texture matrix: ( ( a b c ) ( d e f ) )
        i = expect(i, "(")
        i = expect(i, "(")
        row0 = [float(tokens[i]), float(tokens[i + 1]), float(tokens[i + 2])]
        i += 3
        i = expect(i, ")")
        i = expect(i, "(")
        row1 = [float(tokens[i]), float(tokens[i + 1]), float(tokens[i + 2])]
        i += 3
        i = expect(i, ")")
        i = expect(i, ")")
        # Texture name + optional ``contents flags value``.
        name = tokens[i]
        i += 1
        trailing: List[int] = []
        while i < n and len(trailing) < 3 and tokens[i] != "(":
            tok = tokens[i]
            try:
                trailing.append(
                    int(tok) if "." not in tok and "e" not in tok and "E" not in tok
                    else int(float(tok))
                )
            except ValueError:
                break
            i += 1
        contents = trailing[0] if len(trailing) >= 1 else 0
        surface_flags = trailing[1] if len(trailing) >= 2 else 0
        value = trailing[2] if len(trailing) >= 3 else 0

        plane = Plane(Vec3(nx, ny, nz), dist)
        p1, p2, p3 = _three_points_from_plane(plane)
        tex = TexInfo(
            name=name,
            tex_matrix=((row0[0], row0[1], row0[2]),
                        (row1[0], row1[1], row1[2])),
            contents=contents, surface_flags=surface_flags, value=value,
        )
        faces.append(MapFace(p1=p1, p2=p2, p3=p3, tex=tex))

    return MapBrush(faces=faces, raw_kind="brushDef3", raw_payload=payload)


# --------------------------------------------------------------- serialize


def _fmt_num(x: float) -> str:
    """Format a float compactly (no trailing zeros, no scientific notation)."""
    if x == 0.0:
        return "0"
    if x == int(x) and abs(x) < 1e15:
        return str(int(x))
    return f"{x:.6f}".rstrip("0").rstrip(".")


def _identity_matrix(scale: float = 1.0 / 64.0
                     ) -> tuple[tuple[float, float, float],
                                tuple[float, float, float]]:
    return ((scale, 0.0, 0.0), (0.0, scale, 0.0))


def serialize_brushdef3_face(face: MapFace) -> str:
    plane = face.plane
    n = plane.normal
    d = plane.dist
    if face.tex.tex_matrix is not None:
        m = face.tex.tex_matrix
    else:
        m = _identity_matrix()
    parts = [
        f"( {_fmt_num(n.x)} {_fmt_num(n.y)} {_fmt_num(n.z)} {_fmt_num(d)} )",
        f"( ( {_fmt_num(m[0][0])} {_fmt_num(m[0][1])} {_fmt_num(m[0][2])} )"
        f" ( {_fmt_num(m[1][0])} {_fmt_num(m[1][1])} {_fmt_num(m[1][2])} ) )",
        face.tex.name,
        str(int(face.tex.contents)),
        str(int(face.tex.surface_flags)),
        str(int(face.tex.value)),
    ]
    return " ".join(parts)


def serialize_brushdef3(brush: MapBrush, *, indent: str = "  ") -> str:
    """Emit a ``brushDef3 { ... }`` block (without the outer brush braces)."""
    lines = ["brushDef3", "{"]
    for face in brush.faces:
        lines.append(indent + serialize_brushdef3_face(face))
    lines.append("}")
    return "\n".join(lines)


# ---------------------------------------- brushDef3 → Standard face helper


def to_standard_face(face: MapFace) -> MapFace:
    """Best-effort conversion of a ``brushDef3`` face to a Standard face.

    The 2×3 texture matrix is decomposed into ``(xscale, yscale, rotation,
    xoffset, yoffset)``. Conversion is exact when the matrix is a uniform
    rotation+scale+translate; shear is approximated.
    """
    if face.tex.tex_matrix is None:
        return face
    (a, b, c), (d, e, f) = face.tex.tex_matrix
    # Each matrix row maps base-axes-projected XY into a *normalised* texture
    # coord. The Standard projection stores coords in *texel* units divided by
    # texture size at render time, so the inverse scaling is ``1 / |row|``.
    sx_len = math.hypot(a, b)
    sy_len = math.hypot(d, e)
    xscale = (1.0 / sx_len) if sx_len > 1e-9 else 1.0
    yscale = (1.0 / sy_len) if sy_len > 1e-9 else 1.0
    rotation = math.degrees(math.atan2(b, a)) if sx_len > 1e-9 else 0.0
    # The matrix translation is applied after the linear part, i.e. the
    # un-scaled texel offset is ``c / sx_len`` (and likewise for y).
    xoffset = (c / sx_len) if sx_len > 1e-9 else 0.0
    yoffset = (f / sy_len) if sy_len > 1e-9 else 0.0
    new_tex = TexInfo(
        name=face.tex.name,
        xoffset=xoffset, yoffset=yoffset,
        rotation=rotation,
        xscale=xscale, yscale=yscale,
        contents=face.tex.contents,
        surface_flags=face.tex.surface_flags,
        value=face.tex.value,
    )
    return MapFace(p1=face.p1, p2=face.p2, p3=face.p3, tex=new_tex)
