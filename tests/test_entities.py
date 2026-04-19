"""Tests for the entity-string lexer."""

from __future__ import annotations

import pytest

from quakeblend.formats.entities import parse_entities, parse_origin


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


def test_parse_unterminated_entity_raises() -> None:
    with pytest.raises(ValueError):
        parse_entities('{ "k" "v"')
