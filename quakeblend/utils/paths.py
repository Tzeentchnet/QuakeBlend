"""Filesystem path helpers shared by the Blender import runners.

No bpy imports; safe to use from both the formats and blender layers, and
importable directly under plain pytest.
"""

from __future__ import annotations

from pathlib import Path, PureWindowsPath


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
