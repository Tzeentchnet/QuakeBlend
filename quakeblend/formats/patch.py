"""Quake 3 bicubic Bezier patch tessellation.

A Q3 patch is an ``M × N`` grid of control points where ``M`` and ``N`` are
odd integers ``>= 3``. The grid is composed of ``(M-1)/2`` × ``(N-1)/2``
3×3 bicubic Bezier subpatches sharing edge controls.

For a single 3×3 subpatch ``B`` and a parameter ``t ∈ [0, 1]``:

    P(t) = (1-t)² · B0  +  2(1-t)t · B1  +  t² · B2

Each subpatch is sampled on an ``(L+1)²`` grid (L = subdivision level) and
emitted as a quad strip; the global grid stitches subpatches together
seamlessly because they share controls.

Each control point carries ``(x, y, z, u, v)`` (position + texture coord);
the same Bezier interpolation applies to UVs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence

from .common import Vec3


@dataclass(frozen=True)
class Control:
    pos: Vec3
    uv: tuple[float, float]


@dataclass
class Patch:
    width: int                       # M (odd, >= 3)
    height: int                      # N (odd, >= 3)
    controls: List[Control]          # length = M * N, row-major

    def get(self, x: int, y: int) -> Control:
        return self.controls[y * self.width + x]


@dataclass
class TessellatedPatch:
    vertices: List[Vec3]
    uvs: List[tuple[float, float]]
    quads: List[tuple[int, int, int, int]]


def _bez(t: float, a: float, b: float, c: float) -> float:
    omt = 1.0 - t
    return omt * omt * a + 2.0 * omt * t * b + t * t * c


def _bez_vec(t: float, a: Vec3, b: Vec3, c: Vec3) -> Vec3:
    return Vec3(_bez(t, a.x, b.x, c.x),
                _bez(t, a.y, b.y, c.y),
                _bez(t, a.z, b.z, c.z))


def _bez_uv(t: float, a, b, c) -> tuple[float, float]:
    return (_bez(t, a[0], b[0], c[0]), _bez(t, a[1], b[1], c[1]))


def _evaluate_subpatch(p: Patch, ox: int, oy: int, level: int,
                       verts: list[Vec3], uvs: list[tuple[float, float]],
                       quads: list[tuple[int, int, int, int]]) -> None:
    n = level + 1  # samples per side
    grid_idx = [[0] * n for _ in range(n)]
    # Collect 3×3 control net for this subpatch (positions + UVs).
    pos = [[p.get(ox + i, oy + j).pos for i in range(3)] for j in range(3)]
    uv = [[p.get(ox + i, oy + j).uv for i in range(3)] for j in range(3)]

    for j in range(n):
        t = j / level
        # Interpolate the three Bezier curves down a column → 3 row points.
        row_pos = [_bez_vec(t, pos[0][i], pos[1][i], pos[2][i]) for i in range(3)]
        row_uv = [_bez_uv(t, uv[0][i], uv[1][i], uv[2][i]) for i in range(3)]
        for i in range(n):
            s = i / level
            point = _bez_vec(s, row_pos[0], row_pos[1], row_pos[2])
            tex = _bez_uv(s, row_uv[0], row_uv[1], row_uv[2])
            grid_idx[j][i] = len(verts)
            verts.append(point)
            uvs.append(tex)

    for j in range(level):
        for i in range(level):
            a = grid_idx[j][i]
            b = grid_idx[j][i + 1]
            c = grid_idx[j + 1][i + 1]
            d = grid_idx[j + 1][i]
            quads.append((a, b, c, d))


def tessellate(patch: Patch, level: int = 5) -> TessellatedPatch:
    if patch.width < 3 or patch.height < 3:
        raise ValueError("patch grid must be at least 3×3")
    if patch.width % 2 == 0 or patch.height % 2 == 0:
        raise ValueError("patch grid dimensions must be odd")
    if level < 1:
        raise ValueError("level must be >= 1")

    verts: list[Vec3] = []
    uvs: list[tuple[float, float]] = []
    quads: list[tuple[int, int, int, int]] = []
    sub_w = (patch.width - 1) // 2
    sub_h = (patch.height - 1) // 2
    for sj in range(sub_h):
        for si in range(sub_w):
            _evaluate_subpatch(patch, si * 2, sj * 2, level, verts, uvs, quads)
    return TessellatedPatch(vertices=verts, uvs=uvs, quads=quads)


# ---------------------------------------------------- patchDef2 text parser


def parse_patch_def2_block(payload: str) -> tuple[str, Patch]:
    """Parse the inner body of a ``patchDef2 { ... }`` block.

    The body looks like:

        TEXNAME
        ( WIDTH HEIGHT 0 0 0 )
        (
          ( ( x y z u v ) ( ... ) ... )
          ( ... )
          ...
        )

    Returns ``(texture_name, patch)``.
    """
    tokens = _tokenize(payload)
    # Drop a leading '{' and trailing '}' if present (the upstream MAP tokenizer
    # captures the patch body verbatim, braces and all).
    if tokens and tokens[0] == "{":
        tokens = tokens[1:]
    if tokens and tokens[-1] == "}":
        tokens = tokens[:-1]
    it = iter(tokens)
    name = next(it)
    if next(it) != "(":
        raise ValueError("expected '(' after patch texture name")
    width = int(next(it))
    height = int(next(it))
    # Skip three trailing zeros.
    next(it); next(it); next(it)
    if next(it) != ")":
        raise ValueError("expected ')' closing patch header")
    if next(it) != "(":
        raise ValueError("expected '(' opening control grid")

    controls: list[Control] = [Control(Vec3(0, 0, 0), (0.0, 0.0))] * (width * height)
    for j in range(height):
        if next(it) != "(":
            raise ValueError(f"expected '(' opening row {j}")
        for i in range(width):
            if next(it) != "(":
                raise ValueError(f"expected '(' opening control ({i},{j})")
            x = float(next(it)); y = float(next(it)); z = float(next(it))
            u = float(next(it)); v = float(next(it))
            if next(it) != ")":
                raise ValueError("expected ')' closing control")
            controls[j * width + i] = Control(Vec3(x, y, z), (u, v))
        if next(it) != ")":
            raise ValueError(f"expected ')' closing row {j}")
    if next(it) != ")":
        raise ValueError("expected ')' closing control grid")

    return name, Patch(width=width, height=height, controls=controls)


def _tokenize(text: str) -> list[str]:
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c in "()":
            out.append(c)
            i += 1
            continue
        j = i
        while j < n and text[j] not in " \t\r\n()":
            j += 1
        out.append(text[i:j])
        i = j
    return out
