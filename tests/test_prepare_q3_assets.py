from __future__ import annotations

import hashlib
import json
import struct
import zipfile

import pytest

from quakeblend.formats import bsp_q3
from quakeblend.utils.q3_assets import Q3Assets
from scripts.prepare_q3_assets import prepare


@pytest.fixture
def installation(tmp_path):
    root = tmp_path / "game"
    (root / "baseq3").mkdir(parents=True)
    textures = b"textures/example_trans".ljust(64, b"\x00") + struct.pack("<ii", 0, 0)
    header_size = 8 + bsp_q3.NUM_LUMPS * 8
    header = b"IBSP" + struct.pack("<i", 46)
    header += b"".join(struct.pack("<ii", header_size, len(textures) if lump == bsp_q3.LUMP_TEXTURES else 0)
                       for lump in range(bsp_q3.NUM_LUMPS))
    for number in range(9):
        with zipfile.ZipFile(root / "baseq3" / f"pak{number}.pk3", "w") as archive:
            if number == 0:
                archive.writestr("maps/test.bsp", header + textures)
                archive.writestr("scripts/test.shader", '''textures/example_trans {
qer_editorimage textures/editor.tga
{ animMap 10 textures/first.tga textures/second.tga }
}''')
                archive.writestr("textures/first.jpg", b"first-image")
                archive.writestr("textures/second.tga", b"second-image")
                archive.writestr("textures/editor.jpg", b"editor-image")
                archive.writestr("textures/unused.tga", b"unused-image")
            if number == 8:
                archive.writestr("textures/first.jpg", b"overridden-image")
    return root


def test_prepare_selects_full_dependencies(installation, tmp_path):
    output = tmp_path / "prepared"
    report = prepare(installation, output, member="maps/test.bsp")
    assert (output / "assets/textures/first.jpg").read_bytes() == b"overridden-image"
    assert (output / "assets/textures/second.tga").read_bytes() == b"second-image"
    assert not (output / "assets/textures/unused.tga").exists()
    assert not (output / "assets/textures/example_trans.jpg").exists()
    assert json.loads((output / "audit.json").read_text()) == json.loads(json.dumps(report))
    spec = Q3Assets.from_folder(output / "assets").material("textures/example_trans")
    assert spec.missing == ()
    assert spec.editor_image.name == "textures/editor.jpg"
    assert len(report["resources"]) == 5
    with pytest.raises(FileExistsError):
        prepare(installation, output, member="maps/test.bsp")


def test_audit_never_extracts(installation, tmp_path):
    output = tmp_path / "audit"
    report = prepare(installation, output, member="maps/test.bsp", audit_only=True)
    assert report["audit_only"]
    assert list(output.iterdir()) == [output / "audit.json"]


def test_optional_source_hash_is_caller_supplied(installation, tmp_path):
    with zipfile.ZipFile(installation / "baseq3/pak0.pk3") as archive:
        expected = hashlib.sha256(archive.read("maps/test.bsp")).hexdigest()
    report = prepare(
        installation,
        tmp_path / "matching",
        member="maps/test.bsp",
        expected_sha256=expected.upper(),
        audit_only=True,
    )
    assert report["source"]["sha256"] == expected
    with pytest.raises(ValueError, match="expected snapshot"):
        prepare(
            installation,
            tmp_path / "different",
            member="maps/test.bsp",
            expected_sha256="0" * 64,
            audit_only=True,
        )
    assert not (tmp_path / "different").exists()


def test_reject_installation_output(installation):
    with pytest.raises(ValueError, match="outside"):
        prepare(installation, installation / "output", member="maps/test.bsp")


def test_failed_write_removes_partial_output(installation, tmp_path, monkeypatch):
    from pathlib import Path

    output = tmp_path / "partial"
    original_open = Path.open

    def failing_open(path, mode="r", *args, **kwargs):
        if mode == "xb" and path.name == "first.jpg":
            raise OSError("simulated full disk")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failing_open)
    with pytest.raises(OSError, match="full disk"):
        prepare(installation, output, member="maps/test.bsp")
    assert not output.exists()
