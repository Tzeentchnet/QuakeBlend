from __future__ import annotations

import importlib
from pathlib import Path
import sys
import types

import pytest

from quakeblend.blender.import_replacement import (
    ImportReplacementError,
    find_new_root,
    matching_import_roots,
    prepare_replacement,
    replace_import_root,
)
from quakeblend.utils.paths import canonical_source_identity


class _FakeId:
    _next_pointer = 1

    def __init__(self, name: str) -> None:
        self.name = name
        self._pointer = _FakeId._next_pointer
        _FakeId._next_pointer += 1

    def as_pointer(self) -> int:
        return self._pointer


class _FakeCollection(_FakeId, dict):
    def __init__(self, name: str, **properties: str) -> None:
        _FakeId.__init__(self, name)
        dict.__init__(self, properties)
        self.children: list[_FakeCollection] = []
        self.objects: list[_FakeObject] = []

    def __eq__(self, other) -> bool:
        return self is other

    __hash__ = object.__hash__


class _FakeAnimationData:
    def __init__(self, action=None) -> None:
        self.action = action
        self.nla_tracks = []


class _FakeModifier:
    def __init__(self, node_group=None) -> None:
        self.node_group = node_group


class _FakeNode:
    def __init__(self, node_group=None) -> None:
        self.node_tree = node_group


class _FakeObject(_FakeId):
    def __init__(self, name: str, data=None, *, node_groups=(), action=None) -> None:
        super().__init__(name)
        self.data = data
        self.modifiers = [_FakeModifier(group) for group in node_groups]
        self.animation_data = (
            _FakeAnimationData(action)
            if action is not None
            else None
        )


class _FakeObjectData(_FakeId):
    def __init__(self, name: str, *, users=1, action=None) -> None:
        super().__init__(name)
        self.users = users
        self.animation_data = (
            _FakeAnimationData(action)
            if action is not None
            else None
        )


class _FakeNodeGroup(_FakeObjectData):
    def __init__(
        self,
        name: str,
        *,
        users=1,
        action=None,
        node_groups=(),
    ) -> None:
        super().__init__(name, users=users, action=action)
        self.nodes = [_FakeNode(group) for group in node_groups]


class _FakeAction(_FakeObjectData):
    pass


class _Ids(list):
    def __init__(self, values=(), *, on_remove=None) -> None:
        super().__init__(values)
        self.on_remove = on_remove

    def remove(self, value, *, do_unlink=False) -> None:
        assert do_unlink
        super().remove(value)
        if self.on_remove is not None:
            self.on_remove(value)


class _FakeData:
    def __init__(
        self,
        collections,
        objects,
        materials,
        images,
        *,
        meshes=(),
        lights=(),
        cameras=(),
        node_groups=(),
        actions=(),
    ) -> None:
        self.collections = _Ids(collections)
        self.objects = _Ids(objects, on_remove=self._remove_object)
        self.materials = materials
        self.images = images
        self.meshes = list(meshes)
        self.lights = list(lights)
        self.cameras = list(cameras)
        self.node_groups = list(node_groups)
        self.actions = list(actions)
        self.batch_removed = []
        self.batch_remove_calls = []
        self.fail_batch_for: set[int] = set()

    @staticmethod
    def _remove_object(obj) -> None:
        if obj.data is not None:
            obj.data.users -= 1
        for modifier in obj.modifiers:
            if modifier.node_group is not None:
                modifier.node_group.users -= 1
        if obj.animation_data is not None and obj.animation_data.action is not None:
            obj.animation_data.action.users -= 1

    @staticmethod
    def _release_animation(datablock) -> None:
        animation_data = getattr(datablock, "animation_data", None)
        if animation_data is not None and animation_data.action is not None:
            animation_data.action.users -= 1

    def batch_remove(self, *, ids) -> None:
        ids = tuple(ids)
        self.batch_remove_calls.append(ids)
        if self.fail_batch_for.intersection(
            datablock.as_pointer() for datablock in ids
        ):
            self.fail_batch_for.clear()
            raise RuntimeError("simulated cleanup batch removal failure")

        for datablock in ids:
            if datablock in self.objects:
                self.objects.remove(datablock, do_unlink=True)
            elif datablock in self.node_groups:
                for node in datablock.nodes:
                    if node.node_tree is not None:
                        node.node_tree.users -= 1
                self._release_animation(datablock)
            else:
                self._release_animation(datablock)
        for datablock in ids:
            self.batch_removed.append(datablock)
            for collection in (
                self.collections,
                self.objects,
                self.meshes,
                self.materials,
                self.images,
                self.lights,
                self.cameras,
                self.node_groups,
                self.actions,
            ):
                if datablock in collection:
                    if isinstance(collection, _Ids):
                        collection.remove(datablock, do_unlink=True)
                    else:
                        collection.remove(datablock)


def _root(path: Path, name: str, *, kind="map", game="q1") -> _FakeCollection:
    source_property = "qb_source_map" if kind == "map" else "qb_source_bsp"
    return _FakeCollection(
        name,
        qb_source_identity=canonical_source_identity(path),
        qb_source_game=game,
        **{source_property: str(path.resolve())},
    )


def test_replacement_is_opt_in_and_default_keeps_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "level.map"
    roots = [_root(path, "level"), _root(path, "level.001")]

    assert prepare_replacement(
        path,
        kind="map",
        enabled=False,
        collections=roots,
    ) is None


def test_matching_roots_require_identity_kind_and_supported_game(
    tmp_path: Path,
) -> None:
    path = tmp_path / "level.bsp"
    expected = _root(path, "expected", kind="bsp", game="q2")
    wrong_kind = _root(path, "map", kind="map")
    goldsrc = _root(path, "goldsrc", kind="bsp", game="goldsrc")
    other = _root(tmp_path / "other.bsp", "other", kind="bsp")

    assert matching_import_roots(
        [wrong_kind, goldsrc, other, expected],
        source_identity=canonical_source_identity(path),
        kind="bsp",
    ) == (expected,)


@pytest.mark.parametrize("count", [0, 2])
def test_replacement_requires_exactly_one_existing_root(
    tmp_path: Path,
    count: int,
) -> None:
    path = tmp_path / "level.map"
    roots = [_root(path, f"level.{index}") for index in range(count)]

    with pytest.raises(ImportReplacementError) as error:
        prepare_replacement(
            path,
            kind="map",
            enabled=True,
            collections=roots,
        )

    message = str(error.value)
    assert ("no eligible MAP root" if count == 0 else "2 eligible MAP roots") in message
    assert str(path.resolve()) in message


def test_goldsrc_replacement_is_explicitly_rejected(tmp_path: Path) -> None:
    with pytest.raises(
        ImportReplacementError,
        match="not supported for GoldSrc",
    ):
        prepare_replacement(
            tmp_path / "level.bsp",
            kind="bsp",
            enabled=True,
            collections=[],
            source_game="goldsrc",
        )


def test_new_root_must_be_the_only_additional_match(tmp_path: Path) -> None:
    path = tmp_path / "level.map"
    old_root = _root(path, "level")
    plan = prepare_replacement(
        path,
        kind="map",
        enabled=True,
        collections=[old_root],
    )
    assert plan is not None
    new_root = _root(path, "level.001")

    assert find_new_root(plan, [old_root, new_root]) is new_root
    with pytest.raises(ImportReplacementError, match="created 2 new"):
        find_new_root(plan, [old_root, new_root, _root(path, "level.002")])


def test_replacing_root_restores_name_and_preserves_assets(tmp_path: Path) -> None:
    path = tmp_path / "level.map"
    old_root = _root(path, "Custom Import Name")
    child = _FakeCollection("Geometry")
    mesh = _FakeObjectData("Old Mesh")
    old_object = _FakeObject("Old Object", mesh)
    child.objects.append(old_object)
    old_root.children.append(child)
    new_root = _root(path, "level.001")
    material = _FakeId("Shared Material")
    image = _FakeId("Shared Image")
    plan = prepare_replacement(
        path,
        kind="map",
        enabled=True,
        collections=[old_root, child],
    )
    assert plan is not None
    data = _FakeData(
        [old_root, child, new_root],
        [old_object],
        [material],
        [image],
        meshes=[mesh],
    )

    replace_import_root(plan, new_root, data=data)

    assert new_root.name == "Custom Import Name"
    assert all(item is not old_root for item in data.collections)
    assert all(item is not child for item in data.collections)
    assert all(item is not old_object for item in data.objects)
    assert len(data.batch_remove_calls) == 1
    assert set(data.batch_removed) == {old_root, child, old_object, mesh}
    assert data.materials == [material]
    assert data.images == [image]


def test_replacing_root_removes_owned_orphans_and_keeps_shared_data(
    tmp_path: Path,
) -> None:
    path = tmp_path / "level.map"
    old_root = _root(path, "level")
    new_root = _root(path, "level.001")
    owned_action = _FakeAction("Owned Object Action")
    data_action = _FakeAction("Owned Data Action")
    shared_action = _FakeAction("Shared Action", users=2)
    owned_nested_group = _FakeNodeGroup("Owned Nested Nodes")
    owned_group = _FakeNodeGroup(
        "Owned Nodes",
        node_groups=[owned_nested_group],
    )
    shared_nested_group = _FakeNodeGroup("Shared Nested Nodes")
    shared_group = _FakeNodeGroup(
        "Shared Nodes",
        users=2,
        node_groups=[shared_nested_group],
    )
    mesh = _FakeObjectData("Old Mesh")
    light = _FakeObjectData("Old Light", action=data_action)
    camera = _FakeObjectData("Old Camera")
    shared_mesh = _FakeObjectData("Shared Mesh", users=2)
    old_root.objects.extend([
        _FakeObject(
            "Mesh Object",
            mesh,
            node_groups=[owned_group],
            action=owned_action,
        ),
        _FakeObject("Light Object", light),
        _FakeObject("Camera Object", camera, action=shared_action),
        _FakeObject("Shared Mesh Object", shared_mesh, node_groups=[shared_group]),
    ])
    material = _FakeId("Shared Material")
    image = _FakeId("Shared Image")
    plan = prepare_replacement(
        path,
        kind="map",
        enabled=True,
        collections=[old_root],
    )
    assert plan is not None
    data = _FakeData(
        [old_root, new_root],
        list(old_root.objects),
        [material],
        [image],
        meshes=[mesh, shared_mesh],
        lights=[light],
        cameras=[camera],
        node_groups=[
            owned_group,
            owned_nested_group,
            shared_group,
            shared_nested_group,
        ],
        actions=[owned_action, data_action, shared_action],
    )

    replace_import_root(plan, new_root, data=data)

    assert len(data.batch_remove_calls) == 1
    assert set(data.batch_removed) == {
        old_root,
        *old_root.objects,
        mesh,
        light,
        camera,
        owned_group,
        owned_nested_group,
        owned_action,
        data_action,
    }
    assert data.meshes == [shared_mesh]
    assert data.node_groups == [shared_group, shared_nested_group]
    assert data.actions == [shared_action]
    assert data.materials == [material]
    assert data.images == [image]


def test_cleanup_failure_keeps_old_root_and_rolls_back_new_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "level.map"
    old_root = _root(path, "level")
    old_mesh = _FakeObjectData("Old Mesh")
    old_object = _FakeObject("Old Object", old_mesh)
    old_root.objects.append(old_object)
    data = _FakeData(
        [old_root],
        [old_object],
        [],
        [],
        meshes=[old_mesh],
    )
    plan = prepare_replacement(
        path,
        kind="map",
        enabled=True,
        collections=data.collections,
    )
    assert plan is not None

    bpy = types.ModuleType("bpy")
    bpy.data = data
    monkeypatch.setitem(sys.modules, "bpy", bpy)
    monkeypatch.delitem(
        sys.modules,
        "quakeblend.blender.transaction",
        raising=False,
    )
    transaction = importlib.import_module("quakeblend.blender.transaction")

    new_root = _root(path, "level.001")
    new_mesh = _FakeObjectData("New Mesh")
    new_object = _FakeObject("New Object", new_mesh)
    new_root.objects.append(new_object)

    with pytest.raises(
        RuntimeError,
        match="simulated cleanup batch removal failure",
    ):
        with transaction.ImportTransaction():
            data.collections.append(new_root)
            data.objects.append(new_object)
            data.meshes.append(new_mesh)
            found = find_new_root(plan, data.collections)
            data.fail_batch_for = {old_root.as_pointer()}
            replace_import_root(plan, found, data=data)

    assert data.collections == [old_root]
    assert data.objects == [old_object]
    assert data.meshes == [old_mesh]
    assert old_root.name == "level"
    assert old_root.objects == [old_object]
    assert len(data.batch_remove_calls) == 2
    assert set(data.batch_remove_calls[0]) == {old_root, old_object, old_mesh}
    assert set(data.batch_remove_calls[1]) == {new_root, new_object, new_mesh}
