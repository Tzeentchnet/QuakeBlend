"""Tests for the entity-string lexer."""

from __future__ import annotations

import pytest

from quakeblend.formats.entities import (
    parse_camera_angles, parse_color, parse_entities, parse_goldsrc_light, parse_origin,
)


def test_parse_simple() -> None:
    text = '{ "classname" "worldspawn" "wad" "base.wad" }'
    out = parse_entities(text)
    assert out == [{"classname": "worldspawn", "wad": "base.wad"}]


def test_parse_multiple_entities_with_comments() -> None:
    text = """
    // a comment
    { "classname" "worldspawn" }
    {
      "classname" "info_player_start"
      "origin" "0 0 24"
    }
    """
    out = parse_entities(text)
    assert len(out) == 2
    assert out[1]["origin"] == "0 0 24"


def test_parse_quoted_escape() -> None:
    out = parse_entities('{ "msg" "hello \\"world\\"" }')
    assert out[0]["msg"] == 'hello "world"'


def test_parse_origin_split() -> None:
    assert parse_origin("12 -3.5 7") == (12.0, -3.5, 7.0)


@pytest.mark.parametrize("entity, expected", [
    ({}, (0.0, 0.0, 0.0)),
    ({"angle": "90"}, (0.0, 90.0, 0.0)),
    ({"angle": "bad", "mangle": "30 120 -45"}, (30.0, 120.0, -45.0)),
    ({"mangle": "  -10\t20 30  "}, (-10.0, 20.0, 30.0)),
])
def test_parse_camera_angles(entity: dict[str, str], expected: tuple) -> None:
    assert parse_camera_angles(entity) == expected


@pytest.mark.parametrize("entity", [
    {"angle": "nan"}, {"angle": "inf"}, {"angle": "bad"},
    {"mangle": "0 0"}, {"mangle": "0 0 0 0"},
    {"mangle": "0 nan 0"}, {"mangle": "0 0 inf"}, {"mangle": "bad 0 0"},
])
def test_parse_camera_angles_rejects_invalid_values(entity: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="camera"):
        parse_camera_angles(entity)


@pytest.mark.parametrize("value", ["nan 0 0", "0 inf 0", "0 0 -inf"])
def test_parse_origin_rejects_non_finite_values(value: str) -> None:
    with pytest.raises(ValueError, match="origin component must be finite"):
        parse_origin(value)


def test_parse_color_accepts_normalized_values() -> None:
    assert parse_color("1 0.5 0") == (1.0, 0.5, 0.0)


@pytest.mark.parametrize("value, color, intensity", [
    ("300", (1.0, 1.0, 1.0), 300.0),
    ("0", (1.0, 1.0, 1.0), 0.0),
    ("100 50 0", (1.0, 0.5, 0.0), 100.0),
    ("0 0 0", (0.0, 0.0, 0.0), 0.0),
    ("255 128 0 200", (1.0, 128.0 / 255.0, 0.0), 200.0),
    ("51 102 153 400", (0.2, 0.4, 0.6), 400.0),
])
def test_goldsrc_light_forms(value: str, color: tuple, intensity: float) -> None:
    assert parse_goldsrc_light(value) == (color, intensity)


@pytest.mark.parametrize("value", [
    "", "1 2", "1 2 3 4 5", "nan", "1 inf 2", "1 2 3 inf",
    "-1", "1 -2 3", "1 2 3 -4", "256 0 0 1", "bad",
])
def test_goldsrc_light_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        parse_goldsrc_light(value)


def test_parse_color_accepts_byte_values() -> None:
    assert parse_color("255 128 0") == (1.0, 128.0 / 255.0, 0.0)


def test_parse_color_clamps_values() -> None:
    assert parse_color("300 -10 128") == (1.0, 0.0, 128.0 / 255.0)


def test_parse_color_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="color"):
        parse_color("red green blue")


def test_parse_unterminated_entity_raises() -> None:
    with pytest.raises(ValueError):
        parse_entities('{ "k" "v"')


def test_parse_unterminated_quoted_string_raises() -> None:
    with pytest.raises(ValueError):
        parse_entities('{ "message" "unterminated }')


def test_parse_missing_value_after_key_raises() -> None:
    with pytest.raises(ValueError):
        parse_entities('{ "classname" }')


def test_parse_empty_entity_block() -> None:
    assert parse_entities("{ }") == [{}]


def test_parse_entity_with_only_whitespace_and_comments() -> None:
    text = """
    {
      // no key/value pairs here

    }
    """
    assert parse_entities(text) == [{}]
