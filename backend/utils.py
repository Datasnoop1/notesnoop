"""Shared backend helpers — CBE normalization and input validation."""

import re

_CBE_NON_DIGIT = re.compile(r"\D+")
_NACE_PATTERN = re.compile(r"^\d{2,6}$")


def clean_cbe(value) -> str:
    """Normalize a Belgian enterprise number (CBE/KBO) to 10 digits, no separators.

    Accepts: "0403.101.811", "403101811", "  0403 101 811  ", 403101811
    Returns: "0403101811" (zero-padded to 10 digits)
    Returns "" for None or non-numeric input.
    """
    if value is None:
        return ""
    digits = _CBE_NON_DIGIT.sub("", str(value))
    if not digits:
        return ""
    return digits.zfill(10)


def is_valid_nace(code: str) -> bool:
    """A NACE code is 2-6 digits. Reject everything else."""
    if not code:
        return False
    return bool(_NACE_PATTERN.match(code.strip()))


def parse_nace_list(raw: str) -> list[str]:
    """Parse a comma-separated NACE input, returning only valid codes.

    Used by the screener to safely accept user-supplied NACE filters.
    """
    if not raw:
        return []
    out = []
    for c in raw.split(","):
        c = c.strip()
        if is_valid_nace(c):
            out.append(c)
    return out
