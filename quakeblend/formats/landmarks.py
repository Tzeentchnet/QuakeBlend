"""Deterministic, translation-only GoldSrc landmark alignment."""

from __future__ import annotations

from dataclasses import dataclass
import math

from .entities import parse_origin


@dataclass(frozen=True)
class MapInstance:
    identity: str
    name: str
    entities: tuple[dict[str, str], ...]
    scale: float
    translation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    game: str = "goldsrc"
    translation_only: bool = True


@dataclass(frozen=True)
class Alignment:
    translation: tuple[float, float, float]
    target_ids: tuple[str, ...]


def _map_name(name: str) -> str:
    name = name.strip().casefold()
    return name[:-4] if name.endswith(".bsp") else name


def _connections(source: MapInstance, target: MapInstance) -> set[str]:
    names = set()
    for owner, destination in ((source, target), (target, source)):
        for entity in owner.entities:
            if (entity.get("classname") == "trigger_changelevel"
                    and _map_name(entity.get("map", "")) == _map_name(destination.name)):
                landmark = entity.get("landmark", "")
                if not landmark.strip():
                    raise ValueError("Changelevel connection has no landmark name")
                names.add(landmark)
    return names


def _origin(instance: MapInstance, name: str) -> tuple[float, float, float]:
    matches = [entity for entity in instance.entities
               if entity.get("classname") == "info_landmark" and entity.get("targetname") == name]
    if len(matches) != 1:
        raise ValueError(f"Map '{instance.name}' needs exactly one landmark '{name}'")
    origin = matches[0].get("origin", "")
    if len(origin.split()) != 3:
        raise ValueError(f"Landmark '{name}' needs exactly three origin components")
    return parse_origin(origin)


def resolve_alignment(source: MapInstance, targets: tuple[MapInstance, ...], *,
                      target_id: str = "") -> Alignment:
    """Return an absolute scene offset; agreement tolerance is 0.0001 game units.

    An explicit target identity restricts matching to that instance. Source
    translation is ignored so repeating alignment cannot accumulate offsets.
    """
    if source.game != "goldsrc" or not source.translation_only:
        raise ValueError("Stitching requires unrotated, unscaled GoldSrc roots")
    if not math.isfinite(source.scale) or source.scale <= 0:
        raise ValueError("Import scale must be finite and positive")
    available = [target for target in targets if target.identity != source.identity]
    if target_id:
        available = [target for target in available if target.identity == target_id]
        if len(available) != 1:
            raise ValueError("Selected stitching target is unavailable or ambiguous")
    candidates = []
    connected_names = set()
    for target in sorted(available, key=lambda instance: instance.identity):
        connections = _connections(source, target)
        if not connections:
            continue
        canonical_name = _map_name(target.name)
        if canonical_name in connected_names:
            raise ValueError("Multiple imported instances match; select an explicit target")
        connected_names.add(canonical_name)
        if target.game != "goldsrc" or not target.translation_only:
            raise ValueError("Stitching requires unrotated, unscaled GoldSrc roots")
        if target.scale != source.scale:
            raise ValueError("Connected maps must have matching import scales")
        if not all(math.isfinite(component) for component in target.translation):
            raise ValueError("Target translation must be finite")
        for name in sorted(connections):
            local_origin = _origin(source, name)
            target_origin = _origin(target, name)
            offset = tuple(target.translation[axis]
                           + (target_origin[axis] - local_origin[axis]) * source.scale
                           for axis in range(3))
            if not all(math.isfinite(component) for component in offset):
                raise ValueError("Landmark offset must be finite")
            candidates.append((offset, target.identity))
    if not candidates:
        raise ValueError("No matching changelevel connection found")
    translation = candidates[0][0]
    if any(max(abs(offset[axis] - translation[axis]) for axis in range(3))
           > 0.0001 * source.scale for offset, _ in candidates):
        raise ValueError("Landmark connections disagree on placement")
    return Alignment(translation, tuple(sorted({identity for _, identity in candidates})))
