"""Tests for ``quakeblend.formats.common``."""

from __future__ import annotations

import io
import struct

import pytest

from quakeblend.formats.common import (
    BinaryReader, Plane, Vec3, chunks, parse_finite_float, read_exact,
)


def test_vec3_arithmetic_and_products() -> None:
    a = Vec3(1.0, 2.0, 3.0)
    b = Vec3(-4.0, 5.0, -6.0)

    assert a + b == Vec3(-3.0, 7.0, -3.0)
    assert a - b == Vec3(5.0, -3.0, 9.0)
    assert a * 2 == Vec3(2.0, 4.0, 6.0)
    assert 2 * a == Vec3(2.0, 4.0, 6.0)
    assert -a == Vec3(-1.0, -2.0, -3.0)
    assert a.dot(b) == pytest.approx(-12.0)
    assert a.cross(b) == Vec3(-27.0, -6.0, 13.0)
    assert a.as_tuple() == (1.0, 2.0, 3.0)
    assert tuple(a) == (1.0, 2.0, 3.0)


def test_vec3_length_and_normalized() -> None:
    vec = Vec3(3.0, 4.0, 0.0)

    assert vec.length() == pytest.approx(5.0)
    assert vec.normalized() == Vec3(0.6, 0.8, 0.0)
    assert vec.normalized().length() == pytest.approx(1.0)


def test_vec3_normalized_zero_vector() -> None:
    assert Vec3(0.0, 0.0, 0.0).normalized() == Vec3(0.0, 0.0, 0.0)


def test_plane_from_points_and_signed_distance() -> None:
    plane = Plane.from_points(Vec3(0.0, 0.0, 0.0), Vec3(1.0, 0.0, 0.0), Vec3(0.0, 1.0, 0.0))

    assert plane.normal == Vec3(0.0, 0.0, -1.0)
    assert plane.dist == pytest.approx(0.0)
    assert plane.signed_distance(Vec3(0.0, 0.0, 2.0)) == pytest.approx(-2.0)
    assert plane.signed_distance(Vec3(0.0, 0.0, -3.0)) == pytest.approx(3.0)


def test_binary_reader_read_exact_bytes() -> None:
    reader = BinaryReader(io.BytesIO(b"quake"))

    assert reader.read(5) == b"quake"


def test_binary_reader_read_raises_on_short_read() -> None:
    reader = BinaryReader(io.BytesIO(b"abc"))

    with pytest.raises(EOFError, match=r"expected 5 bytes, got 3"):
        reader.read(5)


def test_binary_reader_reads_numeric_types_and_vec3() -> None:
    payload = (
        struct.pack("<B", 0xFE)
        + struct.pack("<H", 0x1234)
        + struct.pack("<I", 0x89ABCDEF)
        + struct.pack("<h", -1234)
        + struct.pack("<i", -56789)
        + struct.pack("<f", 1.25)
        + struct.pack("<fff", 1.0, -2.5, 3.25)
    )
    reader = BinaryReader(io.BytesIO(payload))

    assert reader.u8() == 0xFE
    assert reader.u16() == 0x1234
    assert reader.u32() == 0x89ABCDEF
    assert reader.s16() == -1234
    assert reader.s32() == -56789
    assert reader.f32() == pytest.approx(1.25)
    assert reader.vec3() == Vec3(1.0, -2.5, 3.25)


def test_binary_reader_fixed_string_handles_null_termination() -> None:
    reader = BinaryReader(io.BytesIO(b"name\x00padplain"))

    assert reader.fixed_string(8) == "name"
    assert reader.fixed_string(5) == "plain"


def test_binary_reader_unpack_and_iter_struct() -> None:
    packed = struct.pack("<HI", 0x1234, 0x89ABCDEF)
    iter_payload = struct.pack("<hh", 1, -2) + struct.pack("<hh", 3, -4)

    assert BinaryReader(io.BytesIO(packed)).unpack("HI") == (0x1234, 0x89ABCDEF)
    assert list(BinaryReader(io.BytesIO(iter_payload)).iter_struct("hh", 2)) == [(1, -2), (3, -4)]


def test_read_exact_reads_requested_bytes() -> None:
    assert read_exact(io.BytesIO(b"abcdef"), 4) == b"abcd"


def test_read_exact_raises_on_short_read() -> None:
    with pytest.raises(EOFError, match=r"expected 4 bytes, got 2"):
        read_exact(io.BytesIO(b"ab"), 4)


def test_chunks_splits_bytes_and_preserves_tail() -> None:
    assert list(chunks(b"abcdefg", 3)) == [b"abc", b"def", b"g"]


def test_chunks_empty_sequence_is_empty() -> None:
    assert list(chunks(b"", 4)) == []


def test_parse_finite_float_accepts_finite_values() -> None:
    assert parse_finite_float("-1.25e2", context="coordinate") == -125.0


@pytest.mark.parametrize("token", ["nan", "inf", "-inf"])
def test_parse_finite_float_rejects_non_finite_values(token: str) -> None:
    with pytest.raises(ValueError, match="coordinate must be finite"):
        parse_finite_float(token, context="coordinate")
