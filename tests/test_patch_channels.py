from __future__ import annotations

import pytest

from quakeblend.formats.common import Vec3
from quakeblend.formats.patch import Control, Patch, serialize_patch_def2, tessellate


@pytest.mark.parametrize("width", [3, 5])
def test_channels_follow_positions_and_uvs(width):
    controls = [Control(Vec3(column, row, 0), (column / 4, row / 2),
                        (column / 4, row / 2, .25, .5, 1, 1, 0, 0, 1))
                for row in range(3) for column in range(width)]
    result = tessellate(Patch(width, 3, controls), level=4)
    assert len(result.channels) == len(result.vertices)
    for position, uv, channels in zip(result.vertices, result.uvs, result.channels):
        assert channels[:2] == pytest.approx(uv)
        assert channels[:2] == pytest.approx((position.x / 4, position.y / 2))
        assert channels[2:] == pytest.approx((.25, .5, 1, 1, 0, 0, 1))
    plain = Patch(width, 3, [Control(control.pos, control.uv) for control in controls])
    assert serialize_patch_def2("demo", plain) == serialize_patch_def2("demo", Patch(width, 3, controls))
    assert result.quads == tessellate(plain, level=4).quads


def test_mixed_channels_rejected():
    controls = [Control(Vec3(0, 0, 0), (0, 0)) for _ in range(9)]
    controls[0] = Control(Vec3(0, 0, 0), (0, 0), (1,))
    with pytest.raises(ValueError, match="channels"):
        tessellate(Patch(3, 3, controls))
