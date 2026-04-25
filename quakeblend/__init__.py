"""QuakeBlend — Blender 5.0+ extension for importing Quake 1/2/3 maps and textures.

The package is split into two layers:

* ``quakeblend.formats`` — pure-Python parsers. **Must not import bpy/bmesh/mathutils.**
* ``quakeblend.blender`` — Blender-facing operators, builders, and UI.

``bpy`` is imported lazily inside :func:`register` so that the formats package
remains importable from a plain Python interpreter (e.g. for pytest).
"""

from __future__ import annotations


def _modules():
    from .blender import (
        exporter_map, importer_bsp, importer_map, importer_wad, prefs, ui,
    )
    return (prefs, importer_map, importer_bsp, importer_wad, exporter_map, ui)


def register() -> None:
    for mod in _modules():
        mod.register()


def unregister() -> None:
    for mod in reversed(_modules()):
        mod.unregister()
