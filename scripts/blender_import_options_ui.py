"""Capture and validate the native file-browser options in a separate GUI process."""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import importlib
import os
from pathlib import Path
import shutil
import struct
import sys
import traceback

import bpy


def _resize_process_window(width: int, height: int) -> tuple[int, int] | None:
    if os.name != "nt":
        return None
    user32 = ctypes.windll.user32
    process_id = os.getpid()
    candidates = []
    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
    )

    @callback_type
    def collect(window_handle, _parameter):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(window_handle, ctypes.byref(owner))
        if owner.value == process_id and user32.IsWindowVisible(window_handle):
            client = wintypes.RECT()
            if user32.GetClientRect(window_handle, ctypes.byref(client)):
                candidates.append(
                    ((client.right - client.left) * (client.bottom - client.top), window_handle)
                )
        return True

    user32.EnumWindows(collect, 0)
    assert candidates, "Could not find the Blender window"
    window_handle = max(candidates)[1]
    get_window_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
    get_window_long.restype = ctypes.c_ssize_t
    style = get_window_long(window_handle, -16)
    extended_style = get_window_long(window_handle, -20)
    outer = wintypes.RECT(0, 0, width, height)
    if hasattr(user32, "AdjustWindowRectExForDpi"):
        assert user32.AdjustWindowRectExForDpi(
            ctypes.byref(outer), style, False, extended_style, user32.GetDpiForWindow(window_handle)
        )
    else:
        assert user32.AdjustWindowRectEx(
            ctypes.byref(outer), style, False, extended_style
        )
    assert user32.SetWindowPos(
        window_handle,
        0,
        0,
        0,
        outer.right - outer.left,
        outer.bottom - outer.top,
        0x0014,
    )
    client = wintypes.RECT()
    assert user32.GetClientRect(window_handle, ctypes.byref(client))
    return client.right - client.left, client.bottom - client.top


def _create_publication_source() -> tuple[Path, Path]:
    if os.name == "nt":
        root = Path(f"{os.environ.get('SystemDrive', 'C:')}\\QuakeBlendDemo")
    else:
        root = Path("/tmp/QuakeBlendDemo")
    root.mkdir(parents=False, exist_ok=False)
    source = root / "demo.bsp"
    source.write_bytes(b"IBSP" + struct.pack("<i", 46))
    return source, root


def _image_size(path: Path) -> tuple[int, int]:
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        return tuple(image.size)
    finally:
        bpy.data.images.remove(image)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--extension-root", default="quakeblend")
    parser.add_argument("--presets", action="store_true")
    parser.add_argument("--publication", action="store_true")
    parser.add_argument("--target-width", type=int, default=1600)
    parser.add_argument("--target-height", type=int, default=900)
    parser.add_argument("--minimum-width", type=int, default=1200)
    parser.add_argument("--minimum-height", type=int, default=700)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    assert not bpy.app.background and not sys.flags.optimize
    args.output_dir.mkdir(parents=True, exist_ok=False)
    publication_root = None
    if args.publication:
        assert args.source is None, "Publication mode creates its own neutral input"
        assert not args.presets, "Publication mode must not write operator presets"
        source, publication_root = _create_publication_source()
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False)
    else:
        assert args.source is not None and args.source.is_file()
        source = args.source.resolve()
    if args.extension_root == "quakeblend":
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        importlib.import_module(args.extension_root).register()
    else:
        bpy.ops.preferences.addon_enable(module=args.extension_root)
    attempts = 0
    invoked = False
    resized = False

    def capture():
        nonlocal attempts, invoked, resized
        try:
            attempts += 1
            if not invoked:
                bpy.ops.quakeblend.import_bsp("INVOKE_DEFAULT", filepath=str(source))
                invoked = True
                return 1
            window = next((window for window in bpy.context.window_manager.windows
                           if any(area.type == "FILE_BROWSER" for area in window.screen.areas)), None)
            if window is None:
                if attempts < 10:
                    return 1
                raise AssertionError("File browser did not open")
            area = next(area for area in window.screen.areas if area.type == "FILE_BROWSER")
            if args.publication and not resized:
                resized = True
                size = _resize_process_window(args.target_width, args.target_height)
                print("IMPORT_OPTIONS_PUBLICATION_CLIENT", size, flush=True)
                return 1
            operator = area.spaces.active.active_operator
            assert operator is not None
            print("IMPORT_UI_OPERATOR", operator.bl_idname, flush=True)
            controls = importlib.import_module(f"{args.extension_root}.blender.import_options")
            controls.check_import_options(operator, bpy.context)
            assert operator.detected_game == "Q3", operator.detected_game
            assert operator.q3_lighting == "FULLBRIGHT"
            assert operator.trigger_handling == "HIDDEN"
            area.spaces.active.show_region_tool_props = True
            region = next(region for region in area.regions if region.type == "TOOL_PROPS")
            with bpy.context.temp_override(window=window, area=area, region=region, active_operator=operator):
                bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=2)
                if not args.publication:
                    bpy.ops.screen.screenshot(filepath=str(args.output_dir / "bsp-options.png"))
                operator.worldspawn_only = True
                assert operator.import_entities and operator.import_lights and operator.import_brush_entities
                operator.worldspawn_only = False
                if args.presets:
                    assert os.environ.get("BLENDER_USER_RESOURCES"), "Preset check requires an isolated profile"
                    operator.q3_lighting = "BAKED"
                    operator.q3_animate_shaders = False
                    operator.q3_deform_geometry = False
                    operator.group_entities = False
                    operator.trigger_handling = "VISIBLE"
                    assert bpy.ops.wm.operator_preset_add(name=args.output_dir.name, operator=operator.bl_idname) == {"FINISHED"}
                    preset = bpy.utils.preset_find(args.output_dir.name, "operator/quakeblend.import_bsp")
                    assert preset
                    operator.q3_lighting = "FULLBRIGHT"
                    operator.q3_animate_shaders = True
                    operator.q3_deform_geometry = True
                    operator.group_entities = True
                    operator.trigger_handling = "HIDDEN"
                    assert bpy.ops.script.execute_preset(filepath=preset, menu_idname="WM_MT_operator_presets") == {"FINISHED"}
                    assert operator.q3_lighting == "BAKED" and not operator.q3_animate_shaders
                    assert not operator.q3_deform_geometry and not operator.group_entities
                    assert operator.trigger_handling == "VISIBLE"
                    operator.q3_lighting = "FULLBRIGHT"
                    print("IMPORT_OPTIONS_PRESET_OK lighting effects grouping visibility", flush=True)
                region = next(region for region in area.regions if region.type == "TOOL_PROPS")
                with bpy.context.temp_override(window=window, area=area, region=region):
                    bpy.ops.view2d.scroll_down(page=True)
                    bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=2)
                    screenshot = args.output_dir / (
                        "import-options-native.png" if args.publication else "bsp-effects.png"
                    )
                    bpy.ops.screen.screenshot(filepath=str(screenshot))
                    if args.publication:
                        size = _image_size(screenshot)
                        print("IMPORT_OPTIONS_PUBLICATION_SIZE", *size, flush=True)
                        assert size[0] >= args.minimum_width, size
                        assert size[1] >= args.minimum_height, size
            print("IMPORT_OPTIONS_UI_OK Q3 Fullbright hidden-triggers", flush=True)
            if publication_root is not None:
                shutil.rmtree(publication_root)
            bpy.ops.wm.quit_blender()
        except Exception:
            traceback.print_exc()
            sys.stdout.flush()
            sys.stderr.flush()
            if publication_root is not None:
                shutil.rmtree(publication_root, ignore_errors=True)
            os._exit(1)
        return None

    bpy.app.timers.register(capture, first_interval=1)


if __name__ == "__main__":
    main()
