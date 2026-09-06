from __future__ import annotations

import pytest

from quakeblend.formats.shader_q3 import Directive, parse


def test_order_comments_and_unknown_directives():
    shaders = parse('''// heading
textures/demo_trans
{
    qer_editorimage textures/editor.tga
    surfaceparm nonsolid
    futureDirective keep this
    { map $lightmap }
    {
        map "textures/base.jpg" /* preserve the next line */
        blendFunc GL_DST_COLOR GL_ZERO
        tcMod scroll .1 .2
        tcMod scale 2 3
    }
}''', source="demo.shader")
    shader = shaders[0]
    assert shader.name == "textures/demo_trans"
    assert shader.line == 2
    assert shader.get("futuredirective").args == ("keep", "this")
    assert shader.stages[0].images() == ("$lightmap",)
    assert [item.args for item in shader.stages[1].directives if item.name == "tcmod"] == [
        ("scroll", ".1", ".2"), ("scale", "2", "3"),
    ]
    assert shader.dependencies() == ("textures/base.jpg",)
    assert shader.dependencies(editor=True) == ("textures/base.jpg", "textures/editor.tga")
    assert shader.stages[1].get("map").line == 9


def test_animation_line_and_sky_dependencies():
    shader = parse('''demo {
    skyParms env/demo 384 -
    {
        animMap 10 textures/frame1.tga textures/frame2.tga
        rgbGen wave sin .5 .5 0 1
    }
}''')[0]
    assert shader.stages[0].images() == ("textures/frame1.tga", "textures/frame2.tga")
    assert len(shader.dependencies()) == 8
    assert shader.stages[0].get("rgbgen").numbers(2) == (.5, .5, 0, 1)


@pytest.mark.parametrize("text", ['demo {', 'demo { { map image', 'demo { { { } } }',
                                  'demo { /* unfinished', 'demo { "unfinished', '}'])
def test_malformed_syntax(text):
    with pytest.raises(ValueError):
        parse(text)


@pytest.mark.parametrize("args", [("nan",), ("inf",), ("bad",), ("1e20",)])
def test_nonfinite_numeric_arguments(args):
    with pytest.raises(ValueError):
        Directive("wave", args, 7).numbers()


@pytest.mark.parametrize("args", ["nan textures/a", "-1 textures/a", "10", "0 textures/a"])
def test_invalid_animation(args):
    with pytest.raises(ValueError):
        parse("demo { { animMap " + args + " } }")[0].dependencies()


def test_comments_touching_paths_are_not_image_names():
    shader = parse('''demo {
    { map textures/base.tga// comment
    }
    { map textures/overlay.tga/* another comment */
    }
}''')[0]
    assert shader.dependencies() == ("textures/base.tga", "textures/overlay.tga")


def test_limits(monkeypatch):
    from quakeblend.formats import shader_q3

    monkeypatch.setattr(shader_q3, "MAX_TEXT_SIZE", 8)
    with pytest.raises(ValueError, match="text exceeds"):
        parse("demo { { map foo } }")
    monkeypatch.setattr(shader_q3, "MAX_TEXT_SIZE", 1024)
    monkeypatch.setattr(shader_q3, "MAX_TOKENS", 2)
    with pytest.raises(ValueError, match="token limit"):
        parse("demo { }")
    monkeypatch.setattr(shader_q3, "MAX_TOKENS", 100)
    monkeypatch.setattr(shader_q3, "MAX_STAGES", 1)
    with pytest.raises(ValueError, match="too many"):
        parse("demo { { map foo } { map bar } }")
    monkeypatch.setattr(shader_q3, "MAX_ANIMATION_FRAMES", 1)
    with pytest.raises(ValueError, match="frame count"):
        parse("demo { { animMap 10 foo bar } }")[0].dependencies()
