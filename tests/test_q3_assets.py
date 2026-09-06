from __future__ import annotations

import zipfile

import pytest

from quakeblend.utils.q3_assets import Q3Assets, resource_name


def test_shader_first_and_tga_jpeg_fallback(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "textures").mkdir()
    (tmp_path / "scripts/demo.shader").write_text('''textures/demo_trans {
{ map textures/base.tga }
}''')
    (tmp_path / "textures/base.jpg").write_bytes(b"jpeg")
    (tmp_path / "textures/demo_trans.tga").write_bytes(b"wrong direct image")
    assets = Q3Assets.from_folder(tmp_path)
    spec = assets.material("TEXTURES/DEMO_trans")
    assert spec.shader is not None
    assert spec.missing == ()
    assert spec.images[0][1].name == "textures/base.jpg"
    assert assets.image("base") is None
    assert assets.image("textures/base.tga").name == "textures/base.jpg"


def test_package_overrides_and_shader_ambiguity(tmp_path):
    packages = [tmp_path / "pak0.pk3", tmp_path / "pak1.pk3"]
    for index, package in enumerate(packages):
        with zipfile.ZipFile(package, "w") as archive:
            archive.writestr("textures/base.jpg", bytes([index]))
            archive.writestr(f"scripts/test{index}.shader", "textures/test { { map textures/base.jpg } }")
    assets = Q3Assets.from_packages(packages)
    assert assets.read(assets.image("textures/base")) == b"\x01"
    with pytest.raises(ValueError, match="Ambiguous"):
        assets.shader("textures/test")


@pytest.mark.parametrize("name", ["../bad", "/bad", "a/../../bad", "C:/bad", "a//b", "a/./b", "", "bad\x00",
                                  "textures/con.tga", "textures/base.jpg.", "textures/a?.jpg", "a\nb"])
def test_unsafe_names(name):
    with pytest.raises(ValueError):
        resource_name(name)


def test_unknown_dependency_not_silently_replaced(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/test.shader").write_text("demo { { map absent.tga } }")
    assert Q3Assets.from_folder(tmp_path).material("demo").missing == ("absent.tga",)


def test_duplicate_package_members(tmp_path):
    path = tmp_path / "pak.pk3"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("textures/base.tga", b"one")
        archive.writestr("Textures/Base.tga", b"two")
    with pytest.raises(ValueError, match="Duplicate"):
        Q3Assets.from_packages([path])


def test_member_and_total_limits(tmp_path, monkeypatch):
    from quakeblend.utils import q3_assets

    (tmp_path / "one.tga").write_bytes(b"1234")
    (tmp_path / "two.tga").write_bytes(b"5678")
    assets = Q3Assets.from_folder(tmp_path)
    monkeypatch.setattr(q3_assets, "MAX_MEMBER_BYTES", 3)
    with pytest.raises(ValueError, match="byte limit"):
        assets.read(assets.image("one"))
    monkeypatch.setattr(q3_assets, "MAX_MEMBER_BYTES", 4)
    monkeypatch.setattr(q3_assets, "MAX_TOTAL_BYTES", 7)
    assert assets.read(assets.image("one")) == b"1234"
    with pytest.raises(ValueError, match="byte limit"):
        assets.read(assets.image("two"))


def test_changed_file_size_rejected(tmp_path):
    path = tmp_path / "one.tga"
    path.write_bytes(b"1234")
    assets = Q3Assets.from_folder(tmp_path)
    path.write_bytes(b"12345")
    with pytest.raises(ValueError, match="size changed"):
        assets.read(assets.image("one"))
