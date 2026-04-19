"""Smoke test for the Quake 1 BSP reader using a tiny synthetic file.

Builds the smallest legal v29 BSP we can: empty geometry lumps + a one-entity
entity lump. This exercises header parsing, lump dispatch and entity decoding.
"""

from __future__ import annotations

import io
import struct

from quakeblend.formats import bsp_q1


def _make_minimal_bsp(entity_text: bytes) -> bytes:
    header_size = 4 + bsp_q1.NUM_LUMPS * 8
    cursor = header_size
    # Layout: only the entity lump has data; everything else is zero-size.
    ent_offset = cursor
    cursor += len(entity_text)

    parts = [struct.pack("<i", bsp_q1.BSP_VERSION)]
    for i in range(bsp_q1.NUM_LUMPS):
        if i == bsp_q1.LUMP_ENTITIES:
            parts.append(struct.pack("<ii", ent_offset, len(entity_text)))
        else:
            parts.append(struct.pack("<ii", header_size, 0))
    return b"".join(parts) + entity_text


def test_minimal_bsp_parses_entities() -> None:
    text = b'{ "classname" "worldspawn" }\n{ "classname" "info_player_start" "origin" "1 2 3" }\n\x00'
    blob = _make_minimal_bsp(text)
    bsp = bsp_q1.read(io.BytesIO(blob))
    assert bsp.version == bsp_q1.BSP_VERSION
    assert len(bsp.entities) == 2
    assert bsp.entities[0]["classname"] == "worldspawn"
    assert bsp.entities[1]["origin"] == "1 2 3"
    assert bsp.vertices == []
    assert bsp.faces == []


def test_wrong_version_rejected() -> None:
    import pytest
    bad = struct.pack("<i", 99) + b"\x00" * (bsp_q1.NUM_LUMPS * 8)
    with pytest.raises(ValueError):
        bsp_q1.read(io.BytesIO(bad))
