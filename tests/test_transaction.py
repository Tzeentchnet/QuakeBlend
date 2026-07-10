"""Tests for Blender import rollback using a minimal bpy stub."""

from __future__ import annotations

import importlib
import sys
import types

import pytest


class _FakeId:
    def __init__(self, pointer: int) -> None:
        self._pointer = pointer

    def as_pointer(self) -> int:
        return self._pointer


class _FakeData:
    def __init__(self) -> None:
        self.objects = [_FakeId(1)]
        self.collections = []
        self.meshes = []
        self.materials = []
        self.images = []
        self.lights = []
        self.cameras = []
        self.removed: list[_FakeId] = []

    def batch_remove(self, *, ids: list[_FakeId]) -> None:
        self.removed.extend(ids)


def _load_transaction(monkeypatch: pytest.MonkeyPatch, data: _FakeData):
    bpy = types.ModuleType("bpy")
    bpy.data = data
    monkeypatch.setitem(sys.modules, "bpy", bpy)
    sys.modules.pop("quakeblend.blender.transaction", None)
    return importlib.import_module("quakeblend.blender.transaction")


def test_import_transaction_keeps_created_ids_on_success(monkeypatch) -> None:
    data = _FakeData()
    transaction = _load_transaction(monkeypatch, data)

    with transaction.ImportTransaction():
        data.objects.append(_FakeId(2))

    assert data.removed == []


def test_import_transaction_removes_only_created_ids_on_failure(monkeypatch) -> None:
    data = _FakeData()
    transaction = _load_transaction(monkeypatch, data)
    created_object = _FakeId(2)
    created_material = _FakeId(3)

    with pytest.raises(RuntimeError, match="failed"):
        with transaction.ImportTransaction():
            data.objects.append(created_object)
            data.materials.append(created_material)
            raise RuntimeError("failed")

    assert data.removed == [created_object, created_material]
