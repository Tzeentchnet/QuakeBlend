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
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, List

from ..utils.constants import MAX_TEXTURE_DIMENSION, MAX_TEXTURE_PIXELS
from .common import BinaryReader, Vec3, require_finite
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

    def validate(self) -> None:
        for vertex_index, vertex in enumerate(self.vertices):
            require_finite(
                vertex,
                context=f"corrupt BSP: vertex {vertex_index}",
            )
        for texinfo_index, texinfo in enumerate(self.texinfos):
            require_finite(
                (*texinfo.s_axis, texinfo.s_offset,
                 *texinfo.t_axis, texinfo.t_offset),
                context=f"corrupt BSP: texinfo {texinfo_index} projection",
            )
        for edge_index, edge in enumerate(self.edges):
            for vertex_index in (edge.v0, edge.v1):
                if not 0 <= vertex_index < len(self.vertices):
                    raise ValueError(
                        f"corrupt BSP: edge {edge_index} vertex {vertex_index} "
                        f"out of range (vertex_count={len(self.vertices)})"
                    )
        for face_index, face in enumerate(self.faces):
            if face.ledge_num < 0:
                raise ValueError(f"corrupt BSP: face {face_index} has negative edge count")
            if face.ledge_id < 0 or face.ledge_id + face.ledge_num > len(self.ledges):
                raise ValueError(
                    f"corrupt BSP: face {face_index} ledge range "
                    f"[{face.ledge_id}, {face.ledge_id + face.ledge_num}) out of range "
                    f"(ledge_count={len(self.ledges)})"
                )
            if not 0 <= face.texinfo_id < len(self.texinfos):
                raise ValueError(
                    f"corrupt BSP: face {face_index} texinfo {face.texinfo_id} "
                    f"out of range (texinfo_count={len(self.texinfos)})"
                )
            self.face_polygon(face)
        for texinfo_index, texinfo in enumerate(self.texinfos):
            if (texinfo.miptex_index != 0xFFFFFFFF
                    and not 0 <= texinfo.miptex_index < len(self.miptextures)):
                raise ValueError(
                    f"corrupt BSP: texinfo {texinfo_index} miptex "
                    f"{texinfo.miptex_index} out of range "
                    f"(miptex_count={len(self.miptextures)})"
                )

    # Built per face: ordered vertex indices forming the face polygon.
    def face_polygon(self, face: Face) -> List[int]:
        verts: list[int] = []
        for k in range(face.ledge_num):
            ledge_idx = face.ledge_id + k
            if not 0 <= ledge_idx < len(self.ledges):
                raise ValueError(
                    f"corrupt BSP: ledge index {ledge_idx} out of range "
                    f"(max {len(self.ledges) - 1})"
                )
            sledge = self.ledges[ledge_idx]
            edge_idx = abs(sledge)
            if not 0 <= edge_idx < len(self.edges):
                raise ValueError(
                    f"corrupt BSP: edge index {edge_idx} out of range "
                    f"(max {len(self.edges) - 1})"
                )
            edge = self.edges[edge_idx]
            v = edge.v0 if sledge >= 0 else edge.v1
            if not 0 <= v < len(self.vertices):
                raise ValueError(
                    f"corrupt BSP: vertex index {v} out of range "
                    f"(max {len(self.vertices) - 1})"
                )
            verts.append(v)
        return verts


# -------------------------------------------------------------- entry point


def _read_lumps(r: BinaryReader) -> list[Lump]:
    return [Lump(*r.unpack("ii")) for _ in range(NUM_LUMPS)]


def _slice(data: bytes, lump: Lump) -> bytes:
    if lump.offset < 0 or lump.size < 0:
        raise ValueError(
            f"invalid BSP lump bounds: offset={lump.offset}, size={lump.size}"
        )
    if lump.offset > len(data):
        raise ValueError(
            f"BSP lump offset {lump.offset} beyond end of file ({len(data)} bytes)"
        )
    end = lump.offset + lump.size
    if end > len(data):
        raise EOFError(
            f"truncated BSP lump: offset={lump.offset}, size={lump.size}, "
            f"file_size={len(data)}"
        )
    return data[lump.offset:lump.offset + lump.size]


def _warn_trailing_bytes(blob: bytes, size: int) -> None:
    leftover = len(blob) % size
    if leftover:
        warnings.warn(
            f"BSP lump has {leftover} trailing bytes (possible corruption)",
            stacklevel=2,
        )


def _read_vertices(blob: bytes) -> list[Vec3]:
    r = BinaryReader(io.BytesIO(blob))
    _warn_trailing_bytes(blob, 12)
    n = len(blob) // 12
    return [r.vec3() for _ in range(n)]


def _read_edges(blob: bytes) -> list[Edge]:
    r = BinaryReader(io.BytesIO(blob))
    _warn_trailing_bytes(blob, 4)
    n = len(blob) // 4
    return [Edge(*r.unpack("HH")) for _ in range(n)]


def _read_ledges(blob: bytes) -> list[int]:
    r = BinaryReader(io.BytesIO(blob))
    _warn_trailing_bytes(blob, 4)
    n = len(blob) // 4
    return [r.s32() for _ in range(n)]


def _read_texinfos(blob: bytes) -> list[TexInfo]:
    r = BinaryReader(io.BytesIO(blob))
    _warn_trailing_bytes(blob, 40)
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
    _warn_trailing_bytes(blob, 20)
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
    if count < 0:
        raise ValueError(f"miptex count must be nonnegative, got {count}")
    if count > (len(blob) - 4) // 4:
        raise EOFError(
            f"miptex offset table exceeds lump: count={count}, lump_size={len(blob)}"
        )
    offsets = [r.s32() for _ in range(count)]
    out: list[MipTexture | None] = []
    for off in offsets:
        if off == -1:
            out.append(None)
            continue
        if off < 0:
            raise ValueError(f"invalid miptex offset {off}")
        if off + 40 > len(blob):
            raise EOFError(
                f"miptex header exceeds lump: offset={off}, lump_size={len(blob)}"
            )
        sub = blob[off:]
        sr = BinaryReader(io.BytesIO(sub))
        name = sr.fixed_string(16)
        width = sr.u32()
        height = sr.u32()
        mip0_off = sr.u32()
        # Skip the other three mip offsets; we only need full resolution.
        _ = [sr.u32() for _ in range(3)]
        if width == 0 or height == 0:
            raise ValueError(
                f"miptex {name!r} dimensions must be positive, got {width}×{height}"
            )
        if width > MAX_TEXTURE_DIMENSION or height > MAX_TEXTURE_DIMENSION:
            raise ValueError(
                f"miptex {name!r} dimensions exceed {MAX_TEXTURE_DIMENSION}: "
                f"{width}×{height}"
            )
        if width * height > MAX_TEXTURE_PIXELS:
            raise ValueError(f"miptex {name!r} pixel count is too large")
        if mip0_off == 0:
            out.append(None)
            continue
        if mip0_off < 40:
            raise ValueError(
                f"miptex {name!r} mip offset {mip0_off} points inside its header"
            )
        if mip0_off + width * height > len(sub):
            raise EOFError(
                f"miptex {name!r} pixels exceed lump: offset={mip0_off}, "
                f"size={width * height}, available={len(sub)}"
            )
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
