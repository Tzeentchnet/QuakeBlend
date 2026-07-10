"""Quake 1 / 2 / 3 ``.map`` text format parser.

A ``.map`` file is a sequence of entity blocks. Each entity is a brace-bound
block with key/value pairs and zero or more brushes:

    {
      "classname" "worldspawn"
      // brush
      {
        ( -64 -64 -16 ) ( -64 -63 -16 ) ( -64 -64 -15 ) BRICK1_1 0 0 0 1 1
        ...
      }
    }

Two face syntaxes are supported here:

* **Standard** (Quake 1, Quake 2):
  ``( p1 ) ( p2 ) ( p3 ) TEXNAME xoff yoff rot xscale yscale``
  with optional trailing surface-flags / contents / value (Quake 2).
* **Valve220** (TrenchBroom, Half-Life, Quake 2/3 modern editors):
  ``( p1 ) ( p2 ) ( p3 ) TEXNAME [ ax ay az aoff ] [ bx by bz boff ] rot xscale yscale``
  where the bracketed vectors are the texture S/T axes in world space.

Quake 3 ``brushDef3`` (``( p1 ) ( p2 ) ( p3 ) ( ( aa ab ac ) ( ba bb bc ) )
TEXNAME``) and ``patchDef2`` blocks are detected and stored verbatim for the
Q3 module to pick up; this base parser raises if asked to interpret them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from ..utils.constants import MAX_BRUSH_FACES
from .common import Plane, Vec3, parse_finite_float


# ----------------------------------------------------------------- dataclasses


@dataclass(frozen=True)
class TexInfo:
    name: str
    # Standard projection:
    xoffset: float = 0.0
    yoffset: float = 0.0
    rotation: float = 0.0
    xscale: float = 1.0
    yscale: float = 1.0
    # Valve220 projection (None for standard):
    s_axis: Optional[Vec3] = None
    s_offset: float = 0.0
    t_axis: Optional[Vec3] = None
    t_offset: float = 0.0
    # Q2 trailing fields (optional):
    surface_flags: int = 0
    contents: int = 0
    value: int = 0
    has_q2_trailing_fields: bool = False
    # Q3 brushDef3 2×3 texture matrix (None unless this came from brushDef3).
    # Stored as ((a, b, c), (d, e, f)); see ``quakeblend.formats.brushdef3``.
    tex_matrix: Optional[
        tuple[tuple[float, float, float], tuple[float, float, float]]
    ] = None

    @property
    def is_valve220(self) -> bool:
        return self.s_axis is not None and self.t_axis is not None

    @property
    def is_brushdef3(self) -> bool:
        return self.tex_matrix is not None


@dataclass(frozen=True)
class MapFace:
    p1: Vec3
    p2: Vec3
    p3: Vec3
    tex: TexInfo

    @property
    def plane(self) -> Plane:
        return Plane.from_points(self.p1, self.p2, self.p3)


@dataclass
class MapBrush:
    faces: List[MapFace] = field(default_factory=list)
    # Raw token stream for unsupported brush flavours (brushDef3, patchDef2).
    raw_kind: str = "standard"      # "standard" | "brushDef3" | "patchDef2"
    raw_payload: str = ""


@dataclass
class MapEntity:
    properties: dict[str, str] = field(default_factory=dict)
    brushes: List[MapBrush] = field(default_factory=list)


@dataclass
class MapFile:
    entities: List[MapEntity] = field(default_factory=list)


# ---------------------------------------------------------------- tokenizer


class _Tokenizer:
    """Stream tokenizer for Quake .map files."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.i = 0
        self.n = len(text)

    def _skip_ws(self) -> None:
        while self.i < self.n:
            c = self.text[self.i]
            if c in " \t\r\n":
                self.i += 1
            elif c == "/" and self.i + 1 < self.n and self.text[self.i + 1] == "/":
                while self.i < self.n and self.text[self.i] != "\n":
                    self.i += 1
            elif c == "/" and self.i + 1 < self.n and self.text[self.i + 1] == "*":
                self.i += 2
                while self.i + 1 < self.n and not (
                    self.text[self.i] == "*" and self.text[self.i + 1] == "/"
                ):
                    self.i += 1
                self.i = min(self.n, self.i + 2)
            else:
                break

    def peek(self) -> str | None:
        self._skip_ws()
        if self.i >= self.n:
            return None
        return self.text[self.i]

    def next(self) -> str:
        """Return the next whitespace-separated token (or quoted string)."""
        self._skip_ws()
        if self.i >= self.n:
            raise ValueError("unexpected end of file")
        c = self.text[self.i]
        if c == '"':
            self.i += 1
            start = self.i
            out: list[str] = []
            while self.i < self.n:
                char = self.text[self.i]
                if char == "\\" and self.i + 1 < self.n:
                    out.append(self.text[start:self.i])
                    escaped = self.text[self.i + 1]
                    out.append(
                        {"n": "\n", "t": "\t", "\\": "\\", '"': '"'}.get(
                            escaped, escaped
                        )
                    )
                    self.i += 2
                    start = self.i
                    continue
                if char == '"':
                    out.append(self.text[start:self.i])
                    self.i += 1
                    return "".join(out)
                self.i += 1
            raise ValueError("unterminated quoted string")
        if c in "(){}[]":
            self.i += 1
            return c
        j = self.i
        while j < self.n and self.text[j] not in ' \t\r\n(){}[]"':
            j += 1
        tok = self.text[self.i:j]
        self.i = j
        return tok

    def expect(self, tok: str) -> None:
        got = self.next()
        if got != tok:
            raise ValueError(f"expected {tok!r}, got {got!r} at offset {self.i}")

    def at_end(self) -> bool:
        self._skip_ws()
        return self.i >= self.n

    def capture_braced_block(self, kind: str) -> str:
        self._skip_ws()
        if self.i >= self.n or self.text[self.i] != "{":
            raise ValueError(f"expected '{{' opening {kind} block")
        start = self.i
        depth = 0
        while self.i < self.n:
            char = self.text[self.i]
            if char == '"':
                self.i += 1
                while self.i < self.n:
                    if self.text[self.i] == "\\" and self.i + 1 < self.n:
                        self.i += 2
                        continue
                    if self.text[self.i] == '"':
                        self.i += 1
                        break
                    self.i += 1
                continue
            if char == "/" and self.i + 1 < self.n:
                following = self.text[self.i + 1]
                if following == "/":
                    self.i += 2
                    while self.i < self.n and self.text[self.i] != "\n":
                        self.i += 1
                    continue
                if following == "*":
                    self.i += 2
                    while self.i + 1 < self.n and self.text[self.i:self.i + 2] != "*/":
                        self.i += 1
                    if self.i + 1 >= self.n:
                        raise ValueError(f"unterminated {kind} block")
                    self.i += 2
                    continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    self.i += 1
                    return self.text[start:self.i]
            self.i += 1
        raise ValueError(f"unterminated {kind} block")


# ---------------------------------------------------------------- parsing


def _parse_vec3(t: _Tokenizer) -> Vec3:
    t.expect("(")
    x = parse_finite_float(t.next(), context="plane coordinate")
    y = parse_finite_float(t.next(), context="plane coordinate")
    z = parse_finite_float(t.next(), context="plane coordinate")
    t.expect(")")
    return Vec3(x, y, z)


def _parse_valve_axis(t: _Tokenizer) -> tuple[Vec3, float]:
    t.expect("[")
    x = parse_finite_float(t.next(), context="Valve220 axis")
    y = parse_finite_float(t.next(), context="Valve220 axis")
    z = parse_finite_float(t.next(), context="Valve220 axis")
    off = parse_finite_float(t.next(), context="Valve220 offset")
    t.expect("]")
    return Vec3(x, y, z), off


def _parse_face(t: _Tokenizer) -> MapFace:
    p1 = _parse_vec3(t)
    p2 = _parse_vec3(t)
    p3 = _parse_vec3(t)
    name = t.next()

    nxt = t.peek()
    s_axis = t_axis = None
    s_off = t_off = 0.0
    if nxt == "[":
        s_axis, s_off = _parse_valve_axis(t)
        t_axis, t_off = _parse_valve_axis(t)
        rot = parse_finite_float(t.next(), context="texture rotation")
        xs = parse_finite_float(t.next(), context="texture scale")
        ys = parse_finite_float(t.next(), context="texture scale")
    else:
        xoff = parse_finite_float(t.next(), context="texture offset")
        yoff = parse_finite_float(t.next(), context="texture offset")
        rot = parse_finite_float(t.next(), context="texture rotation")
        xs = parse_finite_float(t.next(), context="texture scale")
        ys = parse_finite_float(t.next(), context="texture scale")

    # Q2 trailing tokens are optional and numeric: ``contents surface_flags value``.
    # See ``map_q2.py`` for the canonical order; matches Quake 2 ``.map`` syntax.
    trailing: list[int] = []
    while len(trailing) < 3:
        peek = t.peek()
        if peek is None or peek in "({[":
            break
        save = t.i
        try:
            tok = t.next()
            num = int(tok) if "." not in tok and "e" not in tok and "E" not in tok else int(float(tok))
        except (ValueError, IndexError):
            t.i = save
            break
        trailing.append(num)
    contents = trailing[0] if len(trailing) >= 1 else 0
    surface = trailing[1] if len(trailing) >= 2 else 0
    value = trailing[2] if len(trailing) >= 3 else 0

    if s_axis is not None and t_axis is not None:
        tex = TexInfo(
            name=name,
            s_axis=s_axis, s_offset=s_off,
            t_axis=t_axis, t_offset=t_off,
            rotation=rot, xscale=xs, yscale=ys,
            surface_flags=surface, contents=contents, value=value,
            has_q2_trailing_fields=bool(trailing),
        )
    else:
        tex = TexInfo(
            name=name, xoffset=xoff, yoffset=yoff,
            rotation=rot, xscale=xs, yscale=ys,
            surface_flags=surface, contents=contents, value=value,
            has_q2_trailing_fields=bool(trailing),
        )

    return MapFace(p1=p1, p2=p2, p3=p3, tex=tex)


def _parse_brush(t: _Tokenizer) -> MapBrush:
    """Brush body is between ``{`` and ``}``."""
    brush = MapBrush()
    while True:
        peek = t.peek()
        if peek is None:
            raise ValueError("unterminated brush")
        if peek == "}":
            t.next()
            return brush
        if peek == "(":
            if len(brush.faces) >= MAX_BRUSH_FACES:
                raise ValueError(
                    f"brush exceeds maximum face count {MAX_BRUSH_FACES}"
                )
            brush.faces.append(_parse_face(t))
            continue
        # Q3 brush primitives / patches start with an identifier token.
        word = t.next()
        if word in ("brushDef", "brushDef3", "patchDef2", "patchDef3"):
            brush.raw_kind = word
            brush.raw_payload = t.capture_braced_block(word)
            t.expect("}")
            return brush
        raise ValueError(f"unrecognised brush token {word!r}")


def _parse_entity(t: _Tokenizer) -> MapEntity:
    ent = MapEntity()
    while True:
        peek = t.peek()
        if peek is None:
            raise ValueError("unterminated entity")
        if peek == "}":
            t.next()
            return ent
        if peek == "{":
            t.next()
            ent.brushes.append(_parse_brush(t))
            continue
        # Otherwise key-value pair (both quoted strings).
        key = t.next()
        value = t.next()
        ent.properties[key] = value


def parse(text: str) -> MapFile:
    """Parse a Quake ``.map`` source string."""
    t = _Tokenizer(text)
    mf = MapFile()
    while not t.at_end():
        t.expect("{")
        mf.entities.append(_parse_entity(t))
    return mf


def parse_path(path: str | Path) -> MapFile:
    return parse(Path(path).read_text(encoding="latin-1"))


def detect_game(map_file: MapFile) -> str:
    """Detect the MAP dialect from syntax that survives parsing."""
    brushes = (brush for entity in map_file.entities for brush in entity.brushes)
    if any(
        brush.raw_kind in ("brushDef3", "brushDef", "patchDef2", "patchDef3")
        for brush in brushes
    ):
        return "q3"
    if any(
        face.tex.has_q2_trailing_fields
        for entity in map_file.entities
        for brush in entity.brushes
        for face in brush.faces
    ):
        return "q2"
    return "q1"
