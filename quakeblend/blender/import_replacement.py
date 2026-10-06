"""Coordinate opt-in replacement of an existing import root."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

from ..utils import paths as qb_paths

if TYPE_CHECKING:
    import bpy


_SOURCE_PROPERTIES = {
    "map": "qb_source_map",
    "bsp": "qb_source_bsp",
}
_SUPPORTED_GAMES = frozenset({"q1", "q2", "q3"})


class ImportReplacementError(RuntimeError):
    """Raised when an import cannot be replaced deterministically."""


@dataclass(frozen=True)
class ReplacementPlan:
    old_root: bpy.types.Collection
    source_identity: str
    source_path: Path
    kind: str
    old_name: str


@dataclass(frozen=True)
class _RemovalPlan:
    collections: tuple[Any, ...]
    objects: tuple[Any, ...]
    object_data: tuple[Any, ...]
    node_groups: tuple[Any, ...]
    actions: tuple[Any, ...]

    @property
    def ids(self) -> tuple[Any, ...]:
        return (
            *self.objects,
            *reversed(self.collections),
            *self.object_data,
            *self.node_groups,
            *self.actions,
        )


def _pointer(datablock: Any) -> int:
    return int(datablock.as_pointer())


def _source_property(kind: str) -> str:
    try:
        return _SOURCE_PROPERTIES[kind]
    except KeyError as exc:
        raise ValueError(f"unsupported import replacement kind {kind!r}") from exc


def matching_import_roots(
    collections: Iterable[bpy.types.Collection],
    *,
    source_identity: str,
    kind: str,
) -> tuple[bpy.types.Collection, ...]:
    source_property = _source_property(kind)
    return tuple(
        collection
        for collection in collections
        if collection.get("qb_source_identity") == source_identity
        and collection.get("qb_source_game") in _SUPPORTED_GAMES
        and bool(collection.get(source_property))
    )


def prepare_replacement(
    filepath: str | Path,
    *,
    kind: str,
    enabled: bool,
    collections: Iterable[bpy.types.Collection],
    source_game: str | None = None,
) -> ReplacementPlan | None:
    if not enabled:
        return None
    if source_game is not None and source_game.casefold() == "goldsrc":
        raise ImportReplacementError(
            "Replace Existing Import is not supported for GoldSrc BSP files"
        )

    source_path = qb_paths.resolved_source_path(filepath)
    source_identity = qb_paths.canonical_source_identity(source_path)
    matches = matching_import_roots(
        collections,
        source_identity=source_identity,
        kind=kind,
    )
    label = kind.upper()
    if not matches:
        raise ImportReplacementError(
            f"Replace Existing Import found no eligible {label} root for "
            f"'{source_path}'"
        )
    if len(matches) != 1:
        raise ImportReplacementError(
            f"Replace Existing Import found {len(matches)} eligible {label} "
            f"roots for '{source_path}'; remove duplicates or disable replacement"
        )
    old_root = matches[0]
    return ReplacementPlan(
        old_root=old_root,
        source_identity=source_identity,
        source_path=source_path,
        kind=kind,
        old_name=old_root.name,
    )


def find_new_root(
    plan: ReplacementPlan,
    collections: Iterable[bpy.types.Collection],
) -> bpy.types.Collection:
    old_pointer = _pointer(plan.old_root)
    matches = [
        collection
        for collection in matching_import_roots(
            collections,
            source_identity=plan.source_identity,
            kind=plan.kind,
        )
        if _pointer(collection) != old_pointer
    ]
    if len(matches) != 1:
        raise ImportReplacementError(
            f"Replacement import created {len(matches)} new eligible "
            f"{plan.kind.upper()} roots for '{plan.source_path}'; expected exactly one"
        )
    return matches[0]


def _collection_tree(root: bpy.types.Collection) -> list[bpy.types.Collection]:
    out: list[bpy.types.Collection] = []
    pending = [root]
    seen: set[int] = set()
    while pending:
        collection = pending.pop()
        pointer = _pointer(collection)
        if pointer in seen:
            continue
        seen.add(pointer)
        out.append(collection)
        pending.extend(collection.children)
    return out


def _record_reference(
    datablock: Any,
    values: dict[int, Any],
    counts: dict[int, int],
) -> None:
    pointer = _pointer(datablock)
    values[pointer] = datablock
    counts[pointer] = counts.get(pointer, 0) + 1


def _users(datablock: Any, label: str) -> int:
    try:
        users = int(datablock.users)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ImportReplacementError(
            f"Could not validate {label} users for '{datablock.name}'"
        ) from exc
    if users < 0:
        raise ImportReplacementError(
            f"Invalid {label} user count for '{datablock.name}'"
        )
    return users


def _exclusively_owned(
    values: dict[int, Any],
    owned_users: dict[int, int],
    *,
    label: str,
) -> dict[int, Any]:
    exclusive: dict[int, Any] = {}
    for pointer, datablock in values.items():
        users = _users(datablock, label)
        owned = owned_users[pointer]
        if users < owned:
            raise ImportReplacementError(
                f"{label.title()} users changed while replacement was being planned"
            )
        if users == owned:
            exclusive[pointer] = datablock
    return exclusive


def _owned_object_data(objects: Iterable[Any]) -> dict[int, Any]:
    values: dict[int, Any] = {}
    counts: dict[int, int] = {}
    for obj in objects:
        datablock = getattr(obj, "data", None)
        if datablock is not None:
            _record_reference(datablock, values, counts)
    return _exclusively_owned(values, counts, label="object data")


def _owned_node_groups(objects: Iterable[Any]) -> dict[int, Any]:
    groups: dict[int, Any] = {}
    object_users: dict[int, int] = {}
    group_users: dict[int, dict[int, int]] = {}
    pending: list[Any] = []
    for obj in objects:
        for modifier in getattr(obj, "modifiers", ()):
            group = getattr(modifier, "node_group", None)
            if group is None:
                continue
            _record_reference(group, groups, object_users)
            pending.append(group)

    expanded: set[int] = set()
    while pending:
        group = pending.pop()
        group_pointer = _pointer(group)
        groups[group_pointer] = group
        if group_pointer in expanded:
            continue
        expanded.add(group_pointer)
        references = group_users.setdefault(group_pointer, {})
        for node in getattr(group, "nodes", ()):
            child = getattr(node, "node_tree", None)
            if child is None:
                continue
            child_pointer = _pointer(child)
            groups[child_pointer] = child
            references[child_pointer] = references.get(child_pointer, 0) + 1
            pending.append(child)

    selected = set(groups)
    while True:
        shared = set()
        for pointer in selected:
            owned = object_users.get(pointer, 0)
            owned += sum(
                references.get(pointer, 0)
                for owner, references in group_users.items()
                if owner in selected
            )
            users = _users(groups[pointer], "node group")
            if users < owned:
                raise ImportReplacementError(
                    "Node group users changed while replacement was being planned"
                )
            if users != owned:
                shared.add(pointer)
        if not shared:
            break
        selected.difference_update(shared)
    return {
        pointer: group
        for pointer, group in groups.items()
        if pointer in selected
    }


def _action_references(datablock: Any) -> Iterable[Any]:
    animation_data = getattr(datablock, "animation_data", None)
    if animation_data is None:
        return
    action = getattr(animation_data, "action", None)
    if action is not None:
        yield action
    for track in getattr(animation_data, "nla_tracks", ()):
        for strip in track.strips:
            action = getattr(strip, "action", None)
            if action is not None:
                yield action


def _owned_actions(datablocks: Iterable[Any]) -> dict[int, Any]:
    actions: dict[int, Any] = {}
    counts: dict[int, int] = {}
    for datablock in datablocks:
        for action in _action_references(datablock):
            _record_reference(action, actions, counts)
    return _exclusively_owned(actions, counts, label="action")


def _validate_registered(
    datablocks: Iterable[Any],
    registries: Iterable[Iterable[Any]],
    *,
    label: str,
) -> None:
    registered = {
        _pointer(datablock)
        for registry in registries
        for datablock in registry
    }
    missing = [
        datablock.name
        for datablock in datablocks
        if _pointer(datablock) not in registered
    ]
    if missing:
        raise ImportReplacementError(
            f"{label.title()} disappeared before replacement: {', '.join(missing)}"
        )


def _objects_in(collections: Iterable[Any]) -> dict[int, Any]:
    return {
        _pointer(obj): obj
        for collection in collections
        for obj in collection.objects
    }


def _plan_removal(
    plan: ReplacementPlan,
    new_root: bpy.types.Collection,
    data: Any,
) -> _RemovalPlan:
    collections = _collection_tree(plan.old_root)
    new_collections = _collection_tree(new_root)
    old_collection_pointers = {_pointer(collection) for collection in collections}
    if old_collection_pointers.intersection(
        _pointer(collection) for collection in new_collections
    ):
        raise ImportReplacementError(
            "Replacement import reused part of the existing collection tree"
        )

    objects = _objects_in(collections)
    new_objects = _objects_in(new_collections)
    if set(objects).intersection(new_objects):
        raise ImportReplacementError(
            "Replacement import reused an object from the existing root"
        )

    object_data = _owned_object_data(objects.values())
    node_groups = _owned_node_groups(objects.values())
    actions = _owned_actions(
        [
            *collections,
            *objects.values(),
            *object_data.values(),
            *node_groups.values(),
        ]
    )
    removal = _RemovalPlan(
        collections=tuple(collections),
        objects=tuple(objects.values()),
        object_data=tuple(object_data.values()),
        node_groups=tuple(node_groups.values()),
        actions=tuple(actions.values()),
    )
    if len({_pointer(datablock) for datablock in removal.ids}) != len(removal.ids):
        raise ImportReplacementError(
            "Replacement cleanup planned the same datablock more than once"
        )

    _validate_registered(
        [*collections, *new_collections],
        (data.collections,),
        label="collection",
    )
    _validate_registered(
        [*objects.values(), *new_objects.values()],
        (data.objects,),
        label="object",
    )
    _validate_registered(
        object_data.values(),
        (
            getattr(data, "meshes", ()),
            getattr(data, "lights", ()),
            getattr(data, "cameras", ()),
        ),
        label="object data",
    )
    _validate_registered(
        node_groups.values(),
        (data.node_groups,),
        label="node group",
    )
    _validate_registered(
        actions.values(),
        (data.actions,),
        label="action",
    )
    return removal


def replace_import_root(
    plan: ReplacementPlan,
    new_root: bpy.types.Collection,
    *,
    data: Any | None = None,
) -> None:
    if _pointer(new_root) == _pointer(plan.old_root):
        raise ImportReplacementError("Replacement import did not create a new root")
    if new_root not in matching_import_roots(
        (new_root,),
        source_identity=plan.source_identity,
        kind=plan.kind,
    ):
        raise ImportReplacementError(
            "Replacement import root does not match the requested source"
        )

    if data is None:
        import bpy

        data = bpy.data
    removal = _plan_removal(plan, new_root, data)

    # Exercise the RNA setter while only the rollback-owned new root can change.
    new_root.name = plan.old_name
    data.batch_remove(ids=removal.ids)
    new_root.name = plan.old_name
