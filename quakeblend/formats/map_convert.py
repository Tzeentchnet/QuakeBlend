"""Cross-game ``.map`` conversion.

Takes an in-memory :class:`~quakeblend.formats.map_q1.MapFile` and rewrites
it for a different target game (Q1 ↔ Q2 ↔ Q3). All transforms operate on
fresh copies; the input is left untouched.

Steps applied in order:

1. **Texture remap** — optional ``{src: dst}`` mapping; ``"*"`` is a fallback
   for everything not explicitly listed.
2. **Trailing fields** — ``contents/surface_flags/value`` stripped for Q1
   targets, preserved for Q2, kept on the texture matrix for Q3.
3. **brushDef3 normalization** — when target is Q1/Q2 each Q3 ``brushDef3``
   brush is reparsed and each face is decomposed into a Standard face via
   :func:`quakeblend.formats.brushdef3.to_standard_face`.
4. **Patch handling** — ``"tessellate"`` (default for Q1/Q2) replaces each
   ``patchDef2`` brush with a fan of thin extruded brushes; ``"drop"``
   removes them with a warning; ``"keep"`` is only legal when target is Q3.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, List, Literal, Optional

from . import brushdef3 as bd3_mod
from . import patch as patch_mod
from .common import Vec3
from .map_q1 import MapBrush, MapEntity, MapFace, MapFile, TexInfo


Game = Literal["q1", "q2", "q3"]
PatchHandling = Literal["tessellate", "drop", "keep"]


@dataclass
class ConvertOptions:
    texture_map: Optional[Dict[str, str]] = None
    patch_handling: PatchHandling = "tessellate"
    tessellation_level: int = 5
    extrusion_thickness: float = 1.0
    """How thick (in Quake units) tessellated patch quads are extruded."""
    skip_texture: str = "skip"
    """Texture used for the bottom/back faces of extruded patch brushes."""


@dataclass
class ConvertReport:
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    patches_tessellated: int = 0
    patches_dropped: int = 0
    brushdef3_converted: int = 0


# ----------------------------------------------------- texture name remap


def _remap_texture(name: str, mapping: Optional[Dict[str, str]]) -> str:
    if mapping is None:
        return name
    if name in mapping:
        return mapping[name]
    if "*" in mapping:
        return mapping["*"]
    return name


def _apply_texture_map(tex: TexInfo, mapping: Optional[Dict[str, str]]) -> TexInfo:
    if mapping is None:
        return tex
    new_name = _remap_texture(tex.name, mapping)
    if new_name == tex.name:
        return tex
    return replace(tex, name=new_name)


# ----------------------------------------------------- trailing field strip


def _strip_q2_fields(tex: TexInfo) -> TexInfo:
    if (tex.contents == 0 and tex.surface_flags == 0 and tex.value == 0
            and not tex.has_q2_trailing_fields):
        return tex
    return replace(
        tex,
        contents=0,
        surface_flags=0,
        value=0,
        has_q2_trailing_fields=False,
    )


# ----------------------------------------------------- brushDef3 → standard


def _normalize_brushdef3(brush: MapBrush, report: ConvertReport) -> MapBrush:
    """Reparse a ``brushDef3`` brush (if not already parsed) and convert each
    face to a Standard face."""
    if brush.raw_kind not in ("brushDef3", "brushDef"):
        return brush
    try:
        result = bd3_mod.to_standard_brush(brush)
    except (ValueError, StopIteration) as exc:
        report.errors.append(f"failed to parse brushDef3 brush: {exc}")
        return brush
    report.brushdef3_converted += 1
    return result


# ----------------------------------------------------- patch tessellation


def _build_extruded_brush(top_quad: List[Vec3], texture: str,
                          options: ConvertOptions) -> Optional[MapBrush]:
    """Build a thin extruded brush from one tessellated patch quad.

    The quad is the visible top face (textured); the brush extrudes downward
    along the inverted face normal by ``options.extrusion_thickness``. The 4
    side faces and the bottom use ``options.skip_texture``.
    """
    if len(top_quad) != 4:
        return None
    a, b, c, d = top_quad
    # Compute the quad normal from the first two edges.
    e1 = b - a
    e2 = c - a
    n = e1.cross(e2).normalized()
    if n.length() < 1e-6:
        return None
    thickness = options.extrusion_thickness
    # Bottom vertices = top vertices pushed along -n.
    a2 = a - n * thickness
    b2 = b - n * thickness
    c2 = c - n * thickness
    d2 = d - n * thickness

    skip = options.skip_texture

    def face(p1: Vec3, p2: Vec3, p3: Vec3, name: str) -> MapFace:
        return MapFace(p1=p1, p2=p2, p3=p3, tex=TexInfo(name=name))

    # Six faces: top (textured), bottom (skip), four sides (skip).
    # Quake winding: face normal points away from the brush solid, so we
    # supply three points such that ``Plane.from_points`` (which uses
    # (c-a) x (b-a)) yields the outward normal.
    faces = [
        # Plane.from_points uses (c-a) x (b-a), so the top needs the
        # opposite order from the source quad to point along +n.
        face(a, c, b, texture),
        # Bottom points along -n.
        face(a2, b2, c2, skip),
        # Side a-b: outward normal perpendicular to n, pointing outward from quad center.
        face(a, b, b2, skip),
        face(b, c, c2, skip),
        face(c, d, d2, skip),
        face(d, a, a2, skip),
    ]
    return MapBrush(faces=faces, raw_kind="standard", raw_payload="")


def _tessellate_patch_brush(brush: MapBrush, options: ConvertOptions,
                            report: ConvertReport) -> List[MapBrush]:
    if brush.raw_kind != "patchDef2":
        return [brush]
    try:
        name, p = patch_mod.parse_patch_def2_block(brush.raw_payload)
        tess = patch_mod.tessellate(p, level=options.tessellation_level)
    except (ValueError, StopIteration) as exc:
        report.errors.append(f"failed to tessellate patchDef2: {exc}")
        return []
    out: List[MapBrush] = []
    for quad in tess.quads:
        verts = [tess.vertices[i] for i in quad]
        b = _build_extruded_brush(verts, name, options)
        if b is not None:
            out.append(b)
    report.patches_tessellated += 1
    return out


# ----------------------------------------------------- driver


def convert(mf: MapFile, *, source: Game, target: Game,
            options: Optional[ConvertOptions] = None) -> tuple[MapFile, ConvertReport]:
    """Convert ``mf`` from ``source`` to ``target`` game dialect.

    Returns ``(new_mapfile, report)``. ``mf`` is not mutated.
    """
    if options is None:
        options = ConvertOptions()
    if options.patch_handling == "keep" and target != "q3":
        raise ValueError("patch_handling='keep' is only valid for target='q3'")

    report = ConvertReport()
    new_entities: List[MapEntity] = []

    for ent in mf.entities:
        new_brushes: List[MapBrush] = []
        for brush in ent.brushes:
            kind = brush.raw_kind
            # 1. brushDef3 normalization
            if kind in ("brushDef3", "brushDef") and target in ("q1", "q2"):
                brush = _normalize_brushdef3(brush, report)
                kind = brush.raw_kind

            # 2. patch handling
            if kind == "patchDef2":
                if options.patch_handling == "keep":
                    if target != "q3":
                        report.warnings.append(
                            "patch kept but target is not q3; output may be invalid"
                        )
                    new_brushes.append(_remap_brush_textures(brush, options.texture_map,
                                                             target, report))
                    continue
                if options.patch_handling == "drop":
                    report.warnings.append(
                        f"dropped patchDef2 brush (target={target})")
                    report.patches_dropped += 1
                    continue
                # tessellate
                new_brushes.extend(
                    _remap_brush_textures(b, options.texture_map, target, report)
                    for b in _tessellate_patch_brush(brush, options, report)
                )
                continue

            if kind == "patchDef3":
                if target == "q3":
                    if options.texture_map is not None:
                        report.warnings.append(
                            "patchDef3 texture remapping is not implemented; "
                            "brush preserved unchanged"
                        )
                    new_brushes.append(MapBrush(
                        faces=list(brush.faces),
                        raw_kind=brush.raw_kind,
                        raw_payload=brush.raw_payload,
                    ))
                    continue
                report.warnings.append(
                    f"patchDef3 cannot be converted to {target}; brush dropped"
                )
                report.patches_dropped += 1
                continue

            # 3. standard / brushDef3-already-handled brushes
            new_brushes.append(_remap_brush_textures(brush, options.texture_map, target,
                                                     report))

        new_entities.append(MapEntity(properties=dict(ent.properties),
                                      brushes=new_brushes))

    return MapFile(entities=new_entities), report


def _remap_brush_textures(brush: MapBrush,
                          texture_map: Optional[Dict[str, str]],
                          target: Game,
                          report: Optional[ConvertReport] = None) -> MapBrush:
    """Apply texture remap + trailing-field strip per face for the target game."""
    if (brush.raw_kind in ("brushDef3", "brushDef")
            and not brush.faces
            and texture_map is not None):
        try:
            parsed = bd3_mod.parse_brushdef3_block(brush.raw_payload)
        except ValueError as exc:
            if report is not None:
                report.warnings.append(
                    f"failed to remap {brush.raw_kind} textures; "
                    f"keeping original brush: {exc}"
                )
            return brush
        remapped_faces = [
            replace(face, tex=_apply_texture_map(face.tex, texture_map))
            for face in parsed.faces
        ]
        if all(
            remapped.tex.name == original.tex.name
            for remapped, original in zip(remapped_faces, parsed.faces)
        ):
            return brush
        return MapBrush(
            faces=remapped_faces,
            raw_kind=brush.raw_kind,
            raw_payload=brush.raw_payload,
        )

    if brush.raw_kind == "patchDef2" and texture_map is not None:
        # Patch texture is embedded in raw_payload — rewrite it by reparse.
        try:
            name, patch = patch_mod.parse_patch_def2_block(brush.raw_payload)
        except (ValueError, StopIteration) as exc:
            if report is not None:
                report.warnings.append(
                    f"failed to remap patchDef2 texture; keeping original brush: {exc}"
                )
            return brush
        new_name = _remap_texture(name, texture_map)
        if new_name != name:
            new_payload = patch_mod.serialize_patch_def2(new_name, patch)
            # Store the legacy brace-less body; the writer accepts both this
            # representation and the parser's brace-inclusive raw payload.
            inner = _strip_block(new_payload)
            return MapBrush(faces=[], raw_kind="patchDef2", raw_payload=inner)
        return brush

    new_faces = []
    for face in brush.faces:
        tex = face.tex
        tex = _apply_texture_map(tex, texture_map)
        if target == "q1":
            tex = _strip_q2_fields(tex)
        new_faces.append(MapFace(p1=face.p1, p2=face.p2, p3=face.p3, tex=tex))
    return MapBrush(faces=new_faces, raw_kind=brush.raw_kind,
                    raw_payload=brush.raw_payload)


def _strip_block(block: str) -> str:
    """Return the legacy brace-less body from a serialized raw brush block."""
    lines = block.splitlines()
    if lines and lines[0].strip() in ("patchDef2", "patchDef3", "brushDef3", "brushDef"):
        lines = lines[1:]
    if lines and lines[0].strip() == "{":
        lines = lines[1:]
    if lines and lines[-1].strip() == "}":
        lines = lines[:-1]
    return "\n".join(lines)
