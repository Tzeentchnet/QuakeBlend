"""Quake 1 BSP (version 29) reader.

Header layout (little-endian):

    int32   version                  (29 for Q1)
    lump    entities, planes, miptex, vertices, visilist, nodes,
            texinfo, faces, lighting, clipnodes, leaves, lface,
            edges, ledges, models                     (15 lumps × 8 bytes)
    each lump: int32 offset, int32 size

Note: Q1 does NOT use an "IBSP" magic. The first int IS the version. Q2/Q3
do prepend ``IBSP``. The ``read_bsp`` dispatcher in :mod:`bsp` selects this
parser when version == 29.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, List

from .common import BinaryReader, Vec3
from .entities import parse_entities

BSP_VERSION = 29

# Lump indices.
LUMP_ENTITIES   = 0
LUMP_PLANES     = 1
LUMP_MIPTEX     = 2
LUMP_VERTICES   = 3
LUMP_VISIBILITY = 4
LUMP_NODES      = 5
LUMP_TEXINFO    = 6
LUMP_FACES      = 7
LUMP_LIGHTING   = 8
LUMP_CLIPNODES  = 9
LUMP_LEAVES     = 10
LUMP_LFACE      = 11
LUMP_EDGES      = 12
LUMP_LEDGES     = 13
LUMP_MODELS     = 14
NUM_LUMPS       = 15


@dataclass(frozen=True)
class Lump:
    offset: int
    size: int


@dataclass(frozen=True)
class TexInfo:
    s_axis: Vec3
    s_offset: float
    t_axis: Vec3
    t_offset: float
    miptex_index: int
    flags: int


@dataclass(frozen=True)
class MipTexture:
    name: str
    width: int
    height: int
    pixels: bytes  # mip-0 indices (width * height bytes)


@dataclass(frozen=True)
class Edge:
    v0: int
    v1: int


@dataclass(frozen=True)
class Face:
    plane_id: int
    side: int
    ledge_id: int
    ledge_num: int
    texinfo_id: int
    typelight: int
    baselight: int
    light0: int
    light1: int
    lightmap_offset: int


@dataclass
class Bsp:
    version: int = BSP_VERSION
    entities: List[dict] = field(default_factory=list)
    raw_entities: str = ""
    vertices: List[Vec3] = field(default_factory=list)
    edges: List[Edge] = field(default_factory=list)
    ledges: List[int] = field(default_factory=list)   # signed edge indices
    faces: List[Face] = field(default_factory=list)
    texinfos: List[TexInfo] = field(default_factory=list)
    miptextures: List[MipTexture | None] = field(default_factory=list)
    lighting: bytes = b""

    # Built per face: ordered vertex indices forming the face polygon.
    def face_polygon(self, face: Face) -> List[int]:
        verts: list[int] = []
        for k in range(face.ledge_num):
            sledge = self.ledges[face.ledge_id + k]
            edge = self.edges[abs(sledge)]
            v = edge.v0 if sledge >= 0 else edge.v1
            verts.append(v)
        return verts


# -------------------------------------------------------------- entry point


def _read_lumps(r: BinaryReader) -> list[Lump]:
    return [Lump(*r.unpack("ii")) for _ in range(NUM_LUMPS)]


def _slice(data: bytes, lump: Lump) -> bytes:
    return data[lump.offset:lump.offset + lump.size]


def _read_vertices(blob: bytes) -> list[Vec3]:
    r = BinaryReader(io.BytesIO(blob))
    n = len(blob) // 12
    return [r.vec3() for _ in range(n)]


def _read_edges(blob: bytes) -> list[Edge]:
    r = BinaryReader(io.BytesIO(blob))
    n = len(blob) // 4
    return [Edge(*r.unpack("HH")) for _ in range(n)]


def _read_ledges(blob: bytes) -> list[int]:
    r = BinaryReader(io.BytesIO(blob))
    n = len(blob) // 4
    return [r.s32() for _ in range(n)]


def _read_texinfos(blob: bytes) -> list[TexInfo]:
    r = BinaryReader(io.BytesIO(blob))
    n = len(blob) // 40
    out: list[TexInfo] = []
    for _ in range(n):
        sx, sy, sz, soff, tx, ty, tz, toff = r.unpack("ffffffff")
        miptex = r.u32()
        flags = r.u32()
        out.append(TexInfo(
            s_axis=Vec3(sx, sy, sz), s_offset=soff,
            t_axis=Vec3(tx, ty, tz), t_offset=toff,
            miptex_index=miptex, flags=flags,
        ))
    return out


def _read_faces(blob: bytes) -> list[Face]:
    r = BinaryReader(io.BytesIO(blob))
    n = len(blob) // 20
    out: list[Face] = []
    for _ in range(n):
        plane_id, side, ledge_id, ledge_num, texinfo_id, \
            typelight, baselight, light0, light1, lm_offset = r.unpack(
                "HHiHHBBBBi"
            )
        out.append(Face(
            plane_id=plane_id, side=side,
            ledge_id=ledge_id, ledge_num=ledge_num,
            texinfo_id=texinfo_id,
            typelight=typelight, baselight=baselight,
            light0=light0, light1=light1,
            lightmap_offset=lm_offset,
        ))
    return out


def _read_miptex_lump(blob: bytes) -> list[MipTexture | None]:
    if not blob:
        return []
    r = BinaryReader(io.BytesIO(blob))
    count = r.s32()
    offsets = [r.s32() for _ in range(count)]
    out: list[MipTexture | None] = []
    for off in offsets:
        if off < 0 or off >= len(blob):
            out.append(None)
            continue
        sub = blob[off:]
        sr = BinaryReader(io.BytesIO(sub))
        name = sr.fixed_string(16)
        width = sr.u32()
        height = sr.u32()
        mip0_off = sr.u32()
        # Skip the other three mip offsets; we only need full resolution.
        _ = [sr.u32() for _ in range(3)]
        if mip0_off + width * height > len(sub):
            out.append(None)
            continue
        pixels = sub[mip0_off:mip0_off + width * height]
        out.append(MipTexture(name=name, width=width, height=height, pixels=pixels))
    return out


def read(stream: BinaryIO) -> Bsp:
    data = stream.read()
    r = BinaryReader(io.BytesIO(data))
    version = r.s32()
    if version != BSP_VERSION:
        raise ValueError(f"not a Quake 1 BSP (version={version})")
    lumps = _read_lumps(r)

    bsp = Bsp(version=version)
    raw_ent = _slice(data, lumps[LUMP_ENTITIES]).rstrip(b"\x00").decode(
        "latin-1", errors="replace"
    )
    bsp.raw_entities = raw_ent
    bsp.entities = parse_entities(raw_ent) if raw_ent.strip() else []
    bsp.vertices = _read_vertices(_slice(data, lumps[LUMP_VERTICES]))
    bsp.edges = _read_edges(_slice(data, lumps[LUMP_EDGES]))
    bsp.ledges = _read_ledges(_slice(data, lumps[LUMP_LEDGES]))
    bsp.texinfos = _read_texinfos(_slice(data, lumps[LUMP_TEXINFO]))
    bsp.faces = _read_faces(_slice(data, lumps[LUMP_FACES]))
    bsp.miptextures = _read_miptex_lump(_slice(data, lumps[LUMP_MIPTEX]))
    bsp.lighting = _slice(data, lumps[LUMP_LIGHTING])
    return bsp


def read_path(path: str | Path) -> Bsp:
    with open(path, "rb") as fh:
        return read(fh)
