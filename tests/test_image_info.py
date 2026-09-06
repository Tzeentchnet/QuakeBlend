from __future__ import annotations

import struct

import pytest

from quakeblend.formats.image_info import image_dimensions


@pytest.mark.parametrize("suffix,data", [
    (".png", b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR" + struct.pack(">II", 64, 32)),
    (".tga", bytes((0, 0, 2)) + bytes(9) + struct.pack("<HH", 64, 32) + bytes((24, 0))),
    (".jpg", b"\xff\xd8\xff\xe0\0\x04AB\xff\xc0\0\x0b\x08" + struct.pack(">HH", 32, 64) + b"\x01\x01\x11\0"),
])
def test_dimensions(suffix, data):
    assert image_dimensions(data, suffix) == (64, 32)
    for length in (0, 1, 10):
        with pytest.raises(ValueError):
            image_dimensions(data[:length], suffix)


@pytest.mark.parametrize("width,height", [(0, 32), (64, 0), (65536, 32)])
def test_size_limits(width, height):
    with pytest.raises(ValueError, match="limits"):
        image_dimensions(b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR" + struct.pack(">II", width, height), ".png")


@pytest.mark.parametrize("data", [b"\xff\xd8", b"\xff\xd8\xff", b"\xff\xd8\xff\xda", b"\xff\xd8\xff\xe0\0\x01"])
def test_invalid_jpeg(data):
    with pytest.raises(ValueError):
        image_dimensions(data, ".jpeg")
