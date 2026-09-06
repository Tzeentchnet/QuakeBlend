from __future__ import annotations

import pytest

from quakeblend.formats.shader_q3 import parse
from quakeblend.formats.shader_q3_math import animation_frame, blend, validate, wave


@pytest.mark.parametrize("text,expected", [("add", ("one", "one")),
    ("filter", ("dst_color", "zero")), ("blend", ("src_alpha", "one_minus_src_alpha")),
    ("GL_DST_COLOR GL_ONE_MINUS_DST_ALPHA", ("dst_color", "one_minus_dst_alpha"))])
def test_blend_factors(text, expected):
    shader = parse("demo { { map $whiteimage } {\nmap image\nblendFunc " + text + "\n} }")[0]
    validate(shader)
    assert blend(shader.stages[1]) == expected


@pytest.mark.parametrize("seconds,expected", [(-1, 0), (0, 0), (.099, 0), (.1, 1), (.799, 7), (.8, 0)])
def test_animation_boundaries(seconds, expected):
    assert animation_frame(seconds, 10, 8) == expected


def test_complementary_flame_waves():
    for seconds in (0, .0125, .05, .099, .1, .325):
        assert wave("sawtooth", 0, 1, 0, 10, seconds) + wave("inversesawtooth", 0, 1, 0, 10, seconds) == pytest.approx(1)
    assert wave("sin", .8, .2, 0, 1, .25) == pytest.approx(1)
    assert [wave("triangle", 0, 1, 0, 1, seconds) for seconds in (0, .25, .5, .75)] == [0, 1, 0, -1]


@pytest.mark.parametrize("directive", ["tcMod stretch noise 0 1 0 1", "tcMod scroll nan 1",
    "blendFunc unknown", "videoMap movie", "depthFunc greater", "alphaFunc mystery"])
def test_unsupported_stage_rejected(directive):
    with pytest.raises(ValueError):
        validate(parse("demo { {\nmap image\n" + directive + "\n} }")[0])


def test_sky_is_not_claimed_supported():
    with pytest.raises(ValueError, match="skyparms"):
        validate(parse("sky {\nskyParms - 384 -\n{ map sky.tga }\n}")[0])


def test_parenthesized_constant_vector():
    shader = parse("demo { {\nmap $WHITEIMAGE\nrgbGen const ( .2 .3 .4 )\n} }")[0]
    validate(shader)
    assert shader.stages[0].get("rgbgen").numbers(1) == (.2, .3, .4)


@pytest.mark.parametrize("body", ["{ map $unknown }", "{\nmap image\nblendFunc filter\n}",
    "{ map image }\n{\nmap image\nalphaFunc GT0\n}",
    "{\nmap image\ntcGen Environment\ntcMod scroll 1 1\n}"])
def test_unsupported_combinations_are_diagnosed(body):
    with pytest.raises(ValueError):
        validate(parse("demo {\n" + body + "\n}")[0])
