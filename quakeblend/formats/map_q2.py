"""Quake 2 ``.map`` parser.

Quake 2 maps share the standard Quake 1 face syntax but extend it with three
trailing integer fields per face:

    ( p1 ) ( p2 ) ( p3 ) TEXNAME xoff yoff rot xscale yscale  contents flags value

The shared :mod:`quakeblend.formats.map_q1` tokenizer already accepts these
trailing tokens (see ``_parse_face``). This module re-exports the parser as
``parse``/``parse_path`` so the import dispatcher has a per-game module to
target.
"""

from __future__ import annotations

from . import map_q1 as _q1

parse = _q1.parse
parse_path = _q1.parse_path
detect_game = _q1.detect_game
MapFile = _q1.MapFile
MapEntity = _q1.MapEntity
MapBrush = _q1.MapBrush
MapFace = _q1.MapFace
TexInfo = _q1.TexInfo
