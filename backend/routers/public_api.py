"""Public API v1 — customer-facing financials endpoint.

Authentication: ``Authorization: Bearer <token>`` where ``<token>`` is a
key issued by ``scripts/issue_api_key.py`` and stored hashed in the
``api_keys`` table. Every call is recorded in ``api_call_log`` for
usage monitoring and the per-key daily cap.

Endpoint shape:
    GET /api/v1/company/{vat}/financials?years=2

Response: company + tabular financials (columns + data rows) + meta.
See ``docs/api.md`` for the full schema and a cURL example.

Design notes:
- The two existing API auth surfaces (Supabase JWTs, anonymous) are
  routed by middleware. This router is a third surface — API-key auth
  with no Supabase coupling — so the request must bypass the existing
  rate-limit / activity-log / bot-filter / staging-gate middlewares.
  See ``backend/main.py`` for the bypass entries.
- Ratios are computed server-side here, mirroring the formulas in
  ``frontend/src/app/company/[cbe]/_tabs/credit-tab.tsx`` so the API
  returns the same numbers the customer sees in the product. Keep the
  two in sync if either changes.
- Percentages (equityRatio, roe, ebitdaMargin) are returned in the
  ``51.5`` style (matches the credit tab), not ``0.515``. Units are
  declared in ``meta.units`` so the consumer doesn't have to guess.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import math
import os
import re
import time
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from db import execute, fetch_all, fetch_one
from rate_limit import limiter
from utils import clean_cbe

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["public-api"])


# ---------------------------------------------------------------------------
# Schema bootstrap (idempotent — runs once at first call)
# ---------------------------------------------------------------------------

_schema_ensured = False


def _ensure_schema() -> None:
    """Compatibility shim for public API tables moved to migrations.

    Idempotent and cheap to call on every request; guarded with a process flag.
    """
    global _schema_ensured
    if _schema_ensured:
        return
    _schema_ensured = True


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _log_call(
    api_key_id: int | None,
    vat: str | None,
    endpoint: str,
    status: int,
    latency_ms: int,
    cost: int = 1,
) -> None:
    """Best-effort write to api_call_log. Never raises.

    `cost` weights this call against the daily cap. Single-company lookups
    cost 1; the `/companies` listing endpoint costs `ceil(limit / 50)` so
    a max-size search consumes 5 units of the cap.
    """
    if api_key_id is None:
        # Anon failures (no/invalid token) — we have no FK target. Don't log.
        return
    try:
        execute(
            "INSERT INTO api_call_log "
            "(api_key_id, vat_queried, endpoint, status_code, latency_ms, cost) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (api_key_id, vat, endpoint, status, latency_ms, int(cost)),
        )
    except Exception:
        logger.exception("public_api: failed to write api_call_log")


def require_api_key(request: Request) -> dict:
    """FastAPI dependency: validate Bearer token + enforce per-min and daily caps.

    Returns the api_keys row dict on success. Raises HTTPException with a
    machine-readable ``detail`` on failure. Failures with a known key are
    logged to ``api_call_log``; anonymous failures are not (no FK target).
    """
    _ensure_schema()

    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail={"error": "missing_credentials",
                    "message": "Send 'Authorization: Bearer <token>' header"},
        )

    token = auth[7:].strip()
    if not token:
        raise HTTPException(
            status_code=401,
            detail={"error": "missing_credentials",
                    "message": "Empty Bearer token"},
        )

    key_row = fetch_one(
        "SELECT id, label, daily_cap, disabled_at, scopes "
        "FROM api_keys WHERE key_hash = %s",
        (_hash_token(token),),
    )
    if not key_row:
        # Unknown token — anon, no log entry (no FK target).
        raise HTTPException(
            status_code=401,
            detail={"error": "invalid_credentials",
                    "message": "Unknown API key"},
        )

    if key_row["disabled_at"] is not None:
        # Known but revoked — log so the operator sees attempts on disabled keys.
        _log_call(key_row["id"], None, request.url.path, 403, 0)
        raise HTTPException(
            status_code=403,
            detail={"error": "key_disabled",
                    "message": "This API key has been disabled"},
        )

    # Per-minute throttle — protects against burst abuse / runaway scripts
    # even before the daily cap kicks in. Keyed by api_key_id (NOT by IP),
    # so a customer can scale across IPs but not across the cap.
    try:
        limiter.check(f"apikey:{key_row['id']}", max_requests=60, window_seconds=60)
    except HTTPException as e:
        _log_call(key_row["id"], None, request.url.path, 429, 0)
        # Re-shape detail to match our API error envelope
        raise HTTPException(
            status_code=429,
            detail={"error": "rate_limited",
                    "message": "Too many requests — max 60/min per key"},
        ) from e

    # Daily cap (circuit breaker). Sums `cost` rather than COUNT(*) so
    # weighted-cost endpoints (e.g. /companies at limit=250 → cost=5)
    # consume more cap than single-company lookups.
    cap = int(key_row["daily_cap"] or 0)
    if cap > 0:
        used_row = fetch_one(
            "SELECT COALESCE(SUM(cost), 0) AS n FROM api_call_log "
            "WHERE api_key_id = %s AND created_at > NOW() - INTERVAL '1 day'",
            (key_row["id"],),
        )
        used = int(used_row["n"]) if used_row else 0
        if used >= cap:
            _log_call(key_row["id"], None, request.url.path, 429, 0)
            raise HTTPException(
                status_code=429,
                detail={"error": "daily_cap_exceeded",
                        "message": f"Daily cap of {cap} units reached",
                        "cap": cap, "used": used},
            )

    return key_row


# ---------------------------------------------------------------------------
# Scope gating
# ---------------------------------------------------------------------------

# Mirrored in the migration's CHECK (api_keys_scopes_known). Both must be
# updated together when introducing a new scope — the DB rejects writes
# of unknown scopes; the require_scope() module-load check catches typos
# in route definitions.
_VALID_SCOPES = frozenset({"lookup", "search"})


def require_scope(required: str):
    """FastAPI dependency factory: validate Bearer token + check scope.

    Wraps ``require_api_key`` and adds a per-route scope gate. Validated
    at module load time so a typo like ``require_scope("seach")`` blows
    up at import rather than silently 403-ing every call.
    """
    if required not in _VALID_SCOPES:
        raise RuntimeError(
            f"require_scope({required!r}): unknown scope. "
            f"Add it to _VALID_SCOPES + the api_keys_scopes_known CHECK."
        )

    def dep(request: Request, api_key: dict = Depends(require_api_key)) -> dict:
        scopes = api_key.get("scopes") or []
        if required not in scopes:
            _log_call(api_key["id"], None,
                      f"scope_check:{required}", 403, 0)
            raise HTTPException(
                status_code=403,
                detail={"error": "scope_denied",
                        "message": f"This key lacks the '{required}' scope"},
            )
        return api_key
    return dep


# ---------------------------------------------------------------------------
# VAT / CBE normalisation
# ---------------------------------------------------------------------------

_BE_PREFIX_RE = re.compile(r"^\s*BE\s*", re.IGNORECASE)
# After stripping the BE prefix, the remaining body may only contain digits
# and standard separators (dot, space, hyphen). Without this guard,
# `clean_cbe()` happily collapses any string with embedded digits — e.g.
# `"abc1234567890def"` would normalise to a valid-looking 10-digit CBE.
# We tighten that here so the documented `400 invalid_vat` actually fires.
_VAT_BODY_RE = re.compile(r"^[\d.\s\-]+$")


def _normalize_vat(raw: str) -> str:
    """Accepts 'BE0752984076', '0752984076', '0752.984.076', '0752 984 076', etc.

    Returns a 10-digit string. Raises HTTPException(400) if it can't be
    coerced into a plausible Belgian enterprise number.
    """
    if not raw:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_vat", "message": "Empty VAT"},
        )
    stripped = _BE_PREFIX_RE.sub("", str(raw)).strip()
    if not stripped or not _VAT_BODY_RE.match(stripped):
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_vat",
                    "message": "VAT must be a 10-digit Belgian enterprise number "
                               "(optionally prefixed with 'BE'); only digits and "
                               "the separators '.', ' ', '-' are allowed"},
        )
    cbe = clean_cbe(stripped)
    if len(cbe) != 10:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_vat",
                    "message": "VAT must be a 10-digit Belgian enterprise number "
                               "(optionally prefixed with 'BE')"},
        )
    return cbe


# ---------------------------------------------------------------------------
# Ratio helpers (mirror frontend/src/app/company/[cbe]/_tabs/credit-tab.tsx)
# ---------------------------------------------------------------------------


def _safe_div(numer: float | None, denom: float | None) -> float | None:
    """Return numer/denom, or None if either side is missing or denom is 0."""
    if numer is None or denom is None or denom == 0:
        return None
    try:
        return numer / denom
    except Exception:
        return None


def _round(value: float | None, ndigits: int = 4) -> float | None:
    """Round for response payload — keeps JSON small without losing precision."""
    if value is None:
        return None
    try:
        return round(float(value), ndigits)
    except Exception:
        return None


def _compute_year_row(row: dict) -> list:
    """Turn one financial_summary row into the list of column values.

    Order MUST match COLUMNS below. None where data is missing or a
    ratio is undefined (denominator 0/missing).
    """
    revenue = row.get("revenue")
    ebitda = row.get("ebitda")
    ebit = row.get("ebit")
    net_profit = row.get("net_profit")
    equity = row.get("equity")
    total_assets = row.get("total_assets")
    fin_charges = row.get("financial_charges")
    trade_rec = row.get("trade_receivables")
    trade_pay = row.get("trade_payables")

    # Keep originals for the response so unfiled fields stay null instead of
    # silently becoming 0.0 (the docs promise null = unfiled).
    cash_raw = row.get("cash")
    investments_raw = row.get("current_investments")
    lt_debt_raw = row.get("lt_financial_debt")
    st_debt_raw = row.get("st_financial_debt")

    # Math-only views: treat null as 0 for sums/derived figures, mirroring
    # the credit tab's `(row.x ?? 0)` coercions in credit-tab.tsx.
    cash = cash_raw or 0.0
    investments = investments_raw or 0.0
    lt_debt = lt_debt_raw or 0.0
    st_debt = st_debt_raw or 0.0

    gross_debt = lt_debt + st_debt
    net_debt = gross_debt - cash - investments

    # Match the credit tab formulas verbatim. Percentages × 100, days × 365.
    net_debt_ebitda = _safe_div(net_debt, ebitda)
    debt_equity = _safe_div(gross_debt, equity)
    equity_ratio = _safe_div((equity or 0.0) * 100.0, total_assets)
    # Mirror credit-tab.tsx:136 — when fin_charges is non-zero but EBIT is
    # null, the tab returns 0 (treats null EBIT as 0). Without the `or 0.0`
    # we'd return null where the product shows 0.0x.
    interest_coverage = _safe_div(ebit or 0.0, abs(fin_charges)) if fin_charges else None
    cash_st_debt = _safe_div(cash + investments, st_debt_raw)
    # DSCR: EBITDA / (|fin_charges| + ST fin debt). Need at least one of those
    # to be non-zero; EBITDA can be None → treat as 0 to mirror the tab.
    dscr_denom = abs(fin_charges or 0.0) + (st_debt_raw or 0.0)
    dscr = _safe_div(ebitda or 0.0, dscr_denom) if (fin_charges or st_debt_raw) else None
    roe = _safe_div((net_profit or 0.0) * 100.0, equity)
    ebitda_margin = _safe_div((ebitda or 0.0) * 100.0, revenue) if (revenue and revenue > 0) else None
    dso = _safe_div((trade_rec or 0.0) * 365.0, revenue) if (revenue and revenue > 0) else None
    dpo = _safe_div((trade_pay or 0.0) * 365.0, revenue) if (revenue and revenue > 0) else None
    cash_conversion = (dso - dpo) if (dso is not None and dpo is not None) else None

    return [
        int(row["fiscal_year"]) if row.get("fiscal_year") is not None else None,
        # Raw financials — return the unmodified values so unfiled = null.
        _round(revenue, 2),
        _round(ebitda, 2),
        _round(ebit, 2),
        _round(net_profit, 2),
        _round(equity, 2),
        _round(total_assets, 2),
        _round(cash_raw, 2),
        _round(investments_raw, 2),
        _round(lt_debt_raw, 2),
        _round(st_debt_raw, 2),
        _round(fin_charges, 2),
        _round(trade_rec, 2),
        _round(trade_pay, 2),
        # Derived absolutes (computed with null-as-0 coercion above).
        _round(gross_debt, 2),
        _round(net_debt, 2),
        # Ratios
        _round(net_debt_ebitda, 2),
        _round(debt_equity, 2),
        _round(equity_ratio, 2),
        _round(interest_coverage, 2),
        _round(cash_st_debt, 2),
        _round(dscr, 2),
        _round(roe, 2),
        _round(ebitda_margin, 2),
        _round(dso, 1),
        _round(dpo, 1),
        _round(cash_conversion, 1),
    ]


# Column ordering — kept in sync with _compute_year_row.
COLUMNS: list[str] = [
    "fiscalYear",
    "revenue", "ebitda", "ebit", "netProfit",
    "equity", "totalAssets", "cash", "currentInvestments",
    "ltFinancialDebt", "stFinancialDebt", "financialCharges",
    "tradeReceivables", "tradePayables",
    "grossDebt", "netDebt",
    "netDebtEbitda", "debtEquity", "equityRatio",
    "interestCoverage", "cashStDebt", "dscr",
    "roe", "ebitdaMargin", "dso", "dpo", "cashConversion",
]

# Per-column units for the `meta.units` declaration. Anything not listed is
# raw EUR. Customers should treat percent-tagged fields as already-multiplied
# (51.5 means 51.5 %, not 0.515).
UNITS: dict[str, str] = {
    "equityRatio": "percent",
    "roe": "percent",
    "ebitdaMargin": "percent",
    "dso": "days",
    "dpo": "days",
    "cashConversion": "days",
    "netDebtEbitda": "ratio",
    "debtEquity": "ratio",
    "interestCoverage": "ratio",
    "cashStDebt": "ratio",
    "dscr": "ratio",
    "fiscalYear": "year",
}

# Friendly labels for the NBB filing models.
_FILING_MODEL_LABELS: dict[str, str] = {
    "VOL": "full",          # Volledig schema
    "VKT": "abbreviated",   # Verkort schema
    "MIC": "micro",
}


# ---------------------------------------------------------------------------
# GET /api/v1/company/{vat}/financials
# ---------------------------------------------------------------------------


_FINANCIAL_SUMMARY_SQL = """
    SELECT DISTINCT ON (fiscal_year)
           fiscal_year, deposit_key, deposit_date, filing_model,
           revenue, gross_margin, ebit, da, ebitda, net_profit,
           equity, lt_debt, lt_financial_debt, st_financial_debt,
           cash, current_investments, total_assets,
           trade_receivables, trade_payables,
           financial_charges
    FROM financial_summary
    WHERE enterprise_number = %s
      AND fiscal_year IS NOT NULL
    ORDER BY fiscal_year DESC, deposit_date DESC NULLS LAST
    LIMIT %s
"""


async def _attempt_cold_load(
    cbe: str,
    years: int,
    background_tasks: BackgroundTasks,
) -> list:
    """Trigger an on-demand NBB load and return the re-queried summary rows.

    Imports ``_do_load`` lazily to avoid an import cycle at module load
    time (companies/financials.py imports util modules that ultimately
    import from main.py during the FastAPI app build).

    Failures are logged but not raised: an NBB upstream blip shouldn't
    turn a customer's lookup into a 500 — they get an empty response
    just like a customer whose VAT genuinely has no NBB filings would.
    """
    nbb_key = os.getenv("NBB_AUTHENTIC_KEY", "")
    nbb_base = os.getenv("NBB_BASE_URL", "https://ws.cbso.nbb.be")
    if not nbb_key:
        logger.warning("public_api: cold load for %s skipped — NBB_AUTHENTIC_KEY unset", cbe)
        return []

    try:
        # Lazy import — see docstring.
        from routers.companies.financials import _do_load, _LOAD_SEMAPHORE
    except ImportError:
        logger.exception("public_api: cold load for %s failed — _do_load import error", cbe)
        return []

    try:
        async with _LOAD_SEMAPHORE:
            await _do_load(cbe, None, nbb_key, nbb_base, background_tasks)
    except HTTPException as e:
        logger.warning("public_api: cold load NBB error for %s: %s", cbe, e.detail)
        return []
    except Exception:
        logger.exception("public_api: unexpected cold load error for %s", cbe)
        return []

    return fetch_all(_FINANCIAL_SUMMARY_SQL, (cbe, years))


@router.get("/company/{vat}/financials")
async def get_company_financials(
    request: Request,
    background_tasks: BackgroundTasks,
    vat: str,
    years: int = Query(2, ge=1, le=20, description="Number of fiscal years to return (default 2, max 20)"),
    api_key: dict = Depends(require_scope("lookup")),
):
    """Return the last N years of financial data for one company.

    Auth: Bearer token (see ``scripts/issue_api_key.py``).
    Path: VAT/CBE — accepts ``BE0752984076``, ``0752984076``, ``0752.984.076``.

    Cold-lookup behavior: if the company exists in KBO but has no rows in
    ``financial_summary``, we trigger an on-demand NBB load (mirroring the
    platform's auto-load on the company profile) and re-query before
    responding. This adds ~5–10s of latency on the first lookup; subsequent
    lookups hit warm data.
    """
    started = time.monotonic()
    status_code = 200
    cbe: str | None = None
    cold_load_attempted = False
    try:
        cbe = _normalize_vat(vat)

        # Company name + legal form. company_master has one row per
        # (enterprise, language) — pick any one (DISTINCT on enterprise_number).
        company = fetch_one(
            """
            SELECT enterprise_number, name, juridical_form
            FROM company_master
            WHERE enterprise_number = %s
            LIMIT 1
            """,
            (cbe,),
        )
        if not company:
            status_code = 404
            raise HTTPException(
                status_code=404,
                detail={"error": "company_not_found",
                        "message": f"No company in KBO with VAT {cbe}"},
            )

        # Latest deposit per fiscal_year, last N years. DISTINCT ON guarantees
        # we collapse amendments down to the freshest filing per year.
        rows = fetch_all(_FINANCIAL_SUMMARY_SQL, (cbe, int(years)))

        # Cold lookup → mirror the platform's auto-load. Skip if we've
        # already stamped the PDF_ONLY sentinel (every recent NBB filing
        # was 404'd with "no published json xbrl") — those companies
        # genuinely have no structured data and re-fetching wastes the
        # NBB key budget.
        if not rows:
            pdf_only_row = fetch_one(
                "SELECT 1 FROM nbb_load_log "
                "WHERE enterprise_number = %s AND deposit_key = 'PDF_ONLY' LIMIT 1",
                (cbe,),
            )
            if not pdf_only_row:
                rows = await _attempt_cold_load(cbe, int(years), background_tasks)
                cold_load_attempted = True

        data = [_compute_year_row(r) for r in rows]

        latest_deposit_date: str | None = None
        latest_filing_model: str | None = None
        if rows:
            latest_deposit_date = (
                str(rows[0]["deposit_date"]) if rows[0].get("deposit_date") else None
            )
            latest_filing_model = rows[0].get("filing_model")

        return {
            "company": {
                "vat": cbe,
                "name": company.get("name"),
                "legalForm": company.get("juridical_form"),
            },
            "financials": {
                "columns": COLUMNS,
                "data": data,
            },
            "meta": {
                "currency": "EUR",
                "source": "NBB",
                "lastUpdated": latest_deposit_date,
                "schemaVersion": "1.0",
                "yearsReturned": len(data),
                "yearsRequested": int(years),
                "filingModel": latest_filing_model,
                "filingModelLabel": _FILING_MODEL_LABELS.get(latest_filing_model or "", None),
                "coldLoad": cold_load_attempted,
                "units": UNITS,
            },
        }
    except HTTPException as e:
        status_code = int(e.status_code)
        raise
    except Exception:
        status_code = 500
        logger.exception("public_api: unhandled error for vat=%s", vat)
        raise HTTPException(
            status_code=500,
            detail={"error": "server_error", "message": "Internal error"},
        )
    finally:
        latency_ms = int((time.monotonic() - started) * 1000)
        _log_call(api_key["id"], cbe, request.url.path, status_code, latency_ms)


# ---------------------------------------------------------------------------
# GET /api/v1/companies — ranked / filtered company list (scope: search)
# ---------------------------------------------------------------------------

# (sort_metric_col, ORDER BY clause). Both come from the same dict so a
# refactor can never split them. Keys are the public `sort` values.
# Adding a new entry requires a matching composite index in
# migrations/2026-05-07_public_api_search_indexes.sql.
_SORT_TABLE: dict[str, tuple[str, str]] = {
    "total_assets:desc": (
        "fl.total_assets",
        "fl.total_assets DESC NULLS LAST, fl.enterprise_number ASC",
    ),
    "total_assets:asc": (
        "fl.total_assets",
        "fl.total_assets ASC NULLS LAST, fl.enterprise_number ASC",
    ),
    "revenue:desc": (
        "fl.revenue",
        "fl.revenue DESC NULLS LAST, fl.enterprise_number ASC",
    ),
    "revenue:asc": (
        "fl.revenue",
        "fl.revenue ASC NULLS LAST, fl.enterprise_number ASC",
    ),
    "ebitda:desc": (
        "fl.ebitda",
        "fl.ebitda DESC NULLS LAST, fl.enterprise_number ASC",
    ),
    "ebitda:asc": (
        "fl.ebitda",
        "fl.ebitda ASC NULLS LAST, fl.enterprise_number ASC",
    ),
}

# Source table from a server-side dict — never an inline ternary on user-
# derived state, even though both options are server-controlled today.
_SOURCE_TABLES: dict[bool, str] = {
    True:  "financial_by_year",   # used when ?year=N is passed
    False: "financial_latest",    # default: latest filing per company
}

# `juridical_form` filter: alphabetic only, 1-8 chars. Belgian forms
# (BV, NV, CV, CVBA, VOF, MAATSCHAP, etc.) all fit.
# `\Z` instead of `$` because `$` accepts a trailing `\n` (Python regex
# default), which would let `BV\n` slip through validation.
_JURIDICAL_FORM_RE = re.compile(r"^[A-Za-z]{1,8}\Z")

# `nace_prefix` filter: NACE Rev. 2 — 2-5 digits, optional dot, optional
# trailing letter (e.g. `46`, `46.7`, `46.731`, `62.02A`). The regex
# rejects `%` / `_` / arbitrary chars before the value reaches LIKE.
_NACE_PREFIX_RE = re.compile(r"^\d{2,5}(\.\d{1,3})?[A-Za-z]?\Z")


def _encode_cursor(sort: str, metric_val: float, en: str) -> str:
    """Encode (sort, last_metric, last_enterprise_number) into a base64 token.

    Cursors are unsigned — clients can decode them. The exposed surface
    is "skip to row N" on a public ranking, no different from passing
    your own filters. We don't add HMAC for v1; if abuse appears we'll
    revisit.
    """
    raw = json.dumps(
        {"s": sort, "m": metric_val, "e": en},
        separators=(",", ":"),
        sort_keys=True,
    )
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str, expected_sort: str) -> tuple[float, str]:
    """Validate + decode a cursor minted by ``_encode_cursor``.

    Raises ``HTTPException(400, invalid_cursor)`` on any malformed,
    tampered, or sort-mismatched payload.
    """
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        obj = json.loads(raw)
    except (ValueError, json.JSONDecodeError, binascii.Error, UnicodeDecodeError):
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_cursor", "message": "Cursor is malformed"},
        )

    if not isinstance(obj, dict):
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_cursor",
                    "message": "Cursor payload not an object"},
        )

    sort = obj.get("s")
    metric = obj.get("m")
    en = obj.get("e")

    if sort != expected_sort:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_cursor",
                    "message": "Cursor was issued for a different sort; restart pagination"},
        )
    # bool is a subclass of int in Python, so isinstance(True, (int, float))
    # is True. Filter explicitly so a tampered cursor with `"m": true`
    # doesn't slip through. Also reject Infinity / NaN — Python's stdlib
    # json.loads accepts those by default; if they reach the SQL layer
    # they'd raise psycopg2.DataError and the customer would see a 500
    # rather than the documented 400.
    if (
        isinstance(metric, bool)
        or not isinstance(metric, (int, float))
        or not math.isfinite(metric)
    ):
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_cursor",
                    "message": "Cursor metric value missing or non-numeric"},
        )
    if not isinstance(en, str) or len(en) != 10 or not en.isdigit():
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_cursor",
                    "message": "Cursor enterprise number malformed"},
        )

    return float(metric), en


def _bad_filter(field: str, message: str) -> HTTPException:
    """Build a 400 invalid_filter HTTPException identifying the bad parameter."""
    return HTTPException(
        status_code=400,
        detail={"error": "invalid_filter", "field": field, "message": message},
    )


def _validate_min(field: str, value: int | None, min_allowed: int) -> int | None:
    """Range-check a `min_*` filter; return None when unset.

    `min_allowed` is the lowest semantically valid value for THIS column —
    revenue/total_assets are 1 (zero would be a no-op filter that confuses
    the planner; customer should omit the param instead). EBITDA / equity /
    net_profit allow large negatives because losses and insolvency are
    legitimate filter targets.
    """
    if value is None:
        return None
    if value < min_allowed or value > 10**15:
        raise _bad_filter(
            field,
            f"{field} must satisfy {min_allowed} ≤ N ≤ 1e15. "
            f"Omit the parameter instead of passing 0 / out-of-range.",
        )
    return int(value)


@router.get("/companies")
async def list_companies(
    request: Request,
    sort: str = Query("total_assets:desc",
                      description="<metric>:<asc|desc>. See API docs for allowlist."),
    limit: int = Query(50, ge=1, le=250,
                       description="Rows per page, 1..250."),
    cursor: str | None = Query(None,
                               description="Opaque pagination token from the previous response."),
    year: int | None = Query(None, ge=2000, le=2100,
                             description="Filter to a specific fiscal year."),
    min_revenue: int | None = Query(None),
    min_total_assets: int | None = Query(None),
    min_ebitda: int | None = Query(None),
    min_equity: int | None = Query(None),
    min_net_profit: int | None = Query(None),
    juridical_form: str | None = Query(None,
                                       description="Exact match, case-insensitive."),
    nace_prefix: str | None = Query(None,
                                    description="NACE prefix; e.g. '46' or '46.7' or '62.02A'."),
    api_key: dict = Depends(require_scope("search")),
):
    """List companies ranked by a financial metric, with optional filters.

    Returns up to ``limit`` rows + an opaque ``nextCursor`` for pagination.
    Costs ceil(limit/50) units against the daily cap (1 unit = same cost
    as a /financials lookup), so a max-size search consumes 5 units.
    """
    started = time.monotonic()
    status_code = 200
    cost = max(1, math.ceil(int(limit) / 50))
    try:
        # Per-endpoint per-minute throttle — narrower than the 60/min
        # in require_api_key so a customer hammering /companies can't
        # starve their own /financials calls. 30/min on a max-cost
        # search (5 units each) ≈ 150 units/min ceiling, well under
        # the 25 000-unit Ascot daily cap.
        try:
            limiter.check(
                f"apikey:{api_key['id']}:companies",
                max_requests=30,
                window_seconds=60,
            )
        except HTTPException as e:
            status_code = 429
            raise HTTPException(
                status_code=429,
                detail={"error": "rate_limited",
                        "message": "Too many /companies requests — max 30/min per key"},
            ) from e

        # --- Validate inputs (server-side; everything user-derived is
        # bound as a parameter or rejected before reaching SQL) ---
        if sort not in _SORT_TABLE:
            raise HTTPException(
                status_code=400,
                detail={"error": "invalid_sort",
                        "message": f"Unknown sort '{sort}'. Allowed: "
                                   + ", ".join(sorted(_SORT_TABLE.keys()))},
            )

        # Per-metric `min_*` validation. Non-negative-only metrics
        # reject 0 and below; signed metrics allow negatives.
        v_min_revenue       = _validate_min("min_revenue",       min_revenue,       1)
        v_min_total_assets  = _validate_min("min_total_assets",  min_total_assets,  1)
        v_min_ebitda        = _validate_min("min_ebitda",        min_ebitda,       -10**15)
        v_min_equity        = _validate_min("min_equity",        min_equity,       -10**15)
        v_min_net_profit    = _validate_min("min_net_profit",    min_net_profit,   -10**15)

        if juridical_form is not None and not _JURIDICAL_FORM_RE.match(juridical_form):
            raise _bad_filter(
                "juridical_form",
                "Must be 1-8 alphabetic characters (e.g. 'BV', 'NV', 'CVBA').",
            )
        if nace_prefix is not None and not _NACE_PREFIX_RE.match(nace_prefix):
            raise _bad_filter(
                "nace_prefix",
                "Must be 2-5 digits with optional dot and optional trailing letter "
                "(e.g. '46', '46.7', '62.02A').",
            )

        # --- Build the query ---
        sort_metric_col, sort_order_by = _SORT_TABLE[sort]
        sort_dir = "DESC" if sort.endswith(":desc") else "ASC"
        source_table = _SOURCE_TABLES[year is not None]

        # NULL exclusion is unconditional: a NULL sort metric has no
        # defensible position in a ranking, and its absence here makes
        # the cursor seek tuple comparison well-defined for every page.
        where_parts: list[str] = [f"{sort_metric_col} IS NOT NULL"]
        params: list[Any] = []

        for col, val in [
            ("fl.total_assets", v_min_total_assets),
            ("fl.revenue",      v_min_revenue),
            ("fl.ebitda",       v_min_ebitda),
            ("fl.equity",       v_min_equity),
            ("fl.net_profit",   v_min_net_profit),
        ]:
            if val is not None:
                where_parts.append(f"{col} >= %s")
                params.append(val)

        if year is not None:
            where_parts.append("fl.fiscal_year = %s")
            params.append(int(year))

        if juridical_form is not None:
            where_parts.append("LOWER(cm.juridical_form) = LOWER(%s)")
            params.append(juridical_form)

        if nace_prefix is not None:
            where_parts.append("ci.nace_code LIKE %s")
            # Append the LIKE wildcard in Python; never via SQL ||.
            params.append(nace_prefix + "%")

        applied_filters: dict[str, Any] = {}
        if year is not None:
            applied_filters["year"] = int(year)
        if v_min_revenue is not None:
            applied_filters["minRevenue"] = v_min_revenue
        if v_min_total_assets is not None:
            applied_filters["minTotalAssets"] = v_min_total_assets
        if v_min_ebitda is not None:
            applied_filters["minEbitda"] = v_min_ebitda
        if v_min_equity is not None:
            applied_filters["minEquity"] = v_min_equity
        if v_min_net_profit is not None:
            applied_filters["minNetProfit"] = v_min_net_profit
        if juridical_form is not None:
            applied_filters["juridicalForm"] = juridical_form
        if nace_prefix is not None:
            applied_filters["nacePrefix"] = nace_prefix

        if cursor is not None:
            last_v, last_en = _decode_cursor(cursor, expected_sort=sort)
            if sort_dir == "DESC":
                where_parts.append(
                    f"({sort_metric_col}, fl.enterprise_number) < (%s, %s)"
                )
            else:
                where_parts.append(
                    f"({sort_metric_col}, fl.enterprise_number) > (%s, %s)"
                )
            params.extend([last_v, last_en])

        where_clause = " AND ".join(where_parts)
        sql = f"""
            SELECT
                fl.enterprise_number, fl.fiscal_year, fl.filing_model,
                fl.total_assets, fl.revenue, fl.ebitda, fl.equity,
                fl.net_profit, fl.fte_total,
                cm.name, cm.juridical_form,
                ci.city, ci.nace_code
            FROM {source_table} fl
            JOIN company_master cm USING (enterprise_number)
            LEFT JOIN company_info ci USING (enterprise_number)
            WHERE {where_clause}
            ORDER BY {sort_order_by}
            LIMIT %s
        """
        params.append(int(limit) + 1)

        rows = fetch_all(sql, params)

        has_more = len(rows) > int(limit)
        page_rows = rows[: int(limit)]

        data: list[dict[str, Any]] = []
        for r in page_rows:
            data.append({
                "vat": r.get("enterprise_number"),
                "name": r.get("name"),
                "legalForm": r.get("juridical_form"),
                "fiscalYear": int(r["fiscal_year"]) if r.get("fiscal_year") is not None else None,
                "totalAssets": _round(r.get("total_assets"), 2),
                "revenue":     _round(r.get("revenue"), 2),
                "ebitda":      _round(r.get("ebitda"), 2),
                "equity":      _round(r.get("equity"), 2),
                "netProfit":   _round(r.get("net_profit"), 2),
                "fteTotal":    _round(r.get("fte_total"), 1),
                "naceCode":    r.get("nace_code"),
                "city":        r.get("city"),
            })

        next_cursor: str | None = None
        if has_more and page_rows:
            last = page_rows[-1]
            # Cursor is minted from the LAST row of `data` (not the dropped
            # limit+1-th) so the next page's seek goes past the boundary
            # cleanly even when the metric value ties with neighbours.
            metric_raw = last.get(_metric_col_to_row_key(sort_metric_col))
            if metric_raw is not None:
                next_cursor = _encode_cursor(
                    sort=sort,
                    metric_val=float(metric_raw),
                    en=last["enterprise_number"],
                )

        return {
            "data": data,
            "meta": {
                "limit": int(limit),
                "sort": sort,
                "nextCursor": next_cursor,
                "hasMore": has_more,
                "appliedFilters": applied_filters,
                "schemaVersion": "1.0",
                "currency": "EUR",
            },
        }
    except HTTPException as e:
        status_code = int(e.status_code)
        raise
    except Exception:
        status_code = 500
        logger.exception("public_api: /companies unhandled error")
        raise HTTPException(
            status_code=500,
            detail={"error": "server_error", "message": "Internal error"},
        )
    finally:
        latency_ms = int((time.monotonic() - started) * 1000)
        _log_call(api_key["id"], None, request.url.path,
                  status_code, latency_ms, cost=cost)


def _metric_col_to_row_key(sort_metric_col: str) -> str:
    """Map ``fl.total_assets`` → ``total_assets`` (the row dict key).

    Tiny helper kept private — `fl.` is the alias used in the SELECT.
    """
    return sort_metric_col.split(".", 1)[1]


# ---------------------------------------------------------------------------
# GET /api/v1/health — auth-free liveness probe for customers
# ---------------------------------------------------------------------------


@router.get("/health")
async def public_api_health():
    """Unauthenticated: lets customers verify the API is reachable.

    Intentionally returns no data beyond a status string — useful for
    uptime monitors without exposing anything sensitive or rate-limited.
    """
    return {"status": "ok", "service": "datasnoop-public-api", "version": "v1"}
