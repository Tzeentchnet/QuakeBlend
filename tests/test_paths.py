"""Tests for the ``safe_join_under_root`` path-traversal guard."""

from __future__ import annotations

from pathlib import Path

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
