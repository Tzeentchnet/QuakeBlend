from __future__ import annotations

from types import SimpleNamespace

import pytest

from quakeblend.utils.import_options import ImportOptions, ToolSurface, classify_tool_brush


def test_defaults_and_precedence():
    assert ImportOptions.from_operator(SimpleNamespace(), bsp=True).q3_lighting == "FULLBRIGHT"
    assert ImportOptions.from_operator(SimpleNamespace()).q3_lighting == "RELIT"
    options = ImportOptions(worldspawn_only=True, trigger_handling="SKIP")
    assert options.model_allowed(0, {})
    assert not options.model_allowed(1, {})
    assert options.disposition({"clip", "trigger"}) == "SKIP"
    assert ImportOptions().disposition({"clip"}) == "HIDDEN"
    assert ImportOptions(import_entities=False).model_allowed(1, {})


@pytest.mark.parametrize("name,value", [("trigger_handling", "bad"), ("q3_lighting", "bad"), ("q3_lighting", "BAKED")])
def test_invalid_options(name, value):
    with pytest.raises(ValueError):
        ImportOptions.from_operator(SimpleNamespace(**{name: value}))


@pytest.mark.parametrize("names,expected", [(["clip"] * 6, {"clip"}), (["hint", "skip"], {"hint"}),
    (["wall_clip", "hint_panel"], set()), (["*lava", "sky", "nodraw"], set()), (["clip", "wall"], set())])
def test_exact_whole_brush_names(names, expected):
    assert classify_tool_brush([ToolSurface(name) for name in names], "q1")[0] == expected


def test_game_specific_semantics():
    surface = ToolSurface("wall", contents=0x400000)
    assert classify_tool_brush([surface], "q2")[0] == set()
    assert classify_tool_brush([surface], "q3")[0] == {"clip"}
    assert classify_tool_brush([ToolSurface("wall", flags=0x100)], "q3")[0] == {"hint"}
    assert classify_tool_brush([ToolSurface("custom", surfaceparms=("PlayerClip",))], "q3")[0] == {"clip"}
    assert classify_tool_brush([ToolSurface("custom", surfaceparms=("sky",))], "q3")[0] == set()
    assert classify_tool_brush([ToolSurface("custom", surfaceparms=("clip", "hint"))], "q3")[1]


def test_trigger_ownership():
    options = ImportOptions(trigger_handling="SKIP")
    assert not options.model_allowed(1, {"classname": "TRIGGER_ONCE"})
    assert options.model_allowed(1, {"classname": "func_door"})


@pytest.mark.parametrize("game,name", [("q2", "clip"), ("q3", "textures/common/clip")])
def test_unresolved_metadata_keeps_named_tools_visible(game, name):
    from quakeblend.formats.map_q1 import TexInfo
    from quakeblend.utils.map_resources import MapResources

    def fail_lookup(name):
        raise ValueError("Invalid metadata")

    warnings = []
    resources = MapResources(None, game, "image", sizes={},
        q3_assets=SimpleNamespace(shader=fail_lookup), warn=warnings.append)
    resources.wal = fail_lookup
    surface = resources.surface(TexInfo(name))
    categories, diagnostic = classify_tool_brush([surface], game)
    assert not categories and "kept visible" in diagnostic
    assert len(warnings) == 1
