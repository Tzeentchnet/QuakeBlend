from __future__ import annotations

from dataclasses import replace

import pytest

from quakeblend.formats.landmarks import MapInstance, resolve_alignment


def landmark(name="door", origin="0 0 0"):
    return {"classname": "info_landmark", "targetname": name, "origin": origin}


def connection(destination="old", name="door"):
    return {"classname": "trigger_changelevel", "map": destination, "landmark": name}


def pair():
    return (MapInstance("new-id", "new", (landmark(origin="16 0 0"), connection()), 0.5),
            MapInstance("old-id", "old", (landmark(origin="64 0 0"),), 0.5, (10, 20, 30)))


def test_forward_reverse_and_idempotent_alignment():
    source, target = pair()
    result = resolve_alignment(source, (target,))
    assert result.translation == (34, 20, 30)
    assert result.target_ids == ("old-id",)
    assert resolve_alignment(replace(source, translation=result.translation), (target,)) == result
    source = replace(source, entities=(source.entities[0],))
    target = replace(target, entities=target.entities + (connection("NEW.BSP"),))
    assert resolve_alignment(source, (target,)) == result


def test_duplicate_instances_require_selection():
    source, target = pair()
    duplicate = replace(target, identity="duplicate")
    with pytest.raises(ValueError, match="explicit target"):
        resolve_alignment(source, (target, duplicate))
    assert resolve_alignment(source, (target, duplicate), target_id="old-id").target_ids == ("old-id",)
    with pytest.raises(ValueError, match="unavailable"):
        resolve_alignment(source, (target,), target_id="missing")


def test_multiple_connections_and_chain():
    source, target = pair()
    other = replace(target, identity="other-id", name="other")
    source = replace(source, entities=source.entities + (connection("other"),))
    assert resolve_alignment(source, (other, target)).target_ids == ("old-id", "other-id")
    with pytest.raises(ValueError, match="disagree"):
        resolve_alignment(source, (replace(other, translation=(11, 20, 30)), target))
    placed = replace(source, translation=resolve_alignment(source, (target,)).translation)
    third = MapInstance("third-id", "third", (landmark(), connection("new")), 0.5)
    assert resolve_alignment(third, (placed,)).translation == (42, 20, 30)


@pytest.mark.parametrize("entities", [(), (landmark(), landmark()), (landmark(origin="nan 0 0"),),
                                      (landmark(origin="0 0"),), (landmark(origin="0 0 0 1"),)])
def test_bad_landmarks(entities):
    source, target = pair()
    with pytest.raises(ValueError):
        resolve_alignment(source, (replace(target, entities=entities),))


@pytest.mark.parametrize("changes", [{"scale": 1}, {"translation_only": False}, {"game": "q1"},
                                      {"translation": (float("inf"), 0, 0)}])
def test_incompatible_targets(changes):
    source, target = pair()
    with pytest.raises(ValueError):
        resolve_alignment(source, (replace(target, **changes),))


def test_missing_connections_and_keys():
    source, target = pair()
    with pytest.raises(ValueError, match="No matching"):
        resolve_alignment(replace(source, entities=(landmark(),)), (target,))
    with pytest.raises(ValueError, match="no landmark"):
        resolve_alignment(replace(source, entities=(connection(name=""),)), (target,))


@pytest.mark.parametrize("scale", [0, -1, float("nan"), float("inf")])
def test_invalid_source_scale(scale):
    source, target = pair()
    with pytest.raises(ValueError, match="finite and positive"):
        resolve_alignment(replace(source, scale=scale), (target,))


def test_landmark_agreement_tolerance_and_order():
    source, target = pair()
    source = replace(source, entities=source.entities + (landmark("other"), connection(name="other")))
    target = replace(target, entities=target.entities + (landmark("other", "48.00009 0 0"),))
    result = resolve_alignment(source, (target,))
    assert result.translation == (34, 20, 30)
    assert resolve_alignment(replace(source, entities=tuple(reversed(source.entities))), (target,)) == result
    target = replace(target, entities=(target.entities[0], landmark("other", "48.00011 0 0")))
    with pytest.raises(ValueError, match="disagree"):
        resolve_alignment(source, (target,))
