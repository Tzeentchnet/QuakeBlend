"""Bounded, source-located Quake III shader syntax and image dependencies."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass


MAX_TEXT_SIZE = 4 * 1024 * 1024
MAX_TOKENS = 250000
MAX_STAGES = 64
MAX_ANIMATION_FRAMES = 256
MAX_NUMBER = 1_000_000_000
_TOKEN = re.compile(r'//[^\n]*|/\*.*?\*/|"[^"\r\n]*"|[{}]|(?:[^\s{}"/]|/(?![/*]))+|\s+', re.DOTALL)


@dataclass(frozen=True)
class Directive:
    name: str
    args: tuple[str, ...]
    line: int

    def numbers(self, start: int = 0) -> tuple[float, ...]:
        args = self.args[start:]
        if len(args) >= 2 and args[0] == "(" and args[-1] == ")":
            args = args[1:-1]
        try:
            values = tuple(float(value) for value in args)
        except ValueError as exc:
            raise ValueError(f"line {self.line}: {self.name} expects numeric arguments") from exc
        if not all(math.isfinite(value) and abs(value) <= MAX_NUMBER for value in values):
            raise ValueError(f"line {self.line}: non-finite or out-of-range {self.name} argument")
        return values


@dataclass(frozen=True)
class Stage:
    directives: tuple[Directive, ...]

    def get(self, name: str) -> Directive | None:
        return next((item for item in reversed(self.directives) if item.name == name.casefold()), None)

    def images(self) -> tuple[str, ...]:
        maps = [item for item in self.directives if item.name in {"map", "clampmap", "animmap"}]
        if len(maps) != 1:
            raise ValueError("stage must contain exactly one map, clampMap or animMap")
        directive = maps[0]
        if directive.name == "animmap":
            if len(directive.args) < 2 or len(directive.args) > MAX_ANIMATION_FRAMES + 1:
                raise ValueError(f"line {directive.line}: invalid animMap frame count")
            speed = Directive("animmap", directive.args[:1], directive.line).numbers()[0]
            if speed <= 0:
                raise ValueError(f"line {directive.line}: animMap speed must be positive")
            return directive.args[1:]
        if len(directive.args) != 1:
            raise ValueError(f"line {directive.line}: {directive.name} expects one image")
        return directive.args


@dataclass(frozen=True)
class Shader:
    name: str
    directives: tuple[Directive, ...]
    stages: tuple[Stage, ...]
    source: str
    line: int
    sha256: str

    def get(self, name: str) -> Directive | None:
        return next((item for item in reversed(self.directives) if item.name == name.casefold()), None)

    def dependencies(self, *, editor: bool = False) -> tuple[str, ...]:
        names = [name for stage in self.stages for name in stage.images() if not name.startswith("$")]
        sky = self.get("skyparms")
        if sky is not None:
            if len(sky.args) != 3:
                raise ValueError(f"{self.source}:{sky.line}: skyParms expects three arguments")
            for prefix in (sky.args[0], sky.args[2]):
                if prefix != "-":
                    names.extend(f"{prefix}_{side}.tga" for side in ("rt", "bk", "lf", "ft", "up", "dn"))
        if editor and (image := self.get("qer_editorimage")) is not None:
            if len(image.args) != 1:
                raise ValueError(f"{self.source}:{image.line}: qer_editorimage expects one image")
            names.append(image.args[0])
        return tuple(dict.fromkeys(names))


def parse(text: str, *, source: str = "<shader>") -> tuple[Shader, ...]:
    if len(text) > MAX_TEXT_SIZE:
        raise ValueError(f"{source}: shader text exceeds limit")
    tokens = []
    line = 1
    offset = 0
    while offset < len(text):
        match = _TOKEN.match(text, offset)
        if match is None or (text.startswith("/*", offset) and not match.group().endswith("*/")):
            raise ValueError(f"{source}:{line}: malformed shader token")
        raw = match.group()
        if not raw.isspace() and not raw.startswith(("//", "/*")):
            tokens.append((raw[1:-1] if raw.startswith('"') else raw, line))
            if len(tokens) > MAX_TOKENS:
                raise ValueError(f"{source}: shader token limit exceeded")
        line += raw.count("\n")
        offset = match.end()
    cursor = 0
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()

    def take_directive() -> Directive:
        nonlocal cursor
        name, location = tokens[cursor]
        cursor += 1
        args = []
        while cursor < len(tokens) and tokens[cursor][1] == location and tokens[cursor][0] not in {"{", "}"}:
            args.append(tokens[cursor][0])
            cursor += 1
        return Directive(name.casefold(), tuple(args), location)

    result = []
    while cursor < len(tokens):
        name, location = tokens[cursor]
        cursor += 1
        if name in {"{", "}"} or cursor >= len(tokens) or tokens[cursor][0] != "{":
            raise ValueError(f"{source}:{location}: expected shader name and opening brace")
        cursor += 1
        directives = []
        stages = []
        while cursor < len(tokens) and tokens[cursor][0] != "}":
            if tokens[cursor][0] != "{":
                directives.append(take_directive())
                continue
            cursor += 1
            stage = []
            while cursor < len(tokens) and tokens[cursor][0] != "}":
                if tokens[cursor][0] == "{":
                    raise ValueError(f"{source}:{tokens[cursor][1]}: nested shader stage")
                stage.append(take_directive())
            if cursor == len(tokens):
                raise ValueError(f"{source}:{location}: unclosed shader stage")
            cursor += 1
            stages.append(Stage(tuple(stage)))
            if len(stages) > MAX_STAGES:
                raise ValueError(f"{source}:{location}: too many shader stages")
        if cursor == len(tokens):
            raise ValueError(f"{source}:{location}: unclosed shader")
        cursor += 1
        result.append(Shader(name, tuple(directives), tuple(stages), source, location, digest))
    return tuple(result)
