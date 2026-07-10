"""Filesystem path helpers shared by the Blender import runners.

No bpy imports; safe to use from both the formats and blender layers, and
importable directly under plain pytest.
"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath, PureWindowsPath


_TEXTURE_KINDS = {
    ".wal": "wal",
    ".tga": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".png": "image",
}


class TextureRootIndex:
    """Case-insensitive lookup index for supported files beneath one root."""

    def __init__(self, root: Path) -> None:
        self._paths: dict[str, dict[str, Path]] = {"wal": {}, "image": {}}
        try:
            resolved_root = root.resolve(strict=True)
        except OSError:
            return
        if not resolved_root.is_dir():
            return

        entries: list[tuple[str, str, Path]] = []
        for directory, dirnames, filenames in os.walk(resolved_root):
            dirnames.sort(key=str.casefold)
            for filename in sorted(filenames, key=str.casefold):
                kind = _TEXTURE_KINDS.get(Path(filename).suffix.casefold())
                if kind is None:
                    continue
                path = Path(directory, filename)
                try:
                    resolved = path.resolve(strict=True)
                except OSError:
                    continue
                if not resolved.is_relative_to(resolved_root):
                    continue
                relative = resolved.relative_to(resolved_root).as_posix().casefold()
                entries.append((relative, kind, resolved))

        entries.sort(key=lambda item: (item[0], item[1], item[2].as_posix().casefold()))
        for relative, kind, path in entries:
            suffix = path.suffix.casefold()
            parts = relative.split("/")
            self._paths[kind].setdefault(relative, path)
            self._paths[kind].setdefault(relative[:-len(suffix)], path)

        for relative, kind, path in entries:
            suffix = path.suffix.casefold()
            parts = relative.split("/")
            for offset in range(1, len(parts)):
                alias = "/".join(parts[offset:])
                self._paths[kind].setdefault(alias, path)
                self._paths[kind].setdefault(alias[:-len(suffix)], path)

    def resolve(self, name: str, *, kind: str | None = None) -> tuple[Path, str] | None:
        if kind is not None and kind not in self._paths:
            raise ValueError(f"unsupported texture kind {kind!r}")
        normalized = name.strip().replace("\\", "/").casefold()
        posix_name = PurePosixPath(normalized)
        if (
            not normalized
            or posix_name.is_absolute()
            or PureWindowsPath(normalized).is_absolute()
            or ":" in normalized
            or ".." in posix_name.parts
        ):
            return None

        explicit_kind = _TEXTURE_KINDS.get(posix_name.suffix)
        if kind is not None and explicit_kind not in (None, kind):
            return None
        kinds = (
            (kind,)
            if kind is not None
            else (explicit_kind,) if explicit_kind is not None else ("wal", "image")
        )
        for kind in kinds:
            path = self._paths[kind].get(normalized)
            if path is not None:
                return path, kind
        return None


def safe_join_under_root(root: Path, *parts: str) -> Path | None:
    """Join ``parts`` onto ``root`` and return the candidate path, or ``None``
    if the result would escape ``root``.

    Texture/material names embedded in ``.map``/``.bsp`` files are untrusted
    input (the file may come from a downloaded mod). Joining them onto a
    user-selected texture root with the plain ``/`` operator is unsafe:
    ``pathlib`` silently discards the left-hand side if a joined part is
    absolute, and ``..`` segments can walk back out of ``root`` entirely.
    This helper rejects both cases.

    The returned path is *not* resolved/existence-checked beyond the
    containment check, so callers can still call ``.exists()``, ``with_suffix()``,
    etc. on it as usual.
    """
    if not parts or any(not p for p in parts):
        return None
    for part in parts:
        if Path(part).is_absolute() or PureWindowsPath(part).is_absolute() or ":" in part:
            return None
    candidate = root.joinpath(*parts)
    try:
        resolved_root = root.resolve()
        resolved_candidate = candidate.resolve()
    except OSError:
        return None
    if not resolved_candidate.is_relative_to(resolved_root):
        return None
    return candidate


def file_asset_key(path: Path, *, namespace: str, member: str = "") -> str:
    """Return a stable key for one revision of a file-backed asset."""
    resolved = path.resolve(strict=True)
    stat = resolved.stat()
    normalized_member = member.replace("\\", "/").casefold()
    return "|".join((
        namespace,
        resolved.as_posix().casefold(),
        str(stat.st_size),
        str(stat.st_mtime_ns),
        normalized_member,
    ))
