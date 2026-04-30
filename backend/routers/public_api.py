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

import hashlib
import logging
import re
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
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
) -> None:
    """Best-effort write to api_call_log. Never raises."""
    if api_key_id is None:
        # Anon failures (no/invalid token) — we have no FK target. Don't log.
        return
    try:
        execute(
            "INSERT INTO api_call_log "
            "(api_key_id, vat_queried, endpoint, status_code, latency_ms) "
            "VALUES (%s, %s, %s, %s, %s)",
            (api_key_id, vat, endpoint, status, latency_ms),
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
        "SELECT id, label, daily_cap, disabled_at "
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

    # Daily cap (circuit breaker — not a paid quota for the v1 test).
    cap = int(key_row["daily_cap"] or 0)
    if cap > 0:
        used_row = fetch_one(
            "SELECT COUNT(*) AS n FROM api_call_log "
            "WHERE api_key_id = %s AND created_at > NOW() - INTERVAL '1 day'",
            (key_row["id"],),
        )
        used = int(used_row["n"]) if used_row else 0
        if used >= cap:
            _log_call(key_row["id"], None, request.url.path, 429, 0)
            raise HTTPException(
                status_code=429,
                detail={"error": "daily_cap_exceeded",
                        "message": f"Daily cap of {cap} calls reached",
                        "cap": cap, "used": used},
            )

    return key_row


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


@router.get("/company/{vat}/financials")
async def get_company_financials(
    request: Request,
    vat: str,
    years: int = Query(2, ge=1, le=20, description="Number of fiscal years to return (default 2, max 20)"),
    api_key: dict = Depends(require_api_key),
):
    """Return the last N years of financial data for one company.

    Auth: Bearer token (see ``scripts/issue_api_key.py``).
    Path: VAT/CBE — accepts ``BE0752984076``, ``0752984076``, ``0752.984.076``.
    """
    started = time.monotonic()
    status_code = 200
    cbe: str | None = None
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
        rows = fetch_all(
            """
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
            """,
            (cbe, int(years)),
        )

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
# GET /api/v1/health — auth-free liveness probe for customers
# ---------------------------------------------------------------------------


@router.get("/health")
async def public_api_health():
    """Unauthenticated: lets customers verify the API is reachable.

    Intentionally returns no data beyond a status string — useful for
    uptime monitors without exposing anything sensitive or rate-limited.
    """
    return {"status": "ok", "service": "datasnoop-public-api", "version": "v1"}
