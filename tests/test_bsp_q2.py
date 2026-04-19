"""Smoke test for the Quake 2 BSP reader using a tiny synthetic file."""

from __future__ import annotations

import io
import struct

from quakeblend.formats import bsp_q2


def _make_minimal_bsp(entity_text: bytes) -> bytes:
    header_size = 8 + bsp_q2.NUM_LUMPS * 8  # IBSP + version + lumps
    ent_offset = header_size
    parts = [b"IBSP", struct.pack("<i", bsp_q2.BSP_VERSION_Q2 if False else 38)]
    # Build all 19 lumps; only entities lump has data.
    for i in range(bsp_q2.NUM_LUMPS):
        if i == bsp_q2.LUMP_ENTITIES:
            parts.append(struct.pack("<ii", ent_offset, len(entity_text)))
        else:
            parts.append(struct.pack("<ii", header_size, 0))
    return b"".join(parts) + entity_text


def test_minimal_q2_bsp_parses_entities() -> None:
    text = b'{ "classname" "worldspawn" "sky" "unit1_" }\n{ "classname" "info_player_start" "origin" "0 0 24" }\n\x00'
    blob = _make_minimal_bsp(text)
    bsp = bsp_q2.read(io.BytesIO(blob))
    assert bsp.version == 38
    assert len(bsp.entities) == 2
    assert bsp.entities[0]["classname"] == "worldspawn"
    assert bsp.entities[0]["sky"] == "unit1_"
    assert bsp.entities[1]["origin"] == "0 0 24"


def test_q2_rejects_q1_signature() -> None:
    import pytest
    blob = struct.pack("<i", 29) + b"\x00" * (15 * 8)
    with pytest.raises(ValueError):
        bsp_q2.read(io.BytesIO(blob))
