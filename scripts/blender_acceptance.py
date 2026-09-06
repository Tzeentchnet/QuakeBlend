"""Run an acceptance script against a version-checked, isolated Blender profile."""

from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path
import runpy
import sys

import bpy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("script", type=Path)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    if not __debug__:
        raise RuntimeError("Run acceptance without Python optimization")
    assert bpy.app.version_string == args.version, bpy.app.version_string
    assert not bpy.data.filepath, "Start with --factory-startup"
    resources = Path(os.environ["BLENDER_USER_RESOURCES"]).resolve()
    config = Path(os.environ["BLENDER_USER_CONFIG"]).resolve()
    assert resources.is_dir() and config.is_dir() and config.is_relative_to(resources)
    assert Path(bpy.utils.user_resource("CONFIG")).resolve() == config
    bpy.context.preferences.use_preferences_save = False
    extension_root = "bl_ext.user_default.quakeblend"
    module = importlib.import_module(extension_root)
    assert Path(module.__file__).resolve().is_relative_to(resources)
    assert bpy.ops.preferences.addon_enable(module=extension_root) == {"FINISHED"}
    print("QUAKEBLEND_ACCEPTANCE_RUNTIME " + json.dumps({
        "blender": bpy.app.version_string,
        "build_hash": bpy.app.build_hash.decode("ascii"),
        "python": sys.version,
        "config": str(config),
        "extension": str(Path(module.__file__).resolve()),
    }), flush=True)
    script = args.script.resolve()
    sys.argv = [str(script), "--", *args.arguments]
    runpy.run_path(str(script), run_name="__main__")


if __name__ == "__main__":
    main()
