"""Bounded image dimensions without pixel decoding or Blender data blocks."""

from __future__ import annotations

import struct

from ..utils.constants import MAX_TEXTURE_DIMENSION, MAX_TEXTURE_PIXELS


def image_dimensions(data: bytes, suffix: str) -> tuple[int, int]:
    suffix = suffix.casefold()
    try:
        if suffix == ".png":
            if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR" or data[8:12] != b"\x00\x00\x00\x0d":
                raise ValueError("Invalid PNG header")
            width, height = struct.unpack_from(">II", data, 16)
        elif suffix == ".tga":
            if len(data) < 18 or data[2] not in {1, 2, 3, 9, 10, 11}:
                raise ValueError("Invalid TGA header")
            width, height = struct.unpack_from("<HH", data, 12)
        elif suffix in {".jpg", ".jpeg"}:
            if data[:2] != b"\xff\xd8":
                raise ValueError("Invalid JPEG header")
            offset = 2
            while offset < len(data):
                if data[offset] != 255:
                    raise ValueError("Invalid JPEG marker")
                while offset < len(data) and data[offset] == 255:
                    offset += 1
                marker = data[offset]
                offset += 1
                if marker in {0xD9, 0xDA, 0}:
                    break
                if marker in {0x01, *range(0xD0, 0xD9)}:
                    continue
                length = struct.unpack_from(">H", data, offset)[0]
                if length < 2 or offset + length > len(data):
                    raise ValueError("Truncated JPEG segment")
                if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                    if length < 8:
                        raise ValueError("Invalid JPEG frame")
                    height, width = struct.unpack_from(">HH", data, offset + 3)
                    break
                offset += length
            else:
                raise ValueError("JPEG dimensions not found")
            if marker not in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                raise ValueError("JPEG dimensions not found")
        else:
            raise ValueError(f"Unsupported image format: {suffix}")
    except (IndexError, struct.error, UnboundLocalError) as exc:
        raise ValueError("Truncated image header") from exc
    if not (0 < width <= MAX_TEXTURE_DIMENSION and 0 < height <= MAX_TEXTURE_DIMENSION
            and width * height <= MAX_TEXTURE_PIXELS):
        raise ValueError("Image dimensions outside supported limits")
    return width, height


def read_image_dimensions(path):
    with path.open("rb") as stream:
        return image_dimensions(stream.read(1024 * 1024), path.suffix)
