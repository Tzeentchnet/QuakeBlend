"""Shared primitives for the formats layer.

Pure Python, no external dependencies. ``Vec3`` is intentionally a small
hand-rolled type so the parsers do not need ``mathutils`` (which is only
available inside Blender).
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import BinaryIO, Iterable


@dataclass(frozen=True)
class Vec3:
    x: float
    y: float
    z: float

    # ------------------------------------------------------------------ ops
    def __add__(self, other: "Vec3") -> "Vec3":
        return Vec3(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: "Vec3") -> "Vec3":
        return Vec3(self.x - other.x, self.y - other.y, self.z - other.z)

    def __mul__(self, scalar: float) -> "Vec3":
        return Vec3(self.x * scalar, self.y * scalar, self.z * scalar)

    __rmul__ = __mul__

    def __neg__(self) -> "Vec3":
        return Vec3(-self.x, -self.y, -self.z)

    def __iter__(self):
        yield self.x
        yield self.y
        yield self.z

    # ----------------------------------------------------------------- math
    def dot(self, other: "Vec3") -> float:
        return self.x * other.x + self.y * other.y + self.z * other.z

    def cross(self, other: "Vec3") -> "Vec3":
        return Vec3(
            self.y * other.z - self.z * other.y,
            self.z * other.x - self.x * other.z,
            self.x * other.y - self.y * other.x,
        )

    def length(self) -> float:
        return math.sqrt(self.dot(self))

    def normalized(self) -> "Vec3":
        n = self.length()
        if n == 0.0:
            return Vec3(0.0, 0.0, 0.0)
        return Vec3(self.x / n, self.y / n, self.z / n)

    def as_tuple(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.z)


@dataclass(frozen=True)
class Plane:
    """Half-space defined by ``normal . p >= dist``.

    Stored as a unit normal + signed distance from the origin.
    """

    normal: Vec3
    dist: float

    @classmethod
    def from_points(cls, a: Vec3, b: Vec3, c: Vec3) -> "Plane":
        # Quake winding: face normal points away from the brush solid.
        # Standard CCW order in screen space → use (b-a) x (c-a) flipped to match
        # the original Quake compilers, which use (c-a) x (b-a).
        normal = (c - a).cross(b - a).normalized()
        dist = normal.dot(a)
        return cls(normal, dist)

    def signed_distance(self, p: Vec3) -> float:
        return self.normal.dot(p) - self.dist


# ---------------------------------------------------------------------- IO


class BinaryReader:
    """Tiny endian-aware reader wrapping a seekable binary stream."""

    def __init__(self, stream: BinaryIO, *, little_endian: bool = True) -> None:
        self._s = stream
        self._e = "<" if little_endian else ">"

    # ------------------------------------------------------------ position
    def tell(self) -> int:
        return self._s.tell()

    def seek(self, offset: int, whence: int = 0) -> None:
        self._s.seek(offset, whence)

    def read(self, n: int) -> bytes:
        data = self._s.read(n)
        if len(data) != n:
            raise EOFError(f"expected {n} bytes, got {len(data)}")
        return data

    # ------------------------------------------------------------ scalars
    def u8(self) -> int:
        return self.read(1)[0]

    def s8(self) -> int:
        return struct.unpack(self._e + "b", self.read(1))[0]

    def u16(self) -> int:
        return struct.unpack(self._e + "H", self.read(2))[0]

    def s16(self) -> int:
        return struct.unpack(self._e + "h", self.read(2))[0]

    def u32(self) -> int:
        return struct.unpack(self._e + "I", self.read(4))[0]

    def s32(self) -> int:
        return struct.unpack(self._e + "i", self.read(4))[0]

    def f32(self) -> float:
        return struct.unpack(self._e + "f", self.read(4))[0]

    # ---------------------------------------------------------- aggregates
    def vec3(self) -> Vec3:
        return Vec3(self.f32(), self.f32(), self.f32())

    def fixed_string(self, length: int, encoding: str = "ascii") -> str:
        raw = self.read(length)
        end = raw.find(b"\x00")
        if end >= 0:
            raw = raw[:end]
        return raw.decode(encoding, errors="replace")

    def unpack(self, fmt: str) -> tuple:
        fmt = self._e + fmt
        size = struct.calcsize(fmt)
        return struct.unpack(fmt, self.read(size))

    def iter_struct(self, fmt: str, count: int) -> Iterable[tuple]:
        fmt_e = self._e + fmt
        size = struct.calcsize(fmt_e)
        for _ in range(count):
            yield struct.unpack(fmt_e, self.read(size))


def read_exact(stream: BinaryIO, n: int) -> bytes:
    """Read exactly *n* bytes from *stream*, raising on short reads."""
    data = stream.read(n)
    if len(data) != n:
        raise EOFError(f"expected {n} bytes, got {len(data)}")
    return data


def chunks(seq: bytes, size: int) -> Iterable[bytes]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]
