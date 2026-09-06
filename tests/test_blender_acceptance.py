"""Offline checks for the isolated Blender acceptance launcher."""

from __future__ import annotations

from pathlib import Path
import runpy
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def launcher(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    config = profile / "config"
    config.mkdir(parents=True)
    extension = SimpleNamespace(__file__=str(profile / "extensions/quakeblend/__init__.py"))
    bpy = SimpleNamespace(
        app=SimpleNamespace(version_string="5.0.0", build_hash=b"fixture"),
        data=SimpleNamespace(filepath=""),
        context=SimpleNamespace(preferences=SimpleNamespace(use_preferences_save=True)),
        utils=SimpleNamespace(user_resource=Mock(return_value=str(config))),
        ops=SimpleNamespace(preferences=SimpleNamespace(addon_enable=Mock(return_value={"FINISHED"}))),
    )
    monkeypatch.setenv("BLENDER_USER_RESOURCES", str(profile))
    monkeypatch.setenv("BLENDER_USER_CONFIG", str(config))
    monkeypatch.setitem(sys.modules, "bpy", bpy)
    monkeypatch.setitem(sys.modules, "bl_ext.user_default.quakeblend", extension)
    script = tmp_path / "target.py"
    monkeypatch.setattr(sys, "argv", ["blender", "--", "--version", "5.0.0", str(script),
                                     "--output-dir", str(tmp_path / "output")])
    namespace = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/blender_acceptance.py"))
    invoked = Mock()
    monkeypatch.setattr(runpy, "run_path", invoked)
    return SimpleNamespace(main=namespace["main"], bpy=bpy, extension=extension,
                           profile=profile, config=config, script=script, invoked=invoked)


def test_launcher_disables_autosave_and_forwards_arguments(launcher):
    launcher.main()
    assert not launcher.bpy.context.preferences.use_preferences_save
    launcher.bpy.ops.preferences.addon_enable.assert_called_once_with(module="bl_ext.user_default.quakeblend")
    launcher.invoked.assert_called_once_with(str(launcher.script.resolve()), run_name="__main__")
    assert sys.argv == [str(launcher.script.resolve()), "--", "--output-dir",
                        str(launcher.profile.parent / "output")]


@pytest.mark.parametrize("failure", ["version", "open_scene", "missing_config", "outside_config",
                                     "resolved_config", "outside_extension", "missing_environment"])
def test_launcher_rejects_unsafe_start_before_enable(launcher, monkeypatch, failure):
    if failure == "version":
        launcher.bpy.app.version_string = "5.1.1"
    elif failure == "open_scene":
        launcher.bpy.data.filepath = "existing.blend"
    elif failure == "missing_config":
        launcher.config.rmdir()
    elif failure == "outside_config":
        monkeypatch.setenv("BLENDER_USER_CONFIG", str(launcher.profile.parent))
    elif failure == "resolved_config":
        launcher.bpy.utils.user_resource.return_value = str(launcher.profile.parent)
    elif failure == "outside_extension":
        launcher.extension.__file__ = str(launcher.profile.parent / "foreign/__init__.py")
    else:
        monkeypatch.delenv("BLENDER_USER_CONFIG")
    with pytest.raises((AssertionError, KeyError)):
        launcher.main()
    launcher.bpy.ops.preferences.addon_enable.assert_not_called()
    launcher.invoked.assert_not_called()
