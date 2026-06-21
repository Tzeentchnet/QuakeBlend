"""Operator: export the active QuakeBlend MAP-imported collection to a
``.map`` file targeting Q1, Q2, or Q3.

The source of truth is the **original ``.map`` file path cached on the root
collection at import time** (see ``import_runner_map.run``). Blender mesh
edits to brush geometry are NOT reflected in the export. Optional entity
property edits (origin, classname) can be folded in via
``use_scene_entity_edits``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import bpy
from bpy_extras.io_utils import ExportHelper

from ..formats import map_convert, map_q1, map_writer
from ..utils.constants import DEFAULT_PATCH_LEVEL


def _find_source_collection(context: bpy.types.Context) -> bpy.types.Collection | None:
    """Find the import root collection nearest to the active context.

    Search order: active collection (and ancestors), then any top-level scene
    collection child carrying ``qb_source_map``.
    """
    coll = getattr(context, "collection", None)
    visited: set[str] = set()
    while coll is not None and coll.name not in visited:
        visited.add(coll.name)
        if "qb_source_map" in coll:
            return coll
        # Walk up to the parent collection (Blender doesn't expose .parent
        # directly; iterate scene children to find one whose children include us).
        parent = _find_parent(context.scene.collection, coll)
        if parent is None or parent is context.scene.collection:
            break
        coll = parent
    # Fallback: scan top-level children.
    for child in context.scene.collection.children:
        if "qb_source_map" in child:
            return child
    return None


def _find_parent(root: bpy.types.Collection,
                 target: bpy.types.Collection) -> bpy.types.Collection | None:
    for child in root.children:
        if child == target:
            return root
        found = _find_parent(child, target)
        if found is not None:
            return found
    return None


def _apply_entity_overlay(mf: map_q1.MapFile,
                          collection: bpy.types.Collection,
                          scale: float) -> None:
    """Overlay entity-property edits from Blender objects onto ``mf``.

    Looks for objects under ``collection`` carrying ``qb_entity_index``;
    their location (divided by ``scale``) overrides ``origin`` and any
    custom property starting with ``qb_prop_`` overrides the matching key.
    """
    inv_scale = 1.0 / scale if scale else 1.0
    by_index: dict[int, bpy.types.Object] = {}

    def visit(coll: bpy.types.Collection) -> None:
        for obj in coll.objects:
            if "qb_entity_index" in obj:
                try:
                    idx = int(obj["qb_entity_index"])
                except (TypeError, ValueError):
                    continue
                by_index[idx] = obj
        for child in coll.children:
            visit(child)

    visit(collection)
    for idx, obj in by_index.items():
        if idx < 0 or idx >= len(mf.entities):
            continue
        ent = mf.entities[idx]
        # Origin from object location (skip worldspawn).
        if ent.properties.get("classname") != "worldspawn":
            x, y, z = obj.location
            ent.properties["origin"] = (
                f"{x * inv_scale:g} {y * inv_scale:g} {z * inv_scale:g}"
            )
        # Custom property overrides.
        for key in obj.keys():
            if key.startswith("qb_prop_"):
                ent.properties[key[len("qb_prop_"):]] = str(obj[key])


class EXPORT_OT_quake_map(bpy.types.Operator, ExportHelper):
    bl_idname = "quakeblend.export_map"
    bl_label = "Export Quake MAP"
    bl_description = (
        "Export an imported Quake .map collection to a .map file, "
        "optionally converting between Q1/Q2/Q3 dialects"
    )
    bl_options = {"PRESET"}

    filename_ext = ".map"
    filter_glob: bpy.props.StringProperty(default="*.map", options={"HIDDEN"})  # type: ignore[valid-type]

    target_game: bpy.props.EnumProperty(  # type: ignore[valid-type]
        name="Target game",
        items=(
            ("AUTO", "Auto (source)", "Use the source game cached at import time"),
            ("Q1", "Quake 1", "Standard / Valve220 face syntax, no trailing fields"),
            ("Q2", "Quake 2", "Standard / Valve220 + contents/flags/value trailers"),
            ("Q3", "Quake 3", "Allow brushDef3 and patchDef2 brushes"),
        ),
        default="AUTO",
    )
    projection: bpy.props.EnumProperty(  # type: ignore[valid-type]
        name="Texture projection",
        items=(
            ("AUTO", "Auto (per-face)", "Valve220 if face has S/T axes, Standard otherwise"),
            ("STANDARD", "Standard", "Force Standard syntax for every face"),
            ("VALVE220", "Valve220", "Force Valve220 syntax for every face"),
        ),
        default="AUTO",
    )
    patch_handling: bpy.props.EnumProperty(  # type: ignore[valid-type]
        name="Q3 patches",
        items=(
            ("TESSELLATE", "Tessellate to brushes",
             "Replace patchDef2 brushes with thin extruded brush quads"),
            ("DROP", "Drop with warning",
             "Skip patchDef2 brushes; smaller cleaner output"),
            ("KEEP", "Keep verbatim (Q3 target only)",
             "Pass patchDef2 blocks through unchanged; only valid for Q3 target"),
        ),
        default="TESSELLATE",
    )
    tessellation_level: bpy.props.IntProperty(  # type: ignore[valid-type]
        name="Patch tessellation level",
        default=DEFAULT_PATCH_LEVEL, min=1, max=16,
    )
    extrusion_thickness: bpy.props.FloatProperty(  # type: ignore[valid-type]
        name="Patch extrusion thickness",
        description="Quake-unit thickness of brushes built from patch quads",
        default=1.0, min=0.0625, max=64.0,
    )
    texture_map_path: bpy.props.StringProperty(  # type: ignore[valid-type]
        name="Texture map (JSON)",
        description=(
            "Optional JSON file with {\"src_name\": \"dst_name\"} entries. "
            "Use \"*\" as a fallback for unmatched names"
        ),
        subtype="FILE_PATH",
        default="",
    )
    use_scene_entity_edits: bpy.props.BoolProperty(  # type: ignore[valid-type]
        name="Apply entity edits from scene",
        description=(
            "Override entity origin/properties from Blender objects carrying "
            "qb_entity_index. Brush geometry edits are NOT exported."
        ),
        default=False,
    )

    def execute(self, context: bpy.types.Context) -> set[str]:  # noqa: D401
        coll = _find_source_collection(context)
        if coll is None:
            self.report({"ERROR"},
                        "No imported MAP collection found. Select a "
                        "QuakeBlend-imported collection or its child first.")
            return {"CANCELLED"}
        source_path = coll.get("qb_source_map")
        if not source_path:
            self.report({"ERROR"},
                        f"Collection {coll.name!r} has no qb_source_map; "
                        "BSP→MAP export is not supported.")
            return {"CANCELLED"}
        source_game: str = coll.get("qb_source_game", "q1")
        source_projection: str = coll.get("qb_source_projection", "standard")

        target = self.target_game.lower() if self.target_game != "AUTO" else source_game
        if target not in ("q1", "q2", "q3"):
            self.report({"ERROR"}, f"Invalid target game {target!r}")
            return {"CANCELLED"}

        # Re-parse the cached source file.
        try:
            mf = map_q1.parse_path(source_path)
        except (OSError, ValueError) as exc:
            self.report({"ERROR"}, f"Failed to re-parse source MAP: {exc}")
            return {"CANCELLED"}

        # Optional entity overlay from scene objects.
        if self.use_scene_entity_edits:
            scale = float(getattr(context.scene, "qb_import_scale", 1.0 / 32.0))
            _apply_entity_overlay(mf, coll, scale)

        # Optional texture map.
        texture_map: dict[str, str] | None = None
        if self.texture_map_path:
            try:
                texture_map = json.loads(
                    Path(bpy.path.abspath(self.texture_map_path)).read_text(encoding="utf-8")
                )
            except (OSError, ValueError) as exc:
                self.report({"ERROR"}, f"Failed to read texture map JSON: {exc}")
                return {"CANCELLED"}
            if not isinstance(texture_map, dict):
                self.report({"ERROR"}, "Texture map JSON must be an object")
                return {"CANCELLED"}
            invalid_texture_map_keys: list[str] = []
            valid_texture_map: dict[str, str] = {}
            for key, value in texture_map.items():
                if isinstance(key, str) and isinstance(value, str):
                    valid_texture_map[key] = value
                    continue
                invalid_texture_map_keys.append(repr(key))
            if invalid_texture_map_keys:
                invalid_list = ", ".join(invalid_texture_map_keys[:10])
                if len(invalid_texture_map_keys) > 10:
                    invalid_list += ", ..."
                self.report(
                    {"WARNING"},
                    "Skipping texture map entries with non-string key/value for keys: "
                    f"{invalid_list}",
                )
            texture_map = valid_texture_map

        patch_handling_map = {"TESSELLATE": "tessellate", "DROP": "drop", "KEEP": "keep"}
        patch_handling = patch_handling_map[self.patch_handling]
        if patch_handling == "keep" and target != "q3":
            self.report({"WARNING"},
                        "patch_handling=Keep requires target=Q3; falling back to Tessellate")
            patch_handling = "tessellate"

        options = map_convert.ConvertOptions(
            texture_map=texture_map,
            patch_handling=patch_handling,
            tessellation_level=int(self.tessellation_level),
            extrusion_thickness=float(self.extrusion_thickness),
        )

        try:
            converted, report = map_convert.convert(
                mf, source=source_game, target=target, options=options
            )
        except ValueError as exc:
            self.report({"ERROR"}, f"Conversion failed: {exc}")
            return {"CANCELLED"}

        # Pick projection: AUTO inherits source projection.
        if self.projection == "AUTO":
            proj = source_projection if source_projection in ("standard", "valve220") else "auto"
        else:
            proj = self.projection.lower()
        # Normalise to map_writer literal.
        if proj not in ("auto", "standard", "valve220"):
            proj = "auto"

        try:
            map_writer.serialize_path(converted,
                                      os.fspath(self.filepath),
                                      dialect=target,  # type: ignore[arg-type]
                                      projection=proj)  # type: ignore[arg-type]
        except (OSError, ValueError) as exc:
            self.report({"ERROR"}, f"Failed to write MAP: {exc}")
            return {"CANCELLED"}

        for warning in report.warnings:
            self.report({"WARNING"}, warning)
        for err in report.errors:
            self.report({"ERROR"}, err)

        summary_parts = [f"target={target}"]
        if report.brushdef3_converted:
            summary_parts.append(f"brushDef3→standard={report.brushdef3_converted}")
        if report.patches_tessellated:
            summary_parts.append(f"patches_tessellated={report.patches_tessellated}")
        if report.patches_dropped:
            summary_parts.append(f"patches_dropped={report.patches_dropped}")
        self.report({"INFO"},
                    f"Exported {Path(self.filepath).name} ({', '.join(summary_parts)})")
        return {"FINISHED"}


def register() -> None:
    bpy.utils.register_class(EXPORT_OT_quake_map)


def unregister() -> None:
    bpy.utils.unregister_class(EXPORT_OT_quake_map)
