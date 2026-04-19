"""Smoke test for the Quake 3 BSP reader."""

from __future__ import annotations

import io
import struct

from quakeblend.formats import bsp_q3


def _make_minimal_bsp(entity_text: bytes) -> bytes:
    header_size = 8 + bsp_q3.NUM_LUMPS * 8
    parts = [b"IBSP", struct.pack("<i", 46)]
    for i in range(bsp_q3.NUM_LUMPS):
        if i == bsp_q3.LUMP_ENTITIES:
            parts.append(struct.pack("<ii", header_size, len(entity_text)))
        else:
            parts.append(struct.pack("<ii", header_size, 0))
    return b"".join(parts) + entity_text


def test_minimal_q3_bsp_parses_entities() -> None:
    text = b'{ "classname" "worldspawn" "music" "music/sonic5" }\n\x00'
    blob = _make_minimal_bsp(text)
    bsp = bsp_q3.read(io.BytesIO(blob))
    assert bsp.version == 46
    assert bsp.entities[0]["music"] == "music/sonic5"
    assert bsp.textures == []
    assert bsp.faces == []
    assert bsp.lightmaps == []


def test_q3_rejects_q2_signature() -> None:
    import pytest
    blob = b"IBSP" + struct.pack("<i", 38) + b"\x00" * (bsp_q3.NUM_LUMPS * 8)
    with pytest.raises(ValueError):
        bsp_q3.read(io.BytesIO(blob))
