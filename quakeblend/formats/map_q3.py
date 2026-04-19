"""Quake 3 ``.map`` parser.

Reuses the shared text tokenizer from :mod:`map_q1`. Standard brushes,
``brushDef3`` blocks, and ``patchDef2`` blocks are all captured by the
upstream parser; this module re-exports the result and provides helpers
that the import runner uses to materialise patches.
"""

from __future__ import annotations

from . import map_q1 as _q1
from . import patch as patch_mod

parse = _q1.parse
parse_path = _q1.parse_path
MapFile = _q1.MapFile
MapEntity = _q1.MapEntity
MapBrush = _q1.MapBrush
MapFace = _q1.MapFace
TexInfo = _q1.TexInfo


def iter_patches(map_file: MapFile):
    """Yield ``(entity_index, brush_index, texture_name, Patch)`` tuples."""
    for ei, entity in enumerate(map_file.entities):
        for bi, brush in enumerate(entity.brushes):
            if brush.raw_kind == "patchDef2":
                tex, p = patch_mod.parse_patch_def2_block(brush.raw_payload)
                yield ei, bi, tex, p
