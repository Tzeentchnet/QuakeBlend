"""Architecture constraints shared by every supported Python runtime."""

from __future__ import annotations

import ast
from pathlib import Path


FORBIDDEN_MODULES = {"bmesh", "bpy", "mathutils"}
PURE_DIRECTORIES = (Path("quakeblend/formats"), Path("quakeblend/utils"))


def test_pure_layers_do_not_import_blender_modules() -> None:
    violations: list[str] = []
    for directory in PURE_DIRECTORIES:
        for path in directory.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported = {alias.name.split(".", 1)[0] for alias in node.names}
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported = {node.module.split(".", 1)[0]}
                else:
                    continue
                forbidden = imported & FORBIDDEN_MODULES
                if forbidden:
                    violations.append(
                        f"{path}:{node.lineno} imports {', '.join(sorted(forbidden))}"
                    )

    assert violations == []


def test_runtime_modules_use_relative_package_imports() -> None:
    violations: list[str] = []
    for path in Path("quakeblend").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = [
                    alias.name
                    for alias in node.names
                    if alias.name == "quakeblend"
                    or alias.name.startswith("quakeblend.")
                ]
            elif (
                isinstance(node, ast.ImportFrom)
                and node.level == 0
                and node.module
                and (
                    node.module == "quakeblend"
                    or node.module.startswith("quakeblend.")
                )
            ):
                imported = [node.module]
            else:
                continue

            for module in imported:
                violations.append(f"{path}:{node.lineno} imports {module}")

    assert violations == []
