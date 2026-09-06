"""Validated runtime operations shared by Q3 shader nodes and tests."""

from __future__ import annotations

import math

from .shader_q3 import Directive, Shader, Stage


WAVES = {"sin", "triangle", "square", "sawtooth", "inversesawtooth"}
FACTORS = {"zero", "one", "src_color", "one_minus_src_color", "dst_color",
           "one_minus_dst_color", "src_alpha", "one_minus_src_alpha",
           "dst_alpha", "one_minus_dst_alpha"}


def blend(stage: Stage) -> tuple[str, str]:
    directive = stage.get("blendfunc")
    if directive is None:
        return "one", "zero"
    args = tuple(value.casefold().removeprefix("gl_") for value in directive.args)
    if len(args) == 1:
        args = {"add": ("one", "one"), "filter": ("dst_color", "zero"),
                "blend": ("src_alpha", "one_minus_src_alpha")}.get(args[0], args)
    if len(args) != 2 or any(value not in FACTORS for value in args):
        raise ValueError(f"line {directive.line}: unsupported blendFunc {directive.args}")
    return args


def wave(kind: str, base: float, amplitude: float, phase: float, frequency: float,
         seconds: float) -> float:
    phase = phase + seconds * frequency
    fraction = phase - math.floor(phase)
    if kind == "sin":
        value = math.sin(phase * math.tau)
    elif kind == "triangle":
        value = 1 - 4 * abs(((fraction + .25) % 1) - .5)
    elif kind == "square":
        value = 1 if fraction < .5 else -1
    elif kind == "sawtooth":
        value = fraction
    elif kind == "inversesawtooth":
        value = 1 - fraction
    else:
        raise ValueError(f"Unsupported wave {kind}")
    return base + amplitude * value


def animation_frame(seconds: float, frequency: float, count: int) -> int:
    if not math.isfinite(seconds) or not math.isfinite(frequency) or frequency <= 0 or count <= 0:
        raise ValueError("Invalid animation timing")
    return max(0, math.floor(seconds * frequency)) % count


def validate(shader: Shader) -> None:
    def fail(directive):
        raise ValueError(f"{shader.source}:{directive.line}: unsupported {directive.name} {directive.args}")

    def numeric(directive, start, count):
        if len(directive.numbers(start)) != count:
            fail(directive)

    def waveform(directive, start):
        if len(directive.args) <= start or directive.args[start].casefold() not in WAVES:
            fail(directive)
        numeric(directive, start + 1, 4)

    for directive in shader.directives:
        name, args = directive.name, tuple(value.casefold() for value in directive.args)
        if name.startswith("qer_") or name.startswith("q3map_"):
            continue
        if name == "surfaceparm" and len(args) == 1:
            continue
        if name == "cull" and args in {(value,) for value in ("none", "disable", "twosided", "back", "backsided", "front")}:
            continue
        if name in {"nopicmip", "nomipmaps"} and not args:
            continue
        if name in {"tesssize", "sort"}:
            if name == "tesssize":
                numeric(directive, 0, 1)
            elif args not in {("additive",), ("opaque",), ("banner",), ("underwater",)}:
                fail(directive)
            continue
        if name == "deformvertexes" and args and args[0] == "wave":
            if len(args) != 7 or Directive(name, directive.args[1:2], directive.line).numbers()[0] <= 0:
                fail(directive)
            waveform(directive, 2)
            continue
        fail(directive)
    if shader.stages and blend(shader.stages[0]) not in {
        ("one", "zero"), ("one", "one"), ("src_alpha", "one_minus_src_alpha"),
    }:
        raise ValueError(f"{shader.source}:{shader.line}: unsupported first-stage framebuffer blend")
    for stage_index, stage in enumerate(shader.stages):
        stage.images()
        blend(stage)
        if any(name.startswith("$") and name.casefold() not in {"$lightmap", "$whiteimage"} for name in stage.images()):
            raise ValueError(f"{shader.source}:{shader.line}: unsupported special image")
        if stage_index and stage.get("alphafunc"):
            raise ValueError(f"{shader.source}:{shader.line}: later-stage alpha testing is unsupported")
        if stage.get("tcgen") and tuple(value.casefold() for value in stage.get("tcgen").args) == ("environment",) and stage.get("tcmod"):
            raise ValueError(f"{shader.source}:{shader.line}: environment tcMods are unsupported")
        for directive in stage.directives:
            name, args = directive.name, tuple(value.casefold() for value in directive.args)
            if name in {"map", "clampmap", "animmap", "blendfunc"}:
                continue
            if name in {"rgbgen", "alphagen"}:
                if args in {("identity",), ("identitylighting",), ("vertex",), ("exactvertex",), ("oneminusvertex",)}:
                    continue
                if args and args[0] == "wave":
                    waveform(directive, 1)
                    continue
                if args and args[0] == "const":
                    numeric(directive, 1, 3 if name == "rgbgen" else 1)
                    continue
                fail(directive)
            elif name == "tcgen" and args in {("base",), ("texture",), ("lightmap",), ("environment",)}:
                continue
            elif name == "tcmod" and args:
                kind = args[0]
                if kind == "stretch":
                    waveform(directive, 1)
                elif kind in {"scale", "scroll", "rotate", "transform", "turb"}:
                    numeric(directive, 1, {"scale": 2, "scroll": 2, "rotate": 1, "transform": 6, "turb": 4}[kind])
                else:
                    fail(directive)
            elif name == "alphafunc" and args in {("gt0",), ("lt128",), ("ge128",)}:
                continue
            elif name == "depthwrite" and not args:
                continue
            elif name == "depthfunc" and args in {("equal",), ("lequal",)}:
                continue
            else:
                fail(directive)
