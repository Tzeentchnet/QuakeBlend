"""GoldSrc assembly roots and opt-in landmark placement."""

from __future__ import annotations

import bpy

from ..formats.entities import parse_entities
from ..formats.landmarks import MapInstance, resolve_alignment
from ..utils import log as qb_log


_target_items = [("AUTO", "Automatic", "Require an unambiguous set of connected maps", 0)]
_target_choices = {}


def _roots(collection):
    for child in collection.children:
        if child.get("qb_source_game") == "goldsrc" and child.get("qb_import_id"):
            yield child
        yield from _roots(child)


def target_items(_operator, context):
    global _target_items
    _target_items = [_target_items[0]]
    if context is not None:
        roots = {root["qb_import_id"]: root for root in _roots(context.scene.collection)}
        for identity, root in sorted(roots.items()):
            if identity not in _target_choices:
                _target_choices[identity] = (identity, root.name, root.get("qb_source_bsp", ""),
                                             len(_target_choices) + 1)
            _target_items.append(_target_choices[identity])
    return _target_items


def assembly_root(collection):
    matches = [obj for obj in collection.objects
               if obj.get("qb_assembly_id") == collection["qb_import_id"]]
    if len(matches) != 1:
        raise ValueError(f"Map '{collection.name}' has no unique assembly root; reimport it")
    return matches[0]


def create_root(collection):
    objects = list(collection.all_objects)
    root = bpy.data.objects.new(f"{collection.name}_Assembly", None)
    root["qb_assembly_id"] = collection["qb_import_id"]
    root.empty_display_type = "PLAIN_AXES"
    collection.objects.link(root)
    for obj in objects:
        if obj.parent is None:
            obj.parent = root
    return root


def _instance(collection):
    root = assembly_root(collection)
    basis = root.matrix_world.to_3x3()
    translation_only = (
        root.parent is None and not root.constraints and root.animation_data is None
        and all(abs(basis[row][column] - float(row == column)) < 1e-6
                for row in range(3) for column in range(3))
        and all(abs(value) < 1e-6 for value in root.delta_location)
    )
    return MapInstance(
        identity=collection["qb_import_id"], name=collection["qb_map_name"],
        entities=tuple(parse_entities(collection["qb_bsp_entities"])),
        scale=float(collection["qb_import_scale"]),
        translation=tuple(root.matrix_world.translation),
        game=collection["qb_source_game"], translation_only=translation_only,
    )


def stitch_import(operator, context, collection):
    context.view_layer.update()
    try:
        source = _instance(collection)
        selected = getattr(operator, "stitch_target", "AUTO")
        roots = {root.as_pointer(): root for root in _roots(context.scene.collection)
                 if root != collection}
        if selected != "AUTO":
            roots = {pointer: root for pointer, root in roots.items() if root["qb_import_id"] == selected}
        targets = tuple(_instance(root) for root in roots.values())
        alignment = resolve_alignment(source, targets, target_id="" if selected == "AUTO" else selected)
    except (ValueError, KeyError, TypeError) as exc:
        qb_log.report(operator, {"WARNING"}, f"GoldSrc stitching skipped: {exc}")
        return False
    assembly_root(collection).location = alignment.translation
    collection["qb_stitch_offset"] = alignment.translation
    collection["qb_stitch_targets"] = "\n".join(alignment.target_ids)
    context.view_layer.update()
    return True
