"""GoldSrc BSP v30 geometry and embedded/external miptexture reader."""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from ..utils.constants import BSP_VERSION_GOLDSRC, MAX_TEXTURE_DIMENSION, MAX_TEXTURE_PIXELS
from . import bsp_q1, wad
from .common import BinaryReader, require_finite
from .entities import parse_entities


@dataclass
class Bsp(bsp_q1.Bsp):
    """Q1-family geometry with separate embedded WAD3 texture payloads.

    ``miptextures`` retains names and dimensions for external references with
    empty pixels. Missing table slots remain ``None``. Only embedded entries
    appear in ``embedded_textures``, keyed by their original texture index.
    """

    version: int = BSP_VERSION_GOLDSRC
    embedded_textures: dict[int, wad.MipTexture] = field(default_factory=dict)

    def validate(self) -> None:
        super().validate()
        for index, model in enumerate(self.models):
            require_finite((*model.mins, *model.maxs, *model.origin),
                           context=f"GoldSrc model {index}")
        for entity in self.entities:
            model = entity.get("model", "")
            if not model.startswith("*"):
                continue
            try:
                index = int(model[1:])
            except ValueError as exc:
                raise ValueError(f"invalid GoldSrc model reference {model!r}") from exc
            if not 0 < index < len(self.models):
                raise ValueError(f"GoldSrc model reference {model!r} out of range")


def _read_textures(blob: bytes) -> tuple[list[bsp_q1.MipTexture | None], dict[int, wad.MipTexture]]:
    if not blob:
        return [], {}
    stream = io.BytesIO(blob)
    reader = BinaryReader(stream)
    count = reader.s32()
    if count < 0:
        raise ValueError("GoldSrc miptexture count must be nonnegative")
    table_end = 4 + count * 4
    if table_end > len(blob):
        raise EOFError("GoldSrc miptexture table exceeds lump")
    offsets = [reader.s32() for _ in range(count)]
    for offset in offsets:
        if offset == -1:
            continue
        if offset < table_end:
            raise ValueError(f"invalid GoldSrc miptexture offset {offset}")
        if offset + 40 > len(blob):
            raise EOFError("GoldSrc miptexture header exceeds lump")
    boundaries = sorted({offset for offset in offsets if offset != -1} | {len(blob)})
    ends = dict(zip(boundaries, boundaries[1:]))
    textures: list[bsp_q1.MipTexture | None] = []
    embedded: dict[int, wad.MipTexture] = {}
    for index, offset in enumerate(offsets):
        if offset == -1:
            textures.append(None)
            continue
        payload_size = ends[offset] - offset
        if payload_size < 40:
            raise EOFError("GoldSrc miptexture headers overlap")
        stream.seek(offset)
        name = reader.fixed_string(16)
        width, height = reader.unpack("II")
        mip_offsets = reader.unpack("4I")
        if not (0 < width <= MAX_TEXTURE_DIMENSION and 0 < height <= MAX_TEXTURE_DIMENSION):
            raise ValueError(f"invalid GoldSrc texture dimensions for {name!r}: {width}x{height}")
        if width * height > MAX_TEXTURE_PIXELS:
            raise ValueError(f"GoldSrc texture {name!r} exceeds pixel limit")
        if mip_offsets[0] == 0:
            if any(mip_offsets):
                raise ValueError(f"partial external GoldSrc miptexture {name!r}")
            textures.append(bsp_q1.MipTexture(name, width, height, b""))
            continue
        previous_end = 40
        for level, mip_offset in enumerate(mip_offsets):
            if mip_offset < previous_end:
                raise ValueError(f"overlapping GoldSrc mip levels for {name!r}")
            previous_end = mip_offset + max(1, width >> level) * max(1, height >> level)
        texture = wad.read_miptex(stream, base_offset=offset, payload_size=payload_size,
                                  expect_palette=True)
        if texture.palette is None:
            raise ValueError(f"missing or invalid GoldSrc palette for {name!r}")
        embedded[index] = texture
        textures.append(bsp_q1.MipTexture(name, width, height, texture.pixels))
    return textures, embedded


def read(stream: BinaryIO) -> Bsp:
    data = stream.read()
    reader = BinaryReader(io.BytesIO(data))
    version = reader.s32()
    if version != BSP_VERSION_GOLDSRC:
        raise ValueError(f"not a GoldSrc BSP (version={version})")
    lumps = bsp_q1._read_lumps(reader)
    header_size = 4 + bsp_q1.NUM_LUMPS * 8
    occupied = []
    for lump in lumps:
        bsp_q1._slice(data, lump)
        if lump.size:
            if lump.offset < header_size:
                raise ValueError("GoldSrc lump overlaps header")
            occupied.append((lump.offset, lump.offset + lump.size))
    occupied.sort()
    if any(left[1] > right[0] for left, right in zip(occupied, occupied[1:])):
        raise ValueError("overlapping GoldSrc lumps")
    for index, record_size in (
        (bsp_q1.LUMP_VERTICES, 12), (bsp_q1.LUMP_EDGES, 4),
        (bsp_q1.LUMP_LEDGES, 4), (bsp_q1.LUMP_TEXINFO, 40),
        (bsp_q1.LUMP_FACES, 20), (bsp_q1.LUMP_MODELS, 64),
    ):
        if lumps[index].size % record_size:
            raise ValueError(f"incomplete GoldSrc record in lump {index}")
    bsp = Bsp()
    bsp.raw_entities = bsp_q1._slice(data, lumps[bsp_q1.LUMP_ENTITIES]).rstrip(b"\x00").decode("latin-1")
    bsp.entities = parse_entities(bsp.raw_entities) if bsp.raw_entities.strip() else []
    bsp.vertices = bsp_q1._read_vertices(bsp_q1._slice(data, lumps[bsp_q1.LUMP_VERTICES]))
    bsp.edges = bsp_q1._read_edges(bsp_q1._slice(data, lumps[bsp_q1.LUMP_EDGES]))
    bsp.ledges = bsp_q1._read_ledges(bsp_q1._slice(data, lumps[bsp_q1.LUMP_LEDGES]))
    bsp.texinfos = bsp_q1._read_texinfos(bsp_q1._slice(data, lumps[bsp_q1.LUMP_TEXINFO]))
    bsp.faces = bsp_q1._read_faces(bsp_q1._slice(data, lumps[bsp_q1.LUMP_FACES]))
    bsp.models = bsp_q1._read_models(bsp_q1._slice(data, lumps[bsp_q1.LUMP_MODELS]))
    bsp.lighting = bsp_q1._slice(data, lumps[bsp_q1.LUMP_LIGHTING])
    bsp.miptextures, bsp.embedded_textures = _read_textures(
        bsp_q1._slice(data, lumps[bsp_q1.LUMP_MIPTEX])
    )
    bsp.validate()
    return bsp


def read_path(path: str | Path) -> Bsp:
    with open(path, "rb") as stream:
        return read(stream)
