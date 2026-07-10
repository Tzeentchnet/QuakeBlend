"""Entity-string lexer shared by MAP files and BSP entity lumps.

The text is a sequence of ``{ "key" "value" ... }`` blocks. Whitespace and
``// ...`` line comments are ignored. Keys and values are double-quoted
strings; backslash escapes are honoured.
"""

from __future__ import annotations

import math
from typing import List, Dict

from .common import parse_finite_float


def _skip_whitespace(text: str, i: int) -> int:
    n = len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
        elif c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
        else:
            break
    return i


def _read_quoted(text: str, i: int) -> tuple[str, int]:
    n = len(text)
    if i >= n or text[i] != '"':
        raise ValueError(f"expected '\"' at offset {i}")
    i += 1
    start = i
    out: list[str] = []
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n:
            out.append(text[start:i])
            esc = text[i + 1]
            out.append({"n": "\n", "t": "\t", "\\": "\\", '"': '"'}.get(esc, esc))
            i += 2
            start = i
            continue
        if c == '"':
            out.append(text[start:i])
            return "".join(out), i + 1
        i += 1
    raise ValueError("unterminated quoted string")


def parse_entities(text: str) -> List[Dict[str, str]]:
    """Parse a sequence of entity blocks.

    Returns a list of dicts (insertion-order preserved). Duplicate keys
    overwrite earlier values, matching engine behaviour.
    """
    n = len(text)
    i = 0
    entities: list[dict[str, str]] = []
    while True:
        i = _skip_whitespace(text, i)
        if i >= n:
            break
        if text[i] != "{":
            raise ValueError(f"expected '{{' at offset {i}, got {text[i]!r}")
        i += 1
        ent: dict[str, str] = {}
        while True:
            i = _skip_whitespace(text, i)
            if i >= n:
                raise ValueError("unterminated entity block")
            if text[i] == "}":
                i += 1
                break
            key, i = _read_quoted(text, i)
            i = _skip_whitespace(text, i)
            value, i = _read_quoted(text, i)
            ent[key] = value
        entities.append(ent)
    return entities


def parse_origin(value: str) -> tuple[float, float, float]:
    parts = value.split()
    if len(parts) < 3:
        raise ValueError(f"origin must have 3 components, got {value!r}")
    return tuple(
        parse_finite_float(part, context="origin component")
        for part in parts[:3]
    )  # type: ignore[return-value]


def parse_color(value: str) -> tuple[float, float, float]:
    """Parse either normalized ``0..1`` or byte-range ``0..255`` RGB."""
    parts = value.split()
    if len(parts) < 3:
        raise ValueError(f"color must have 3 components, got {value!r}")
    try:
        components = [float(part) for part in parts[:3]]
    except ValueError as exc:
        raise ValueError(f"color components must be numeric, got {value!r}") from exc
    if not all(math.isfinite(component) for component in components):
        raise ValueError(f"color components must be finite, got {value!r}")
    divisor = 255.0 if any(abs(component) > 1.0 for component in components) else 1.0
    return tuple(
        min(1.0, max(0.0, component / divisor))
        for component in components
    )  # type: ignore[return-value]
