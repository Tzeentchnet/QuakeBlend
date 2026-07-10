"""Rollback newly created Blender datablocks when an import fails."""

from __future__ import annotations

import bpy


_DATA_COLLECTIONS = (
    "objects",
    "collections",
    "meshes",
    "materials",
    "images",
    "lights",
    "cameras",
)


class ImportTransaction:
    def __init__(self) -> None:
        self._before: dict[str, set[int]] = {}

    def __enter__(self) -> "ImportTransaction":
        self._before = {
            name: {item.as_pointer() for item in getattr(bpy.data, name)}
            for name in _DATA_COLLECTIONS
        }
        return self

    def __exit__(self, exc_type, _exc, _traceback) -> bool:
        if exc_type is None:
            return False
        created = []
        for name in _DATA_COLLECTIONS:
            previous = self._before[name]
            created.extend(
                item
                for item in getattr(bpy.data, name)
                if item.as_pointer() not in previous
            )
        if created:
            bpy.data.batch_remove(ids=created)
        return False
