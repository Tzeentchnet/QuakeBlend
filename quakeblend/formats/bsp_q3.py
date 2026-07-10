"""Quake 3 BSP (IBSP version 46) reader.

Header: ``"IBSP"`` magic + int32 version (46) + 17 lump (offset, size) pairs.

Lump indices:

    0  ENTITIES   1  TEXTURES   2  PLANES     3  NODES
    4  LEAFS      5  LEAFFACES  6  LEAFBRUSHES 7 MODELS
    8  BRUSHES    9  BRUSHSIDES 10 VERTEXES  11 MESHVERTS
   12  EFFECTS   13  FACES      14 LIGHTMAPS 15 LIGHTVOLS  16 VISDATA

Vertex (44 bytes): position (3f), texcoord (2f), lightmap_coord (2f),
                   normal (3f), color (4 uint8).
Face (104 bytes):  texture, effect, type, vertex, n_vertexes, meshvert,
                   n_meshverts, lm_index, lm_start[2], lm_size[2],
                   lm_origin[3], lm_vec0[3], lm_vec1[3], normal[3], size[2].
Face types: 1 = polygon, 2 = patch, 3 = mesh, 4 = billboard.
"""

from __future__ import annotations

import io
import struct
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, List

from ..utils.constants import BSP_VERSION_Q3, IBSP_MAGIC, MAX_PATCH_DIMENSION
from .common import BinaryReader, Vec3, require_finite
from .entities import parse_entities

NUM_LUMPS = 17

LUMP_ENTITIES    = 0
LUMP_TEXTURES    = 1
LUMP_PLANES      = 2
LUMP_NODES       = 3
LUMP_LEAFS       = 4
LUMP_LEAFFACES   = 5
LUMP_LEAFBRUSHES = 6
LUMP_MODELS      = 7
LUMP_BRUSHES     = 8
LUMP_BRUSHSIDES  = 9
LUMP_VERTEXES    = 10
LUMP_MESHVERTS   = 11
LUMP_EFFECTS     = 12
LUMP_FACES       = 13
LUMP_LIGHTMAPS   = 14
LUMP_LIGHTVOLS   = 15
LUMP_VISDATA     = 16

FACE_TYPE_POLY      = 1
FACE_TYPE_PATCH     = 2
FACE_TYPE_MESH      = 3
FACE_TYPE_BILLBOARD = 4

LIGHTMAP_DIM = 128


@dataclass(frozen=True)
class Lump:
    offset: int
    size: int


@dataclass(frozen=True)
class Texture:
    name: str
    flags: int
    contents: int


@dataclass(frozen=True)
class Vertex:
    pos: Vec3
    tex_uv: tuple[float, float]
    lm_uv: tuple[float, float]
    normal: Vec3
    color: tuple[int, int, int, int]


@dataclass(frozen=True)
class Face:
    texture: int
    effect: int
    type: int
    vertex: int
    n_vertexes: int
    meshvert: int
    n_meshverts: int
    lm_index: int
    lm_start: tuple[int, int]
    lm_size: tuple[int, int]
    lm_origin: Vec3
    lm_vec0: Vec3
    lm_vec1: Vec3
    normal: Vec3
    size: tuple[int, int]


@dataclass
class Bsp:
    version: int = BSP_VERSION_Q3
    entities: List[dict] = field(default_factory=list)
    raw_entities: str = ""
    textures: List[Texture] = field(default_factory=list)
    vertices: List[Vertex] = field(default_factory=list)
    meshverts: List[int] = field(default_factory=list)
    faces: List[Face] = field(default_factory=list)
    lightmaps: List[bytes] = field(default_factory=list)

    def validate(self) -> None:
        valid_types = {
            FACE_TYPE_POLY, FACE_TYPE_PATCH, FACE_TYPE_MESH, FACE_TYPE_BILLBOARD,
        }
        for vertex_index, vertex in enumerate(self.vertices):
            require_finite(
                vertex.pos,
                context=f"corrupt BSP: vertex {vertex_index} position",
            )
            require_finite(
                vertex.tex_uv,
                context=f"corrupt BSP: vertex {vertex_index} texture UV",
            )
            require_finite(
                vertex.lm_uv,
                context=f"corrupt BSP: vertex {vertex_index} lightmap UV",
            )
            require_finite(
                vertex.normal,
                context=f"corrupt BSP: vertex {vertex_index} normal",
            )
        for face_index, face in enumerate(self.faces):
            require_finite(
                (*face.lm_origin, *face.lm_vec0, *face.lm_vec1, *face.normal),
                context=f"corrupt BSP: face {face_index} vectors",
            )
            if face.type not in valid_types:
                raise ValueError(
                    f"corrupt BSP: face {face_index} has unknown type {face.type}"
                )
            if not 0 <= face.texture < len(self.textures):
                raise ValueError(
                    f"corrupt BSP: face {face_index} texture {face.texture} "
                    f"out of range (texture_count={len(self.textures)})"
                )
            if face.vertex < 0 or face.n_vertexes < 0:
                raise ValueError(
                    f"corrupt BSP: face {face_index} has negative vertex range"
                )
            if face.vertex + face.n_vertexes > len(self.vertices):
                raise ValueError(
                    f"corrupt BSP: face {face_index} vertex range "
                    f"[{face.vertex}, {face.vertex + face.n_vertexes}) out of range "
                    f"(vertex_count={len(self.vertices)})"
                )
            if face.meshvert < 0 or face.n_meshverts < 0:
                raise ValueError(
                    f"corrupt BSP: face {face_index} has negative meshvert range"
                )
            if face.meshvert + face.n_meshverts > len(self.meshverts):
                raise ValueError(
                    f"corrupt BSP: face {face_index} meshvert range "
                    f"[{face.meshvert}, {face.meshvert + face.n_meshverts}) out of range "
                    f"(meshvert_count={len(self.meshverts)})"
                )
            for relative_index in self.meshverts[
                face.meshvert:face.meshvert + face.n_meshverts
            ]:
                if not 0 <= relative_index < face.n_vertexes:
                    raise ValueError(
                        f"corrupt BSP: face {face_index} meshvert {relative_index} "
                        f"out of relative vertex range (vertex_count={face.n_vertexes})"
                    )
            if (face.type in (FACE_TYPE_POLY, FACE_TYPE_MESH)
                    and face.n_meshverts % 3 != 0):
                raise ValueError(
                    f"corrupt BSP: face {face_index} meshvert count "
                    f"{face.n_meshverts} is not a multiple of 3"
                )
            if face.type == FACE_TYPE_PATCH:
                width, height = face.size
                if (width < 3 or height < 3 or width % 2 == 0 or height % 2 == 0
                        or width > MAX_PATCH_DIMENSION
                        or height > MAX_PATCH_DIMENSION
                        or width * height != face.n_vertexes):
                    raise ValueError(
                        f"corrupt BSP: face {face_index} has invalid patch grid "
                        f"{width}×{height} for {face.n_vertexes} vertices"
                    )
            if face.lm_index != -1 and not 0 <= face.lm_index < len(self.lightmaps):
                raise ValueError(
                    f"corrupt BSP: face {face_index} lightmap {face.lm_index} "
                    f"out of range (lightmap_count={len(self.lightmaps)})"
                )


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


def _read_textures(blob: bytes) -> list[Texture]:
    SIZE = 72
    _warn_trailing_bytes(blob, SIZE)
    n = len(blob) // SIZE
    out: list[Texture] = []
    for i in range(n):
        name_bytes = blob[i * SIZE:i * SIZE + 64]
        end = name_bytes.find(b"\x00")
        if end >= 0:
            name_bytes = name_bytes[:end]
        flags, contents = struct.unpack_from("<ii", blob, i * SIZE + 64)
        out.append(Texture(
            name=name_bytes.decode("ascii", errors="replace"),
            flags=flags, contents=contents,
        ))
    return out


def _read_vertices(blob: bytes) -> list[Vertex]:
    SIZE = 44
    _warn_trailing_bytes(blob, SIZE)
    n = len(blob) // SIZE
    out: list[Vertex] = []
    for i in range(n):
        px, py, pz, su, sv, lu, lv, nx, ny, nz = struct.unpack_from("<10f", blob, i * SIZE)
        r, g, b, a = blob[i * SIZE + 40:i * SIZE + 44]
        out.append(Vertex(
            pos=Vec3(px, py, pz),
            tex_uv=(su, sv),
            lm_uv=(lu, lv),
            normal=Vec3(nx, ny, nz),
            color=(r, g, b, a),
        ))
    return out


def _read_meshverts(blob: bytes) -> list[int]:
    _warn_trailing_bytes(blob, 4)
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}i", blob[:n * 4])) if n else []


def _read_faces(blob: bytes) -> list[Face]:
    SIZE = 104
    _warn_trailing_bytes(blob, SIZE)
    n = len(blob) // SIZE
    out: list[Face] = []
    for i in range(n):
        off = i * SIZE
        (texture, effect, ftype, vertex, n_vertexes, meshvert, n_meshverts,
         lm_index) = struct.unpack_from("<8i", blob, off)
        lm_start = struct.unpack_from("<2i", blob, off + 32)
        lm_size = struct.unpack_from("<2i", blob, off + 40)
        lm_origin = Vec3(*struct.unpack_from("<3f", blob, off + 48))
        lm_vec0 = Vec3(*struct.unpack_from("<3f", blob, off + 60))
        lm_vec1 = Vec3(*struct.unpack_from("<3f", blob, off + 72))
        normal = Vec3(*struct.unpack_from("<3f", blob, off + 84))
        size = struct.unpack_from("<2i", blob, off + 96)
        out.append(Face(
            texture=texture, effect=effect, type=ftype,
            vertex=vertex, n_vertexes=n_vertexes,
            meshvert=meshvert, n_meshverts=n_meshverts,
            lm_index=lm_index,
            lm_start=lm_start, lm_size=lm_size,
            lm_origin=lm_origin, lm_vec0=lm_vec0, lm_vec1=lm_vec1,
            normal=normal, size=size,
        ))
    return out


def _read_lightmaps(blob: bytes) -> list[bytes]:
    SIZE = LIGHTMAP_DIM * LIGHTMAP_DIM * 3
    _warn_trailing_bytes(blob, SIZE)
    n = len(blob) // SIZE
    return [blob[i * SIZE:(i + 1) * SIZE] for i in range(n)]


def read(stream: BinaryIO) -> Bsp:
    data = stream.read()
    r = BinaryReader(io.BytesIO(data))
    magic = r.read(4)
    if magic != IBSP_MAGIC:
        raise ValueError(f"not an IBSP file (magic={magic!r})")
    version = r.s32()
    if version != BSP_VERSION_Q3:
        raise ValueError(f"not a Quake 3 BSP (version={version})")
    lumps = _read_lumps(r)

    bsp = Bsp(version=version)
    raw_ent = _slice(data, lumps[LUMP_ENTITIES]).rstrip(b"\x00").decode(
        "latin-1", errors="replace",
    )
    bsp.raw_entities = raw_ent
    bsp.entities = parse_entities(raw_ent) if raw_ent.strip() else []
    bsp.textures = _read_textures(_slice(data, lumps[LUMP_TEXTURES]))
    bsp.vertices = _read_vertices(_slice(data, lumps[LUMP_VERTEXES]))
    bsp.meshverts = _read_meshverts(_slice(data, lumps[LUMP_MESHVERTS]))
    bsp.faces = _read_faces(_slice(data, lumps[LUMP_FACES]))
    bsp.lightmaps = _read_lightmaps(_slice(data, lumps[LUMP_LIGHTMAPS]))
    return bsp


def read_path(path: str | Path) -> Bsp:
    with open(path, "rb") as fh:
        return read(fh)
