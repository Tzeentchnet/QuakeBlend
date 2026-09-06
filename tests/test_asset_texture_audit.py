from __future__ import annotations

import pytest

from scripts.audit_asset_textures import audit_textures


def test_texture_audit_distinguishes_exact_ambiguous_encoded_and_missing() -> None:
    paths = [
        "texture-wads/greek/brick.png",
        "texture-wads/old/duplicate.png",
        "texture-wads/new/duplicate.PNG",
        "texture-wads/liquid/star_water.png",
        "texture-wads/greek/plus_0button_fbr.png",
        "elsewhere/absent.png",
        "texture-wads/greek/absent.txt",
    ]
    tree = {"sha": "pinned", "truncated": False,
            "tree": [{"path": path, "type": "blob"} for path in paths]}
    result = audit_textures({"BRICK", "duplicate", "*water", "+0button", "absent"}, tree)
    assert result == {
        "revision": "pinned",
        "required_textures": 5,
        "exact": {"BRICK": paths[0]},
        "ambiguous": {"duplicate": sorted(paths[1:3])},
        "encoded_candidates": {"*water": [paths[3]], "+0button": [paths[4]]},
        "missing": ["absent"],
    }


@pytest.mark.parametrize("truncated", [True, None])
def test_texture_audit_rejects_incomplete_tree(truncated) -> None:
    with pytest.raises(ValueError, match="complete"):
        audit_textures(set(), {"truncated": truncated})
