"""Unit tests for src/kbo_loader helpers."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.kbo_loader import strip_dots, convert_date


def test_strip_dots_basic():
    assert strip_dots("0403.101.811") == "0403101811"


def test_strip_dots_already_clean():
    assert strip_dots("0403101811") == "0403101811"


def test_strip_dots_padding():
    # KBO sometimes ships 9-digit numbers; ensure they get zero-padded
    result = strip_dots("403101811")
    assert len(result) == 10
    assert result == "0403101811"


def test_strip_dots_empty():
    assert strip_dots("") == ""


def test_strip_dots_none():
    assert strip_dots(None) is None


def test_strip_dots_establishment_eleven_digits():
    # Establishment numbers are 11 digits — must not be truncated by padding
    assert strip_dots("23000012345") == "23000012345"
    assert strip_dots("2.300.001.2345") == "23000012345"


def test_convert_date_iso():
    assert convert_date("15-01-2024") == "2024-01-15"


def test_convert_date_empty():
    assert convert_date("") in (None, "")


def test_convert_date_whitespace():
    assert convert_date("   ") in (None, "")


def test_convert_date_malformed():
    # Must not raise; implementation returns the original string unchanged
    result = convert_date("not-a-date")
    assert result == "not-a-date" or result is None or result == ""


def test_convert_date_partial():
    # Wrong shape should not crash
    result = convert_date("2024")
    assert result == "2024" or result is None or result == ""


if __name__ == "__main__":
    test_strip_dots_basic()
    test_strip_dots_already_clean()
    test_strip_dots_padding()
    test_strip_dots_empty()
    test_strip_dots_none()
    test_strip_dots_establishment_eleven_digits()
    test_convert_date_iso()
    test_convert_date_empty()
    test_convert_date_whitespace()
    test_convert_date_malformed()
    test_convert_date_partial()
    print("All KBO loader tests passed.")
