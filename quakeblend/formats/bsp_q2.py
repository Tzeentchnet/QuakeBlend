"""Quake 2 BSP (IBSP version 38) reader.

Header: ``"IBSP"`` magic + int32 version + 19 lump (offset, size) pairs.

Lump indices we care about for import:

    0  ENTITIES   1  PLANES     2  VERTICES   3  VISIBILITY
    4  NODES      5  TEXINFO    6  FACES      7  LIGHTING
    8  LEAFS      9  LEAFFACES 10  LEAFBRUSHES
   11  EDGES     12  SURFEDGES 13  MODELS    14  BRUSHES
   15  BRUSHSIDES 16 POP        17 AREAS     18  AREAPORTALS

Texinfo is 76 bytes:

    float32 u_axis[3]; float32 u_offset;
    float32 v_axis[3]; float32 v_offset;
    int32   flags;     int32   value;
    char[32] texture_name;            // path relative to "textures/", no extension
    int32   next_texinfo;             // -1 or animation chain
"""

from __future__ import annotations

import io
import struct
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, List

from ..utils.constants import BSP_VERSION_Q2, IBSP_MAGIC
from .common import BinaryReader, Vec3, require_finite
from .entities import parse_entities

NUM_LUMPS = 19

LUMP_ENTITIES    = 0
LUMP_PLANES      = 1
LUMP_VERTICES    = 2
LUMP_VISIBILITY  = 3
LUMP_NODES       = 4
LUMP_TEXINFO     = 5
LUMP_FACES       = 6
LUMP_LIGHTING    = 7
LUMP_LEAFS       = 8
LUMP_LEAFFACES   = 9
LUMP_LEAFBRUSHES = 10
LUMP_EDGES       = 11
LUMP_SURFEDGES   = 12
LUMP_MODELS      = 13
LUMP_BRUSHES     = 14
LUMP_BRUSHSIDES  = 15


@dataclass(frozen=True)
class Lump:
    offset: int
    size: int


@dataclass(frozen=True)
class TexInfo:
    u_axis: Vec3
    u_offset: float
    v_axis: Vec3
    v_offset: float
    flags: int
    value: int
    texture_name: str
    next_texinfo: int


@dataclass(frozen=True)
class Edge:
    v0: int
    v1: int


@dataclass(frozen=True)
class Face:
    plane_id: int
    side: int
    first_edge: int
    num_edges: int
    texinfo_id: int
    styles: bytes
    lightmap_offset: int


@dataclass
class Bsp:
    version: int = BSP_VERSION_Q2
    entities: List[dict] = field(default_factory=list)
    raw_entities: str = ""
    vertices: List[Vec3] = field(default_factory=list)
    edges: List[Edge] = field(default_factory=list)
    surfedges: List[int] = field(default_factory=list)  # signed
    faces: List[Face] = field(default_factory=list)
    texinfos: List[TexInfo] = field(default_factory=list)
    lighting: bytes = b""

    def validate(self) -> None:
        for vertex_index, vertex in enumerate(self.vertices):
            require_finite(
                vertex,
                context=f"corrupt BSP: vertex {vertex_index}",
            )
        for texinfo_index, texinfo in enumerate(self.texinfos):
            require_finite(
                (*texinfo.u_axis, texinfo.u_offset,
                 *texinfo.v_axis, texinfo.v_offset),
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
            if face.num_edges < 0:
                raise ValueError(f"corrupt BSP: face {face_index} has negative edge count")
            if (face.first_edge < 0
                    or face.first_edge + face.num_edges > len(self.surfedges)):
                raise ValueError(
                    f"corrupt BSP: face {face_index} surfedge range "
                    f"[{face.first_edge}, {face.first_edge + face.num_edges}) out of range "
                    f"(surfedge_count={len(self.surfedges)})"
                )
            if not 0 <= face.texinfo_id < len(self.texinfos):
                raise ValueError(
                    f"corrupt BSP: face {face_index} texinfo {face.texinfo_id} "
                    f"out of range (texinfo_count={len(self.texinfos)})"
                )
            self.face_polygon(face)
        for texinfo_index, texinfo in enumerate(self.texinfos):
            if (texinfo.next_texinfo != -1
                    and not 0 <= texinfo.next_texinfo < len(self.texinfos)):
                raise ValueError(
                    f"corrupt BSP: texinfo {texinfo_index} next_texinfo "
                    f"{texinfo.next_texinfo} out of range "
                    f"(texinfo_count={len(self.texinfos)})"
                )

    def face_polygon(self, face: Face) -> List[int]:
        verts: list[int] = []
        for k in range(face.num_edges):
            surfedge_idx = face.first_edge + k
            if not 0 <= surfedge_idx < len(self.surfedges):
                raise ValueError(
                    f"corrupt BSP: surfedge index {surfedge_idx} out of range "
                    f"(max {len(self.surfedges) - 1})"
                )
            sedge = self.surfedges[surfedge_idx]
            edge_idx = abs(sedge)
            if not 0 <= edge_idx < len(self.edges):
                raise ValueError(
                    f"corrupt BSP: edge index {edge_idx} out of range "
                    f"(max {len(self.edges) - 1})"
                )
            edge = self.edges[edge_idx]
            vertex_index = edge.v0 if sedge >= 0 else edge.v1
            if not 0 <= vertex_index < len(self.vertices):
                raise ValueError(
                    f"corrupt BSP: vertex index {vertex_index} out of range "
                    f"(max {len(self.vertices) - 1})"
                )
            verts.append(vertex_index)
        return verts


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
    _warn_trailing_bytes(blob, 12)
    n = len(blob) // 12
    out = []
    for i in range(n):
        x, y, z = struct.unpack_from("<fff", blob, i * 12)
        out.append(Vec3(x, y, z))
    return out


def _read_edges(blob: bytes) -> list[Edge]:
    _warn_trailing_bytes(blob, 4)
    n = len(blob) // 4
    return [Edge(*struct.unpack_from("<HH", blob, i * 4)) for i in range(n)]


def _read_surfedges(blob: bytes) -> list[int]:
    _warn_trailing_bytes(blob, 4)
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}i", blob[:n * 4])) if n else []


def _read_faces(blob: bytes) -> list[Face]:
    SIZE = 20  # short, short, int, short, short, byte[4], int
    _warn_trailing_bytes(blob, SIZE)
    n = len(blob) // SIZE
    out: list[Face] = []
    for i in range(n):
        plane_id, side, first_edge, num_edges, texinfo_id = struct.unpack_from(
            "<HHiHH", blob, i * SIZE,
        )
        styles = blob[i * SIZE + 12:i * SIZE + 16]
        lm_offset = struct.unpack_from("<i", blob, i * SIZE + 16)[0]
        out.append(Face(
            plane_id=plane_id, side=side,
            first_edge=first_edge, num_edges=num_edges,
            texinfo_id=texinfo_id,
            styles=bytes(styles),
            lightmap_offset=lm_offset,
        ))
    return out


def _read_texinfos(blob: bytes) -> list[TexInfo]:
    SIZE = 76
    _warn_trailing_bytes(blob, SIZE)
    n = len(blob) // SIZE
    out: list[TexInfo] = []
    for i in range(n):
        ux, uy, uz, uo, vx, vy, vz, vo = struct.unpack_from("<8f", blob, i * SIZE)
        flags, value = struct.unpack_from("<ii", blob, i * SIZE + 32)
        name_bytes = blob[i * SIZE + 40:i * SIZE + 72]
        end = name_bytes.find(b"\x00")
        if end >= 0:
            name_bytes = name_bytes[:end]
        name = name_bytes.decode("ascii", errors="replace")
        next_texinfo = struct.unpack_from("<i", blob, i * SIZE + 72)[0]
        out.append(TexInfo(
            u_axis=Vec3(ux, uy, uz), u_offset=uo,
            v_axis=Vec3(vx, vy, vz), v_offset=vo,
            flags=flags, value=value,
            texture_name=name, next_texinfo=next_texinfo,
        ))
    return out


def read(stream: BinaryIO) -> Bsp:
    data = stream.read()
    r = BinaryReader(io.BytesIO(data))
    magic = r.read(4)
    if magic != IBSP_MAGIC:
        raise ValueError(f"not an IBSP file (magic={magic!r})")
    version = r.s32()
    if version != BSP_VERSION_Q2:
        raise ValueError(f"not a Quake 2 BSP (version={version})")
    lumps = _read_lumps(r)

    bsp = Bsp(version=version)
    raw_ent = _slice(data, lumps[LUMP_ENTITIES]).rstrip(b"\x00").decode(
        "latin-1", errors="replace",
    )
    bsp.raw_entities = raw_ent
    bsp.entities = parse_entities(raw_ent) if raw_ent.strip() else []
    bsp.vertices = _read_vertices(_slice(data, lumps[LUMP_VERTICES]))
    bsp.edges = _read_edges(_slice(data, lumps[LUMP_EDGES]))
    bsp.surfedges = _read_surfedges(_slice(data, lumps[LUMP_SURFEDGES]))
    bsp.faces = _read_faces(_slice(data, lumps[LUMP_FACES]))
    bsp.texinfos = _read_texinfos(_slice(data, lumps[LUMP_TEXINFO]))
    bsp.lighting = _slice(data, lumps[LUMP_LIGHTING])
    return bsp


def read_path(path: str | Path) -> Bsp:
    with open(path, "rb") as fh:
        return read(fh)
