"""Tests for ``quakeblend.formats.palette``."""

from __future__ import annotations

import pytest

from quakeblend.formats import palette
from quakeblend.utils.constants import Q1_FULLBRIGHT_RANGE, Q2_FULLBRIGHT_RANGE


def _synthetic_palette() -> palette.Palette:
    rgb = bytes(((i * 3) % 256, (i * 5) % 256, (i * 7) % 256)[c]
                for i in range(256) for c in range(3))
    assert len(rgb) == 768
    return palette.from_bytes(rgb, Q1_FULLBRIGHT_RANGE)


def test_decode_indexed_basic() -> None:
    pal = _synthetic_palette()
    rgba = palette.decode_indexed(bytes([0, 1, 255]), pal, opaque_index=255)
    assert rgba[0:4] == bytes((0, 0, 0, 255))           # idx 0 → palette[0]
    # idx 1 → palette[3..6]
    assert rgba[4:8] == bytes((pal.rgb[3], pal.rgb[4], pal.rgb[5], 255))
    assert rgba[8:12] == bytes((pal.rgb[765], pal.rgb[766], pal.rgb[767], 0))  # transparent


def test_fullbright_mask_only_in_range() -> None:
    pal = _synthetic_palette()
    indices = bytes(range(256))
    mask = palette.fullbright_mask(indices, pal)
    assert len(mask) == 256
    for i, m in enumerate(mask):
        assert (m == 255) == (i in Q1_FULLBRIGHT_RANGE), f"bad mask at index {i}"


def test_palette_validates_length() -> None:
    with pytest.raises(ValueError):
        palette.from_bytes(b"\x00" * 100)


def test_bundled_q1_palette_has_correct_size() -> None:
    pal = palette.load_bundled("q1")
    assert len(pal.rgb) == 768
    assert pal.fullbright_indices == frozenset(Q1_FULLBRIGHT_RANGE)


def test_bundled_q2_palette_has_correct_size() -> None:
    pal = palette.load_bundled("q2")
    assert len(pal.rgb) == 768
    assert pal.fullbright_indices == frozenset(Q2_FULLBRIGHT_RANGE)


def test_unknown_game_raises() -> None:
    with pytest.raises(ValueError):
        palette.load_bundled("doom")
