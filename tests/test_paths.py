"""Tests for the ``safe_join_under_root`` path-traversal guard."""

from __future__ import annotations

from pathlib import Path

import pytest

from quakeblend.utils import paths as qb_paths


def test_safe_join_simple_relative_name(tmp_path: Path) -> None:
    result = qb_paths.safe_join_under_root(tmp_path, "brick1.wal")
    assert result == tmp_path / "brick1.wal"


def test_safe_join_nested_relative_parts(tmp_path: Path) -> None:
    result = qb_paths.safe_join_under_root(tmp_path, "textures", "brick1.wal")
    assert result == tmp_path / "textures" / "brick1.wal"


def test_safe_join_allows_texture_style_subpath(tmp_path: Path) -> None:
    # Q3 texture names often look like "common/caulk" or "base_wall/x".
    result = qb_paths.safe_join_under_root(tmp_path, "common/caulk.tga")
    assert result == tmp_path / "common/caulk.tga"


def test_safe_join_rejects_parent_traversal(tmp_path: Path) -> None:
    assert qb_paths.safe_join_under_root(tmp_path, "../secret.wal") is None
    assert qb_paths.safe_join_under_root(tmp_path, "../../etc/passwd.wal") is None
    assert qb_paths.safe_join_under_root(tmp_path, "sub/../../escape.wal") is None


def test_safe_join_rejects_absolute_posix_style_path(tmp_path: Path) -> None:
    assert qb_paths.safe_join_under_root(tmp_path, "/etc/passwd") is None


def test_safe_join_rejects_windows_drive_path(tmp_path: Path) -> None:
    assert qb_paths.safe_join_under_root(tmp_path, "C:\\Windows\\system32\\config") is None
    assert qb_paths.safe_join_under_root(tmp_path, "C:/Windows/system32/config") is None


def test_safe_join_rejects_empty_input(tmp_path: Path) -> None:
    assert qb_paths.safe_join_under_root(tmp_path) is None
    assert qb_paths.safe_join_under_root(tmp_path, "") is None


def test_safe_join_traversal_that_stays_inside_root_is_allowed(tmp_path: Path) -> None:
    # "sub/../file.wal" normalizes back to root/file.wal without escaping.
    result = qb_paths.safe_join_under_root(tmp_path, "sub/../file.wal")
    assert result is not None
    assert result.resolve() == (tmp_path / "file.wal").resolve()


def test_file_asset_key_is_stable_and_member_specific(tmp_path: Path) -> None:
    archive = tmp_path / "textures.wad"
    archive.write_bytes(b"revision one")

    first = qb_paths.file_asset_key(archive, namespace="wad", member="BRICK")
    same = qb_paths.file_asset_key(archive, namespace="wad", member="brick")
    other_member = qb_paths.file_asset_key(archive, namespace="wad", member="metal")

    assert first == same
    assert first != other_member


def test_file_asset_key_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        qb_paths.file_asset_key(tmp_path / "missing.wad", namespace="wad")


def test_texture_root_index_resolves_case_insensitive_aliases(tmp_path: Path) -> None:
    texture = tmp_path / "Textures" / "Base_Wall" / "Brick.WAL"
    texture.parent.mkdir(parents=True)
    texture.write_bytes(b"wal")

    index = qb_paths.TextureRootIndex(tmp_path)

    assert index.resolve("base_wall/brick") == (texture.resolve(), "wal")
    assert index.resolve("TEXTURES/BASE_WALL/BRICK.WAL") == (texture.resolve(), "wal")


def test_texture_root_index_honors_kind_and_wal_precedence(tmp_path: Path) -> None:
    wal = tmp_path / "stone.wal"
    image = tmp_path / "stone.PNG"
    wal.write_bytes(b"wal")
    image.write_bytes(b"png")

    index = qb_paths.TextureRootIndex(tmp_path)

    assert index.resolve("stone") == (wal.resolve(), "wal")
    assert index.resolve("stone", kind="image") == (image.resolve(), "image")
    assert index.resolve("stone.png") == (image.resolve(), "image")


def test_texture_root_index_prefers_exact_path_over_suffix_alias(tmp_path: Path) -> None:
    exact = tmp_path / "brick.wal"
    nested = tmp_path / "a" / "brick.wal"
    nested.parent.mkdir()
    exact.write_bytes(b"exact")
    nested.write_bytes(b"nested")

    index = qb_paths.TextureRootIndex(tmp_path)

    assert index.resolve("brick", kind="wal") == (exact.resolve(), "wal")
    assert index.resolve("a/brick", kind="wal") == (nested.resolve(), "wal")


def test_texture_root_index_rejects_unsafe_and_unsupported_names(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("not a texture", encoding="ascii")
    index = qb_paths.TextureRootIndex(tmp_path)

    assert index.resolve("../secret") is None
    assert index.resolve("C:/secret") is None
    assert index.resolve("notes") is None
