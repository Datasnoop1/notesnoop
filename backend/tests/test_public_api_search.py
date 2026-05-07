"""Unit tests for the /api/v1/companies search endpoint helpers.

Pure-function coverage for cursor encode/decode, parameter validation
regexes, and the require_scope dependency factory. The integration
behaviour (real Postgres queries, CHECK constraint enforcement, EXPLAIN
verifying composite indexes) is verified manually on staging — see
docs/public-api-search-plan.md §10.

Run with: pytest backend/tests/test_public_api_search.py -v
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest

# Make `backend` importable without installing as a package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException

from routers.public_api import (  # noqa: E402
    _JURIDICAL_FORM_RE,
    _NACE_PREFIX_RE,
    _SORT_TABLE,
    _SOURCE_TABLES,
    _VALID_SCOPES,
    _decode_cursor,
    _encode_cursor,
    _validate_min,
    require_scope,
)


# ---------------------------------------------------------------------------
# Cursor encoding / decoding
# ---------------------------------------------------------------------------


class TestCursorRoundTrip:
    """Encoding then decoding must yield the original tuple for any
    valid metric/enterprise pair."""

    def test_round_trip_positive_metric(self):
        token = _encode_cursor("total_assets:desc", 800000.0, "0752984076")
        v, en = _decode_cursor(token, expected_sort="total_assets:desc")
        assert v == 800000.0
        assert en == "0752984076"

    def test_round_trip_negative_metric(self):
        # EBITDA can be negative for loss-making companies.
        token = _encode_cursor("ebitda:asc", -1234.5, "0123456789")
        v, en = _decode_cursor(token, expected_sort="ebitda:asc")
        assert v == -1234.5
        assert en == "0123456789"

    def test_round_trip_integer_metric(self):
        # JSON serialisation may render `100` as `100`, decode as int.
        # The codec returns float regardless.
        token = _encode_cursor("revenue:desc", 100, "0000000001")
        v, en = _decode_cursor(token, expected_sort="revenue:desc")
        assert isinstance(v, float)
        assert v == 100.0


class TestCursorRejection:
    """Every malformed / tampered cursor variant must raise 400 invalid_cursor."""

    def test_invalid_base64(self):
        with pytest.raises(HTTPException) as exc:
            _decode_cursor("!!!not-base64!!!", expected_sort="total_assets:desc")
        assert exc.value.status_code == 400
        assert exc.value.detail["error"] == "invalid_cursor"

    def test_invalid_json(self):
        token = base64.urlsafe_b64encode(b"{not json").decode("ascii").rstrip("=")
        with pytest.raises(HTTPException) as exc:
            _decode_cursor(token, expected_sort="total_assets:desc")
        assert exc.value.status_code == 400
        assert exc.value.detail["error"] == "invalid_cursor"

    def test_payload_not_dict(self):
        token = base64.urlsafe_b64encode(b'["a","b","c"]').decode("ascii").rstrip("=")
        with pytest.raises(HTTPException) as exc:
            _decode_cursor(token, expected_sort="total_assets:desc")
        assert exc.value.detail["error"] == "invalid_cursor"

    def test_missing_sort_field(self):
        raw = json.dumps({"m": 100.0, "e": "0123456789"})
        token = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")
        with pytest.raises(HTTPException) as exc:
            _decode_cursor(token, expected_sort="total_assets:desc")
        assert exc.value.detail["error"] == "invalid_cursor"

    def test_sort_mismatch(self):
        # Encode for total_assets:desc, decode as if for revenue:desc.
        token = _encode_cursor("total_assets:desc", 100.0, "0123456789")
        with pytest.raises(HTTPException) as exc:
            _decode_cursor(token, expected_sort="revenue:desc")
        assert exc.value.detail["error"] == "invalid_cursor"
        assert "different sort" in exc.value.detail["message"]

    def test_metric_value_missing(self):
        raw = json.dumps({"s": "total_assets:desc", "e": "0123456789"})
        token = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")
        with pytest.raises(HTTPException):
            _decode_cursor(token, expected_sort="total_assets:desc")

    def test_metric_value_string(self):
        raw = json.dumps({"s": "total_assets:desc", "m": "not-a-number", "e": "0123456789"})
        token = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")
        with pytest.raises(HTTPException):
            _decode_cursor(token, expected_sort="total_assets:desc")

    def test_metric_value_bool_rejected(self):
        # Python bool is an int subclass; isinstance(True, int) is True.
        # The decoder must explicitly filter bools or a tampered cursor
        # with `"m": true` would slip through.
        raw = json.dumps({"s": "total_assets:desc", "m": True, "e": "0123456789"})
        token = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")
        with pytest.raises(HTTPException):
            _decode_cursor(token, expected_sort="total_assets:desc")

    def test_metric_value_infinity_rejected(self):
        # Python's stdlib json.loads accepts `Infinity` / `-Infinity`
        # / `NaN` as floats. They'd reach psycopg2 as numeric params
        # and raise DataError → 500. The decoder must reject them
        # so a tampered cursor returns 400 (the documented error)
        # rather than crashing the endpoint.
        for tampered_metric in ("Infinity", "-Infinity", "NaN"):
            raw = (
                '{"s":"total_assets:desc","m":' + tampered_metric
                + ',"e":"0123456789"}'
            )
            token = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")
            with pytest.raises(HTTPException) as exc:
                _decode_cursor(token, expected_sort="total_assets:desc")
            assert exc.value.detail["error"] == "invalid_cursor"

    def test_enterprise_number_wrong_length(self):
        raw = json.dumps({"s": "total_assets:desc", "m": 100.0, "e": "123"})
        token = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")
        with pytest.raises(HTTPException):
            _decode_cursor(token, expected_sort="total_assets:desc")

    def test_enterprise_number_non_digit(self):
        raw = json.dumps({"s": "total_assets:desc", "m": 100.0, "e": "ABCDEFGHIJ"})
        token = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")
        with pytest.raises(HTTPException):
            _decode_cursor(token, expected_sort="total_assets:desc")


# ---------------------------------------------------------------------------
# Filter validation regexes
# ---------------------------------------------------------------------------


class TestJuridicalFormRegex:

    @pytest.mark.parametrize("value", ["BV", "NV", "CV", "CVBA", "VOF", "bv", "Bv"])
    def test_valid(self, value):
        assert _JURIDICAL_FORM_RE.match(value)

    @pytest.mark.parametrize("value", [
        "",                # empty
        "ABCDEFGHI",       # 9 chars, over limit
        "BV1",             # contains digit
        "BV%",             # LIKE wildcard — must be rejected before binding
        "BV ",             # trailing space
        "B-V",             # hyphen
        "BV\n",            # trailing newline — `$` would accept but `\Z` doesn't
    ])
    def test_invalid(self, value):
        assert not _JURIDICAL_FORM_RE.match(value)


class TestNacePrefixRegex:

    @pytest.mark.parametrize("value", [
        "46",          # 2-digit class
        "46.7",        # 3-digit subclass with dot
        "46.731",      # 5-digit detail
        "62.02A",      # NACE Rev. 2 letter suffix
        "01",          # boundary low
        "99999",       # boundary high (5-digit)
    ])
    def test_valid(self, value):
        assert _NACE_PREFIX_RE.match(value)

    @pytest.mark.parametrize("value", [
        "",            # empty
        "4",           # 1-digit (too short)
        "ABC",         # letters only
        "46%",         # LIKE wildcard — regex must reject before binding
        "46_",         # LIKE wildcard
        "46.731.0",    # too many dot groups
        "46.7AB",      # multi-letter suffix
        " 46",         # leading space
    ])
    def test_invalid(self, value):
        assert not _NACE_PREFIX_RE.match(value)


# ---------------------------------------------------------------------------
# `min_*` clamping
# ---------------------------------------------------------------------------


class TestValidateMin:

    def test_unset_returns_none(self):
        assert _validate_min("min_revenue", None, 1) is None

    def test_revenue_zero_rejected(self):
        # Revenue can't be sensibly negative for a "≥" filter, and 0 is a
        # no-op that confuses the planner. Customer should omit instead.
        with pytest.raises(HTTPException) as exc:
            _validate_min("min_revenue", 0, 1)
        assert exc.value.status_code == 400
        assert exc.value.detail["error"] == "invalid_filter"
        assert exc.value.detail["field"] == "min_revenue"

    def test_revenue_one_accepted(self):
        assert _validate_min("min_revenue", 1, 1) == 1

    def test_revenue_huge_accepted(self):
        assert _validate_min("min_revenue", 10**14, 1) == 10**14

    def test_revenue_above_ceiling_rejected(self):
        with pytest.raises(HTTPException):
            _validate_min("min_revenue", 10**16, 1)

    def test_ebitda_negative_accepted(self):
        # EBITDA can legitimately be negative — loss-making companies.
        assert _validate_min("min_ebitda", -1_000_000, -10**15) == -1_000_000

    def test_ebitda_below_floor_rejected(self):
        with pytest.raises(HTTPException):
            _validate_min("min_ebitda", -(10**16), -10**15)


# ---------------------------------------------------------------------------
# require_scope() factory
# ---------------------------------------------------------------------------


class TestRequireScope:

    def test_valid_scope_returns_callable(self):
        # Module-load-time validation: known scope works.
        dep = require_scope("lookup")
        assert callable(dep)

    def test_unknown_scope_raises_runtime_error(self):
        # Catches typos at import time rather than silently 403-ing
        # every call.
        with pytest.raises(RuntimeError) as exc:
            require_scope("seach")
        assert "unknown scope" in str(exc.value)

    def test_search_scope_known(self):
        # Sanity: the scope we're about to ship works.
        assert "search" in _VALID_SCOPES
        require_scope("search")  # does not raise


# ---------------------------------------------------------------------------
# Sort + source-table tables
# ---------------------------------------------------------------------------


class TestSortTable:

    def test_every_entry_has_three_fields(self):
        for key, value in _SORT_TABLE.items():
            assert len(value) == 2, f"{key} should map to (column, order_by)"
            col, order_by = value
            assert col.startswith("fl."), f"{key}: column should be aliased as fl.*"
            assert "ORDER" not in order_by.upper().split()[0], \
                f"{key}: order_by string should not include the keyword ORDER BY"

    def test_metric_column_appears_in_order_by(self):
        # Tiebreak on enterprise_number is the cursor's anchor; if a
        # _SORT_TABLE entry omits it the cursor would be unstable.
        for key, (col, order_by) in _SORT_TABLE.items():
            assert col in order_by, f"{key}: metric column missing from ORDER BY"
            assert "fl.enterprise_number" in order_by, \
                f"{key}: ORDER BY missing enterprise_number tiebreak"

    def test_only_known_directions(self):
        for key in _SORT_TABLE:
            assert key.endswith(":asc") or key.endswith(":desc"), \
                f"{key}: invalid direction suffix"


class TestSourceTables:

    def test_year_present_uses_by_year_table(self):
        assert _SOURCE_TABLES[True] == "financial_by_year"

    def test_year_absent_uses_latest_table(self):
        assert _SOURCE_TABLES[False] == "financial_latest"
