"""Unit tests for backend/utils.py helpers."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from utils import clean_cbe, is_valid_nace, parse_nace_list


def test_clean_cbe_dotted():
    assert clean_cbe("0403.101.811") == "0403101811"


def test_clean_cbe_padding():
    assert clean_cbe("403101811") == "0403101811"


def test_clean_cbe_already_clean():
    assert clean_cbe("0403101811") == "0403101811"


def test_clean_cbe_none():
    assert clean_cbe(None) == ""


def test_clean_cbe_empty():
    assert clean_cbe("") == ""


def test_clean_cbe_whitespace():
    assert clean_cbe("   ") == ""


def test_clean_cbe_int():
    assert clean_cbe(403101811) == "0403101811"


def test_clean_cbe_spaces():
    assert clean_cbe("  0403 101 811  ") == "0403101811"


def test_clean_cbe_garbage():
    assert clean_cbe("abc-403-101-811-xyz") == "0403101811"


def test_clean_cbe_letters_only():
    assert clean_cbe("abcdef") == ""


def test_is_valid_nace_ok():
    assert is_valid_nace("28")
    assert is_valid_nace("281")
    assert is_valid_nace("2811")
    assert is_valid_nace("28110")
    assert is_valid_nace("281101")


def test_is_valid_nace_bad():
    assert not is_valid_nace("")
    assert not is_valid_nace(None)
    assert not is_valid_nace("a28")
    assert not is_valid_nace("28a")
    assert not is_valid_nace("2812345")  # too long
    assert not is_valid_nace("2")        # too short
    assert not is_valid_nace("28.11")    # special char
    assert not is_valid_nace("28-11")    # special char


def test_parse_nace_list_basic():
    assert parse_nace_list("28,46,62") == ["28", "46", "62"]


def test_parse_nace_list_drops_invalid():
    assert parse_nace_list("28, abc, 62") == ["28", "62"]


def test_parse_nace_list_empty():
    assert parse_nace_list("") == []


def test_parse_nace_list_whitespace():
    assert parse_nace_list("   ") == []


def test_parse_nace_list_padding_in_entries():
    assert parse_nace_list(" 28 , 46 ") == ["28", "46"]


def test_parse_nace_list_none():
    assert parse_nace_list(None) == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"{name}: ok")
    print("All utils tests passed.")
