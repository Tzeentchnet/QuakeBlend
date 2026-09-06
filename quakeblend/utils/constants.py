"""Project-wide constants for QuakeBlend.

No bpy imports; safe to use from the formats layer.
"""

from __future__ import annotations

import math

# Default world-unit scale. 1 Quake unit ≈ 1 inch ≈ 0.0254 m, but the community
# standard for Blender import is 1/32 (32 units = 1 Blender meter), matching the
# reference implementations.
DEFAULT_IMPORT_SCALE: float = 1.0 / 32.0

# CSG plane-intersection epsilon used when classifying candidate vertices as
# inside the brush half-space arrangement.
CSG_EPSILON: float = 1e-5

# Quake "light" values are an intensity in Quake-unit space falling off as
# 1/d^2; Blender point lights are watts falling off as P/(4*pi*d^2) in metres.
# Equating the two gives P = 4*pi * light * scale^2, so a default 300-unit
# light at the 1/32 import scale lands near 3.7 W instead of a blinding 300 W.
QUAKE_LIGHT_TO_WATTS: float = 4.0 * math.pi

# Fallback brightness for a light entity with no "light"/"_light" key.
DEFAULT_QUAKE_LIGHT: float = 300.0

CAMERA_ENTITY_CLASSNAMES = frozenset((
	"info_player_start", "info_player_deathmatch", "info_player_coop", "info_intermission",
))
DEFAULT_CAMERA_FOV: float = 90.0

# Palette index ranges considered "fullbright" (self-illuminating).
# Quake 1: 224..254 (255 reserved as transparent in some assets).
# Quake 2: 224..255.
Q1_FULLBRIGHT_RANGE = range(224, 255)
Q2_FULLBRIGHT_RANGE = range(224, 256)

# IBSP magic + supported versions.
IBSP_MAGIC = b"IBSP"
BSP_VERSION_Q1 = 29
BSP_VERSION_GOLDSRC = 30
BSP_VERSION_Q2 = 38
BSP_VERSION_Q3 = 46

# WAD magics.
WAD2_MAGIC = b"WAD2"
WAD3_MAGIC = b"WAD3"

# WAD entry types.
WAD_TYPE_MIPTEX = 0x44
WAD3_TYPE_MIPTEX = 0x43

# Default Q3 patch tessellation level (segments per Bezier span).
DEFAULT_PATCH_LEVEL = 5
MAX_PATCH_LEVEL = 16

# Q3 tools traditionally cap patch control grids at 32 per side. Dimensions
# must be odd, so 31 is the largest usable value.
MAX_PATCH_DIMENSION = 31

# Bound source MAP parsing before a malformed brush can grow without limit.
MAX_BRUSH_FACES = 4096

# Bound decoded indexed textures before dimensions are multiplied or pixel
# buffers are read into memory.
MAX_TEXTURE_DIMENSION = 4096
MAX_TEXTURE_PIXELS = MAX_TEXTURE_DIMENSION * MAX_TEXTURE_DIMENSION

Q2_CONTENTS_CLIP = 0x10000 | 0x20000
Q3_CONTENTS_CLIP = 0x10000 | 0x20000 | 0x400000
Q3_CONTENTS_TRIGGER = 0x40000000
Q3_SURF_HINT = 0x100
