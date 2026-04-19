"""Quake 1 / 2 palette decoding.

Palettes are 768 raw bytes (256 RGB triplets). The bundled palettes live in
``quakeblend/data/`` and are loaded via :func:`load_bundled`.

Decoding produces RGBA byte buffers in row-major top-down order and a separate
fullbright alpha mask (255 where the source index falls in the fullbright
range, 0 otherwise). Top-down vs. bottom-up flipping for Blender is handled by
the blender layer, not here.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from typing import Iterable

from ..utils.constants import Q1_FULLBRIGHT_RANGE, Q2_FULLBRIGHT_RANGE


@dataclass(frozen=True)
class Palette:
    rgb: bytes  # 768 bytes, 256 * (R,G,B)
    fullbright_indices: frozenset[int]

    def __post_init__(self) -> None:
        if len(self.rgb) != 768:
            raise ValueError(f"palette must be 768 bytes, got {len(self.rgb)}")


def from_bytes(data: bytes, fullbright: Iterable[int] = Q1_FULLBRIGHT_RANGE) -> Palette:
    return Palette(rgb=bytes(data), fullbright_indices=frozenset(fullbright))


def load_bundled(game: str) -> Palette:
    """Return the palette for ``"q1"`` or ``"q2"``."""
    game = game.lower()
    if game == "q1":
        data = resources.files("quakeblend.data").joinpath("palette_q1.lmp").read_bytes()
        return from_bytes(data, Q1_FULLBRIGHT_RANGE)
    if game == "q2":
        data = resources.files("quakeblend.data").joinpath("palette_q2.lmp").read_bytes()
        return from_bytes(data, Q2_FULLBRIGHT_RANGE)
    raise ValueError(f"unknown game {game!r}; expected 'q1' or 'q2'")


def decode_indexed(
    indices: bytes, palette: Palette, *, opaque_index: int | None = 255
) -> bytes:
    """Decode palette-indexed pixels to RGBA bytes.

    If ``opaque_index`` is set, that palette index is treated as fully
    transparent (Quake 1 convention for textures whose name starts with ``{``).
    Pass ``None`` to disable.
    """
    pal = palette.rgb
    out = bytearray(len(indices) * 4)
    for i, idx in enumerate(indices):
        base = idx * 3
        out[i * 4 + 0] = pal[base + 0]
        out[i * 4 + 1] = pal[base + 1]
        out[i * 4 + 2] = pal[base + 2]
        out[i * 4 + 3] = 0 if (opaque_index is not None and idx == opaque_index) else 255
    return bytes(out)


def fullbright_mask(indices: bytes, palette: Palette) -> bytes:
    """Return a single-channel alpha mask: 255 for fullbright pixels, else 0."""
    fb = palette.fullbright_indices
    out = bytearray(len(indices))
    for i, idx in enumerate(indices):
        if idx in fb:
            out[i] = 255
    return bytes(out)


def has_fullbright(indices: bytes, palette: Palette) -> bool:
    fb = palette.fullbright_indices
    return any(b in fb for b in indices)
