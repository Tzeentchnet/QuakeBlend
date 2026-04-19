"""Project-wide constants for QuakeBlend.

No bpy imports; safe to use from the formats layer.
"""

from __future__ import annotations

# Default world-unit scale. 1 Quake unit ≈ 1 inch ≈ 0.0254 m, but the community
# standard for Blender import is 1/32 (32 units = 1 Blender meter), matching the
# reference implementations.
DEFAULT_IMPORT_SCALE: float = 1.0 / 32.0

# CSG plane-intersection epsilon used when classifying candidate vertices as
# inside the brush half-space arrangement.
CSG_EPSILON: float = 0.1

# Palette index ranges considered "fullbright" (self-illuminating).
# Quake 1: 224..254 (255 reserved as transparent in some assets).
# Quake 2: 224..255.
Q1_FULLBRIGHT_RANGE = range(224, 255)
Q2_FULLBRIGHT_RANGE = range(224, 256)

# IBSP magic + supported versions.
IBSP_MAGIC = b"IBSP"
BSP_VERSION_Q1 = 29
BSP_VERSION_Q2 = 38
BSP_VERSION_Q3 = 46

# WAD magics.
WAD2_MAGIC = b"WAD2"
WAD3_MAGIC = b"WAD3"

# WAD entry types.
WAD_TYPE_MIPTEX = 0x44

# Default Q3 patch tessellation level (segments per Bezier span).
DEFAULT_PATCH_LEVEL = 5
