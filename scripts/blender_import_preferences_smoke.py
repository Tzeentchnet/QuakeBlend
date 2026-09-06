"""Check preference seeding with actual RNA operators and explicit overrides."""

from __future__ import annotations

import argparse
import importlib
import os
from pathlib import Path
import sys
import traceback

import bpy
from bpy_extras.io_utils import ImportHelper


def capture_preferences(extension_root, output_dir):
    output_dir.mkdir(parents=True, exist_ok=False)
    opened = False

    def capture():
        nonlocal opened
        try:
            if not opened:
                window = bpy.context.window_manager.windows[0]
                area = max(window.screen.areas, key=lambda area: area.width * area.height)
                area.type = "PREFERENCES"
                with bpy.context.temp_override(window=window, area=area):
                    bpy.ops.preferences.addon_show(module=extension_root)
                assert bpy.context.preferences.active_section == "ADDONS", "Preferences capture requires an installed extension"
                opened = True
                return 1
            window = next(window for window in bpy.context.window_manager.windows
                          if any(area.type == "PREFERENCES" for area in window.screen.areas))
            area = next(area for area in window.screen.areas if area.type == "PREFERENCES")
            region = next(region for region in area.regions if region.type == "WINDOW")
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=2)
                bpy.ops.screen.screenshot(filepath=str(output_dir / "preferences-top.png"))
            region = next(region for region in area.regions if region.type == "WINDOW")
            with bpy.context.temp_override(window=window, area=area, region=region):
                bpy.ops.view2d.scroll_down(page=True)
                bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=2)
                bpy.ops.screen.screenshot(filepath=str(output_dir / "preferences-bottom.png"))
            print("IMPORT_PREFERENCES_UI_OK", flush=True)
            bpy.ops.wm.quit_blender()
        except Exception:
            traceback.print_exc()
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(1)
        return None

    bpy.app.timers.register(capture, first_interval=1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extension-root", default="bl_ext.user_default.quakeblend")
    parser.add_argument("--persist", choices=("write", "read"))
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    assert not bpy.app.background and not sys.flags.optimize
    bpy.context.preferences.use_preferences_save = False
    bpy.context.preferences.view.show_splash = False
    if args.persist:
        expected = os.environ.get("BLENDER_USER_CONFIG")
        assert expected and Path(expected).is_dir(), "Persistence requires an existing explicit test config directory"
        assert Path(bpy.utils.user_resource("CONFIG")).resolve() == Path(expected).resolve(), "Blender config isolation failed"
    if args.extension_root == "quakeblend":
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    bpy.ops.preferences.addon_enable(module=args.extension_root)
    prefs_module = importlib.import_module(f"{args.extension_root}.blender.prefs")
    prefs = prefs_module.get_prefs(bpy.context)
    assert prefs is not None
    if args.persist != "read":
        assert prefs.default_q3_bsp_lighting == "FULLBRIGHT"
        assert prefs.default_q3_map_lighting == "RELIT"
        assert prefs.default_trigger_handling == prefs.default_clip_handling == prefs.default_hint_handling == "HIDDEN"
    original = {name: getattr(prefs, f"default_{name}") for name in prefs_module.IMPORT_DEFAULT_NAMES}
    choices = {"worldspawn_only": True, "group_entities": False, "create_materials": False,
               "import_brush_entities": False, "import_entities": False, "import_lights": False,
               "import_cameras": False, "trigger_handling": "SKIP", "clip_handling": "VISIBLE",
               "hint_handling": "SKIP", "q3_map_lighting": "FULLBRIGHT", "q3_bsp_lighting": "BAKED",
               "q3_animate_shaders": False, "q3_deform_geometry": False, "q3_material_mode": "DIRECT",
               "scale": .125, "light_energy": 2.0, "patch_level": 3, "stitch_goldsrc": True}
    if args.persist == "read":
        assert original == choices, (original, choices)
        print("IMPORT_PREFERENCES_REOPEN_OK", flush=True)
    captured = {}

    def capture(operator, context, *unused):
        captured.clear()
        captured.update({name: getattr(operator, name)
                 for name in (*choices, "q3_lighting") if hasattr(operator, name)})
        return {"FINISHED"}

    previous_invoke = ImportHelper.invoke
    try:
        for name, value in choices.items():
            setattr(prefs, f"default_{name}", value)
        ImportHelper.invoke = capture
        for kind in ("map", "bsp"):
            operation = getattr(bpy.ops.quakeblend, f"import_{kind}")
            assert operation("INVOKE_DEFAULT") == {"FINISHED"}
            assert "worldspawn_only" in captured and "q3_lighting" in captured
            for name, value in captured.items():
                expected = choices[f"q3_{kind}_lighting"] if name == "q3_lighting" else choices[name]
                assert value == expected, (kind, name, value, expected)
            assert operation("INVOKE_DEFAULT", worldspawn_only=False, create_materials=True,
                q3_lighting="RELIT", trigger_handling="HIDDEN") == {"FINISHED"}
            assert not captured["worldspawn_only"] and captured["create_materials"]
            assert captured["q3_lighting"] == "RELIT" and captured["trigger_handling"] == "HIDDEN"
            assert operation("INVOKE_DEFAULT") == {"FINISHED"}
            assert captured["worldspawn_only"] and not captured["create_materials"]
            assert captured["q3_lighting"] == choices[f"q3_{kind}_lighting"]
            runner = importlib.import_module(f"{args.extension_root}.blender.import_runner_{kind}")
            previous_run = runner.run
            try:
                runner.run = capture
                assert operation("EXEC_DEFAULT") == {"FINISHED"}
                assert not captured["worldspawn_only"] and captured["create_materials"]
                assert captured["q3_lighting"] == ("FULLBRIGHT" if kind == "bsp" else "RELIT")
            finally:
                runner.run = previous_run
        if args.persist == "write":
            bpy.ops.wm.save_userpref()
    finally:
        ImportHelper.invoke = previous_invoke
        for name, value in original.items():
            setattr(prefs, f"default_{name}", value)
    print("IMPORT_PREFERENCES_OK defaults explicit-overrides scripted-imports")
    if args.output_dir:
        capture_preferences(args.extension_root, args.output_dir)
    else:
        bpy.ops.wm.quit_blender()


if __name__ == "__main__":
    main()
