"""Companies financials router — load financial data from NBB and read history."""

import asyncio
import logging
import os
import time
from typing import Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response

from db import fetch_all, fetch_one, get_connection, put_connection
from auth import optional_user
from nbb_governance import store_governance_snapshot
from utils import clean_cbe
from ._helpers import _serialize_row

logger = logging.getLogger(__name__)
router = APIRouter()

_NBB_AUTH_FAILURE_STATUSES = {401, 403}
_NBB_RETRYABLE_STATUSES = {408, 409, 425, 429, 500, 502, 503, 504}

# Cap concurrent NBB loads at 3. NBB doesn't publish rate limits but
# advises 1-2s between calls; parallel /load calls from different IPs
# would multiply NBB traffic and risk key revocation. Three in
# flight keeps the service responsive under burst while staying
# well inside the politeness envelope.
_LOAD_SEMAPHORE = asyncio.Semaphore(3)


def _pick(d: dict | None, *keys: str):
    """Return the first present, non-empty value from a dict."""
    if not isinstance(d, dict):
        return None
    for key in keys:
        value = d.get(key)
        if value not in (None, ""):
            return value
    return None


def _normalise_reference(ref: dict) -> dict:
    """Flatten NBB reference metadata across PascalCase and camelCase variants."""
    exercise = _pick(ref, "ExerciseDates", "exerciseDates") or {}
    end_date = _pick(exercise, "endDate", "EndDate") or ""
    fiscal_year = int(end_date[:4]) if end_date and len(end_date) >= 4 else None
    return {
        "reference_number": str(_pick(ref, "ReferenceNumber", "referenceNumber") or ""),
        "deposit_date": str(_pick(ref, "DepositDate", "depositDate") or ""),
        "model_type": str(_pick(ref, "ModelType", "modelType") or ""),
        "fiscal_year": fiscal_year,
        "raw": ref,
    }


def _no_filings_result(cbe: str) -> dict:
    return {
        "enterprise_number": cbe,
        "filings_found": 0,
        "filings_loaded": 0,
        "rubrics_loaded": 0,
        "governance_loaded": _empty_governance_counts(),
        "status": "no_filings",
    }


def _empty_governance_counts() -> dict[str, int]:
    return {
        "administrators": 0,
        "shareholders": 0,
        "participating_interests": 0,
        "affiliations": 0,
    }


def _sum_governance_counts(counts: dict[str, int]) -> int:
    return sum(int(counts.get(key, 0) or 0) for key in _empty_governance_counts())


def _get_filing_sync_state(cur, cbe: str, deposit_key: str) -> dict[str, int | bool]:
    """Return whether financials exist already, and whether NBB admins do too."""
    cur.execute(
        """
        SELECT
            EXISTS(
                SELECT 1
                FROM nbb_load_log
                WHERE enterprise_number = %s
                  AND deposit_key = %s
            ) AS financials_loaded,
            COALESCE((
                SELECT COUNT(*)
                FROM administrator
                WHERE enterprise_number = %s
                  AND deposit_key = %s
            ), 0) AS admin_count
        """,
        (cbe, deposit_key, cbe, deposit_key),
    )
    row = cur.fetchone() or (False, 0)
    return {
        "financials_loaded": bool(row[0]),
        "admin_count": int(row[1] or 0),
    }


async def _nbb_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict,
    params: dict | None = None,
    timeout: float = 15.0,
    attempts: int = 3,
):
    """GET one NBB endpoint with light retry on transient failures only."""
    backoff_s = 1.0
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            response = await client.get(url, headers=headers, params=params, timeout=timeout)
        except httpx.RequestError as exc:
            last_exc = exc
            if attempt >= attempts:
                raise
            logger.warning(
                "NBB request failed on attempt %d/%d for %s: %s",
                attempt, attempts, url, exc,
            )
            await asyncio.sleep(backoff_s)
            backoff_s = min(backoff_s * 2, 4.0)
            continue

        if response.status_code in _NBB_RETRYABLE_STATUSES and attempt < attempts:
            logger.warning(
                "NBB returned transient HTTP %d on attempt %d/%d for %s",
                response.status_code, attempt, attempts, url,
            )
            await asyncio.sleep(backoff_s)
            backoff_s = min(backoff_s * 2, 4.0)
            continue
        return response

    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"NBB request exhausted retries without a response: {url}")


# ---------------------------------------------------------------------------
# POST /api/companies/{cbe}/load
# ---------------------------------------------------------------------------

@router.post("/{cbe}/load")
async def load_company_data(
    cbe: str,
    background_tasks: BackgroundTasks,
    fiscal_year: Optional[int] = Query(None, description="Only load filings for this fiscal year"),
    user=Depends(optional_user),
):
    """Load financial data from NBB for this company.

    Open to anonymous callers — the per-IP rate limiter in main.py
    (200 req/min) plus NBB's own gateway throttling are sufficient
    protection against quota exhaustion, and the UX of "sign in to
    see the financials we already publicly link to" was surprising.

    1. Fetch filing references (optionally filtered by fiscal year)
    2. For each reference (most recent 5), fetch JSON-XBRL filing
    3. Parse rubric codes and values
    4. Insert into financial_data table
    5. Refresh financial_latest and financial_by_year for this company
       (deferred to a BackgroundTask so the response returns as soon as
       the NBB inserts have committed — `financial_summary` is a live VIEW
       so the profile re-fetch sees fresh data immediately).
    """
    cbe = clean_cbe(cbe)

    nbb_key = os.getenv("NBB_AUTHENTIC_KEY", "")
    nbb_base = os.getenv("NBB_BASE_URL", "https://ws.cbso.nbb.be")

    if not nbb_key:
        raise HTTPException(status_code=503, detail="NBB API key not configured")

    # Global concurrency cap — serialise against other in-flight
    # /load calls so NBB sees at most 3 concurrent streams from us.
    async with _LOAD_SEMAPHORE:
        return await _do_load(cbe, fiscal_year, nbb_key, nbb_base, background_tasks)


async def _do_load(
    cbe: str,
    fiscal_year: Optional[int],
    nbb_key: str,
    nbb_base: str,
    background_tasks: BackgroundTasks,
):
    import uuid
    import psycopg2.extras

    # --- Step 1: Fetch filing references (non-blocking) ---
    # Previously used `requests.get` inside an async function — any slow NBB
    # call would block the whole uvicorn worker (single-process). httpx's
    # AsyncClient yields control while waiting on the network.
    headers_ref = {
        "Accept": "application/json",
        "NBB-CBSO-Subscription-Key": nbb_key,
        "X-Request-Id": str(uuid.uuid4()),
        "User-Agent": "Datasnoop/1.0 (Belgian Company Intelligence)",
    }
    ref_params = {}
    if fiscal_year:
        ref_params["fiscalYear"] = str(fiscal_year)

    async with httpx.AsyncClient() as client:
        try:
            resp = await _nbb_get(
                client,
                f"{nbb_base}/authentic/legalEntity/{cbe}/references",
                headers=headers_ref,
                params=ref_params or None,
                timeout=15.0,
            )
        except Exception as e:
            logger.error("NBB references request failed for %s: %s", cbe, e)
            raise HTTPException(status_code=502, detail=f"NBB API connection error: {e}")

    if resp.status_code == 404:
        return _no_filings_result(cbe)

    if resp.status_code in _NBB_AUTH_FAILURE_STATUSES:
        raise HTTPException(status_code=503, detail="NBB API authentication failed")

    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"NBB API error fetching references: HTTP {resp.status_code}",
        )

    references = resp.json()
    if not references:
        return _no_filings_result(cbe)

    normalised_refs = [_normalise_reference(ref) for ref in references]

    # Sort newest-first then try up to 15 references to find 5 successful
    # filings — old filings are PDF-only by virtue of pre-XBRL age and
    # would burn slots without ever loading data.
    sorted_refs = sorted(
        normalised_refs,
        key=lambda r: (r["deposit_date"], r["reference_number"]),
        reverse=True,
    )
    refs_to_load = sorted_refs[:15]

    # --- Step 2-4: Fetch, parse, and insert each filing ---
    conn = get_connection()
    total_rubrics = 0
    filings_loaded = 0
    governance_loaded = _empty_governance_counts()
    errors = []
    # NBB only publishes JSON-XBRL for the m02-f model (full-format scheme
    # used by larger companies). Smaller filers using m120/m211/m212 with
    # the -p suffix get a 404 with body containing "no published json xbrl".
    # We track these so we can flag the company as PDF-only on the profile
    # — distinguishes "we tried and got nothing structured" from "the data
    # just hasn't been requested yet". Look only at recent (post-2022 Apr)
    # filings since older ones are pre-XBRL by definition and wouldn't be
    # extractable regardless of model.
    pdf_only_404s = 0
    post2022_eligible_count = sum(
        1 for r in normalised_refs
        if r["deposit_date"] >= "2022-04"
        and isinstance(r["model_type"], str)
        and not r["model_type"].endswith("-p")
    )
    post2022_total = sum(
        1 for r in normalised_refs if r["deposit_date"] >= "2022-04"
    )

    try:
        cur = conn.cursor()
        async with httpx.AsyncClient() as client:
            for ref in refs_to_load:
                if filings_loaded >= 5:
                    break  # Stop after 5 successful filings
                ref_number = ref["reference_number"]
                if not ref_number:
                    continue

                sync_state = _get_filing_sync_state(cur, cbe, ref_number)
                financials_loaded_already = bool(sync_state["financials_loaded"])
                has_nbb_admins = int(sync_state["admin_count"] or 0) > 0

                if financials_loaded_already and has_nbb_admins:
                    logger.info("Skipping already-loaded filing %s for %s", ref_number, cbe)
                    continue
                if financials_loaded_already:
                    logger.info(
                        "Re-checking already-loaded filing %s for %s to backfill missing NBB admins",
                        ref_number,
                        cbe,
                    )

                # Inter-call rate-limit. NBB advises 1-2s between calls but
                # their own ~1.5s response time naturally satisfies that
                # for sequential fetches, so 0.25s is belt-and-suspenders.
                # Applied before EVERY filing fetch (including the first)
                # so the per-key NBB request rate stays bounded even when
                # `_LOAD_SEMAPHORE` allows three concurrent loads to enter
                # their first-filing fetch simultaneously.
                await asyncio.sleep(0.25)

                # Fetch JSON-XBRL data — async + light retry for transient
                # timeouts so a slow NBB response doesn't instantly break the
                # profile-triggered loader.
                headers_json = {
                    "Accept": "application/x.jsonxbrl",
                    "NBB-CBSO-Subscription-Key": nbb_key,
                    "X-Request-Id": str(uuid.uuid4()),
                    "User-Agent": "Datasnoop/1.0 (Belgian Company Intelligence)",
                }
                try:
                    filing_resp = await _nbb_get(
                        client,
                        f"{nbb_base}/authentic/deposit/{ref_number}/accountingData",
                        headers=headers_json,
                        timeout=30.0,
                    )
                except Exception as e:
                    logger.error("NBB filing request failed for ref %s: %s", ref_number, e)
                    errors.append(f"ref {ref_number}: connection error")
                    continue

                if filing_resp.status_code in _NBB_AUTH_FAILURE_STATUSES:
                    raise HTTPException(status_code=503, detail="NBB API authentication failed")

                if filing_resp.status_code != 200:
                    logger.warning(
                        "NBB filing %s returned HTTP %d", ref_number, filing_resp.status_code,
                    )
                    errors.append(f"ref {ref_number}: HTTP {filing_resp.status_code}")
                    # Detect the specific "no JSON-XBRL published" 404 — body
                    # contains the diagnostic string. Used after the loop to
                    # set the pdf_only flag on the response.
                    if filing_resp.status_code == 404:
                        body = (filing_resp.text or "").lower()
                        if "json xbrl" in body or "jsonxbrl" in body:
                            pdf_only_404s += 1
                    continue

                filing_json = filing_resp.json()

                # Extract metadata from the normalized reference
                deposit_date = ref["deposit_date"]
                filing_model = ref["model_type"]
                filing_fiscal_year = ref["fiscal_year"]

                # Parse rubrics (handle both capitalized and lowercase keys)
                rows = []
                for rubric in filing_json.get("Rubrics", filing_json.get("rubrics", [])):
                    code = rubric.get("Code", rubric.get("code", ""))
                    value = rubric.get("Value", rubric.get("value"))
                    period = rubric.get("Period", rubric.get("period", "N"))

                    if code and value is not None:
                        try:
                            float_val = float(str(value).replace(",", ".").strip())
                        except (ValueError, TypeError):
                            logger.warning(
                                "Skipping rubric %s in filing %s: non-numeric value %r",
                                code, ref_number, value,
                            )
                            continue
                        rows.append((
                            cbe, ref_number, filing_fiscal_year, deposit_date,
                            filing_model, code, period, float_val,
                        ))

                if rows:
                    try:
                        # Reset connection state if in error
                        if conn.status != 1:  # STATUS_READY = 1
                            conn.rollback()
                            logger.warning("Connection was in bad state for %s, rolled back", cbe)

                        psycopg2.extras.execute_batch(
                            cur,
                            """INSERT INTO financial_data
                               (enterprise_number, deposit_key, fiscal_year, deposit_date,
                                filing_model, rubric_code, period, value)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                               ON CONFLICT DO NOTHING""",
                            rows,
                        )
                        # Log the load
                        cur.execute(
                            "INSERT INTO nbb_load_log (enterprise_number, deposit_key, rubric_count) "
                            "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                            (cbe, ref_number, len(rows)),
                        )
                        conn.commit()  # Commit EACH filing immediately
                        if financials_loaded_already:
                            logger.info(
                                "Reused existing financial rows for filing %s of %s while backfilling governance",
                                ref_number,
                                cbe,
                            )
                        else:
                            total_rubrics += len(rows)
                            filings_loaded += 1
                        if not financials_loaded_already:
                            logger.info(
                            "Loaded filing %s for %s: %d rubrics (FY %s) — committed",
                            ref_number, cbe, len(rows), filing_fiscal_year,
                        )
                    except Exception as batch_err:
                        conn.rollback()
                        logger.error(
                            "Failed to insert rubrics for filing %s of %s: %s",
                            ref_number, cbe, batch_err,
                        )
                        errors.append(f"ref {ref_number}: insert failed: {batch_err}")
                else:
                    logger.info("Filing %s for %s had no rubrics", ref_number, cbe)

                try:
                    governance_counts = store_governance_snapshot(
                        conn, cbe, ref_number, filing_fiscal_year, filing_json,
                    )
                    for key, value in governance_counts.items():
                        governance_loaded[key] += int(value or 0)
                    if any(governance_counts.values()):
                        logger.info(
                            "Stored governance for %s filing %s: %d admins, %d shareholders, %d subsidiaries",
                            cbe,
                            ref_number,
                            governance_counts["administrators"],
                            governance_counts["shareholders"],
                            governance_counts["participating_interests"],
                        )
                except Exception as gov_err:
                    logger.warning(
                        "Governance snapshot store failed for %s filing %s: %s",
                        cbe, ref_number, gov_err,
                    )

        # --- Step 5: Schedule materialized-table refresh as background task ---
        # `financial_summary` is a live VIEW so the profile's GET /financials
        # re-fetch already sees the new rubrics — `financial_latest` and
        # `financial_by_year` only feed the screener / search / sector
        # benchmarks, none of which fire in the same render. Deferring saves
        # ~300-500ms on perceived load latency.
        background_tasks.add_task(_refresh_materialized_for_company_bg, cbe)

        cur.close()
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        logger.exception("Error loading financial data for %s", cbe)
        raise HTTPException(status_code=500, detail=f"Error loading data: {e}")
    finally:
        from db import put_connection
        put_connection(conn)

    # Final flag: this CBE's recent filings are PDF-only.
    # Two equivalent paths to true (either is sufficient):
    #   (a) NBB has at least one post-2022 filing for this company, but
    #       NONE of them are JSON-XBRL eligible (every model ends in -p).
    #       This is the cleanest signal — derived from references metadata
    #       alone, no per-filing fetch required.
    #   (b) We actually tried to load and got the explicit "no published
    #       json xbrl" diagnostic from NBB. Belt + suspenders for the case
    #       where NBB's reference metadata lies about model availability.
    pdf_only = filings_loaded == 0 and (
        (post2022_total > 0 and post2022_eligible_count == 0)
        or pdf_only_404s > 0
    )

    if pdf_only:
        # Stamp nbb_load_log with a sentinel row so /financials can read
        # the flag without re-hitting NBB. Idempotent on the PK.
        try:
            conn2 = get_connection()
            try:
                cur2 = conn2.cursor()
                cur2.execute(
                    "INSERT INTO nbb_load_log (enterprise_number, deposit_key, rubric_count) "
                    "VALUES (%s, 'PDF_ONLY', 0) ON CONFLICT DO NOTHING",
                    (cbe,),
                )
                conn2.commit()
                cur2.close()
            finally:
                from db import put_connection
                put_connection(conn2)
        except Exception:
            logger.debug("Failed to stamp PDF_ONLY marker for %s", cbe, exc_info=True)

    result = {
        "enterprise_number": cbe,
        "filings_found": len(references),
        "filings_loaded": filings_loaded,
        "rubrics_loaded": total_rubrics,
        "governance_loaded": governance_loaded,
        "pdf_only": pdf_only,
        "status": (
            "loaded"
            if filings_loaded > 0
            else (
                "governance_backfilled"
                if _sum_governance_counts(governance_loaded) > 0
                else ("pdf_only" if pdf_only else "no_new_data")
            )
        ),
    }
    if errors:
        result["errors"] = errors
    return result


def _refresh_materialized_for_company_bg(cbe: str) -> None:
    """BackgroundTask wrapper — acquires its own connection from the pool
    and delegates to the original refresh routine. Errors are logged but
    not raised (the response has already been sent to the client)."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        try:
            _refresh_materialized_for_company(cur, conn, cbe)
        finally:
            cur.close()
    except Exception:
        logger.exception("Background matview refresh failed for %s", cbe)
    finally:
        put_connection(conn)


def _refresh_materialized_for_company(cur, conn, cbe: str):
    """Refresh financial_latest and financial_by_year for a single company.

    Instead of rebuilding the full tables (expensive), we delete+reinsert
    only the rows for this company using the financial_summary view.
    """
    # Refresh financial_latest for this company. Explicit target column
    # list — `fixed_assets` lives at position 16 on the live table (added
    # via ALTER TABLE), not next to `total_assets`. Positional insert
    # without a column list silently shifts fte_total / personnel_costs /
    # fixed_assets into the wrong slots.
    cur.execute("DELETE FROM financial_latest WHERE enterprise_number = %s", (cbe,))
    cur.execute("""
        INSERT INTO financial_latest
            (enterprise_number, fiscal_year, filing_model,
             revenue, ebit, da, ebitda, net_profit,
             equity, lt_financial_debt, st_financial_debt, cash,
             total_assets, fixed_assets, fte_total, personnel_costs)
        SELECT enterprise_number, fiscal_year, filing_model,
               revenue, ebit, da, ebitda, net_profit,
               equity, lt_financial_debt, st_financial_debt, cash,
               total_assets, fixed_assets, fte_total, personnel_costs
        FROM (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY enterprise_number
                       ORDER BY fiscal_year DESC, deposit_key DESC
                   ) AS rn
            FROM financial_summary
            WHERE enterprise_number = %s
        ) sub
        WHERE rn = 1
    """, (cbe,))

    # Refresh financial_by_year for this company
    cur.execute("DELETE FROM financial_by_year WHERE enterprise_number = %s", (cbe,))
    cur.execute("""
        INSERT INTO financial_by_year
        SELECT enterprise_number, fiscal_year, filing_model,
               revenue, ebit, da, ebitda, net_profit,
               equity, lt_financial_debt, st_financial_debt, cash,
               total_assets, fte_total, personnel_costs
        FROM financial_summary
        WHERE enterprise_number = %s
    """, (cbe,))

    # Also upsert company_info if this company isn't in it yet.
    # Keep priority rules in lockstep with refresh_company_info() in
    # backend/kbo_daily_update.py: language NL > FR > none > DE > EN, and
    # NACE preferred from activity_group '006' (RSZ — what employees do)
    # over '001' (VAT — tax filing classification).
    cur.execute("SELECT 1 FROM company_info WHERE enterprise_number = %s", (cbe,))
    if not cur.fetchone():
        cur.execute("""
            INSERT INTO company_info (enterprise_number, name, city, zipcode, nace_code)
            SELECT DISTINCT ON (e.enterprise_number)
                e.enterprise_number,
                d.denomination,
                a.municipality_nl,
                a.zipcode,
                act.nace_code
            FROM enterprise e
            LEFT JOIN denomination d
                   ON d.entity_number = e.enterprise_number
                  AND d.type_of_denomination = '001'
            LEFT JOIN address a
                   ON a.entity_number = e.enterprise_number
                  AND a.type_of_address = 'REGO'
            LEFT JOIN LATERAL (
                SELECT nace_code FROM activity
                WHERE entity_number = e.enterprise_number
                  AND classification = 'MAIN'
                  AND activity_group IN ('006', '001')
                ORDER BY
                    CASE activity_group WHEN '006' THEN 1 WHEN '001' THEN 2 ELSE 3 END,
                    CASE nace_version  WHEN '2025' THEN 1 WHEN '2008' THEN 2
                                       WHEN '2003' THEN 3 ELSE 4 END
                LIMIT 1
            ) act ON TRUE
            WHERE e.enterprise_number = %s
            ORDER BY e.enterprise_number,
                     CASE d.language WHEN '2' THEN 1 WHEN '1' THEN 2 WHEN '0' THEN 3
                                     WHEN '3' THEN 4 WHEN '4' THEN 5 ELSE 6 END,
                     d.denomination NULLS LAST
        """, (cbe,))

    conn.commit()
    logger.info("Refreshed materialized tables for %s", cbe)


# ---------------------------------------------------------------------------
# GET /api/companies/{cbe}/financials
# ---------------------------------------------------------------------------

@router.get("/{cbe}/financials")
async def get_company_financials(cbe: str, response: Response):
    """Financial history from financial_summary.

    SQL extracted from app/pages/2_company.py load_company_detail() hist query.
    """
    cbe = clean_cbe(cbe)
    # NBB filings land at most once per fiscal year, so the populated
    # response is fine to cache for 5 min with a long SWR window for
    # snappy tab-switching. The header is overridden to no-store on the
    # empty path below — caching an empty response would let the browser
    # serve stale `[]` to the post-/load auto-refetch and hide freshly
    # loaded financials until the cache expires.
    response.headers["Cache-Control"] = "private, max-age=300, stale-while-revalidate=86400"

    t_total = time.perf_counter()

    try:
        t0 = time.perf_counter()
        hist = fetch_all("""
            SELECT fiscal_year, deposit_key, filing_model,
                   revenue, gross_margin, ebit, da, ebitda, net_profit,
                   equity, lt_debt, lt_financial_debt, st_financial_debt, cash, total_assets,
                   fixed_assets, inventories, trade_receivables, trade_payables,
                   financial_charges, fte_total, personnel_costs, current_investments,
                   CASE WHEN revenue > 0
                        THEN ROUND((ebitda / revenue * 100)::numeric, 1)
                   END AS "ebitda_margin_pct"
            FROM financial_summary
            WHERE enterprise_number = %s
            ORDER BY fiscal_year
        """, (cbe,))
        logger.info("financials.subquery=summary cbe=%s ms=%.0f rows=%d", cbe, (time.perf_counter()-t0)*1000, len(hist) if hist else 0)

        # PDF-only flag: set by /load when every recent NBB deposit was
        # 404'd with the "no published json xbrl" diagnostic. Lets the
        # frontend explain WHY a company has no financial rows instead
        # of silently rendering an empty state.
        t0 = time.perf_counter()
        pdf_only_row = fetch_one(
            "SELECT 1 AS x FROM nbb_load_log "
            "WHERE enterprise_number = %s AND deposit_key = 'PDF_ONLY' LIMIT 1",
            (cbe,),
        )
        pdf_only = bool(pdf_only_row)
        logger.info("financials.subquery=pdf_only cbe=%s ms=%.0f", cbe, (time.perf_counter()-t0)*1000)

        if not hist:
            # Don't let the browser cache the empty state unless we're
            # confident no data will ever load (PDF_ONLY companies have
            # no JSON-XBRL filings so the response is genuinely stable).
            # For anything else, the auto-load on the profile is about to
            # populate `financial_data` — caching `[]` for 5 min would
            # hide the new rows until the cache expires.
            if not pdf_only:
                response.headers["Cache-Control"] = "no-store"
            logger.info("financials.total cbe=%s ms=%.0f rows=0 (early exit)", cbe, (time.perf_counter()-t_total)*1000)
            return {"summary": [], "pnl": {}, "pdf_only": pdf_only}

        # P&L rubric data
        pnl_codes = [
            "70", "74", "70/76A", "60", "61", "62", "630", "631/4", "635/8",
            "640/8", "60/66A", "9901", "75", "65", "9902", "76", "66",
            "9903", "67/77", "9904",
            # Cash-flow derivation: dividends paid (appropriation of result)
            "694",
        ]
        bs_codes = [
            "20/28", "21", "22", "28", "29/58", "3", "41", "54/58",
            "20/58", "10/15", "16", "17", "43", "44", "10/49",
            # Cash-flow derivation additions. Split-out rubrics matter because
            # a holding's Δ(21/28) is dominated by Δ(28) = financial fixed
            # assets (subsidiaries), which is M&A/consolidation — not CapEx.
            # 22/27 — tangible fixed assets
            # 21    — intangible fixed assets (overlaps "21" already listed)
            # 28    — financial fixed assets (participations)
            # 40/41 — full trade receivables (was only 41 = LT receivables)
            # 45 — tax, remuneration, social security payables
            # 47/48 — other amounts payable ≤1y
            # 50/53 — current investments (cash proxy)
            # 170/4 — LT financial debt (subset of 17)
            # 10    — capital; 11 — share premium (actual cash-raised equity)
            # 12    — revaluation reserves (non-cash equity movement — needed
            #         to avoid mis-classifying revaluations as new capital
            #         in the newCapital fallback)
            # 13 — reserves; 14 — accumulated profits (non-cash reclassifications)
            # 15    — investment grants (part of total equity 10/15 — subtract
            #         from newCapital fallback so a grant isn't counted as
            #         cash-raised capital)
            # 42/48 — aggregate short-term payables (fallback when the
            #         per-bucket rubrics 44/45/46/47/48 aren't filed individually)
            "22/27", "40/41", "45", "47/48", "50/53", "170/4",
            "10", "11", "12", "13", "14", "15",
            "42/48",
        ]
        all_codes = list(dict.fromkeys(pnl_codes + bs_codes))
        placeholders = ",".join(["%s"] * len(all_codes))

        t0 = time.perf_counter()
        rubric_rows = fetch_all(f"""
            SELECT fiscal_year, rubric_code, value
            FROM financial_data
            WHERE enterprise_number = %s
              AND period = 'N'
              AND rubric_code IN ({placeholders})
        """, [cbe] + all_codes)
        logger.info("financials.subquery=rubric_data cbe=%s ms=%.0f rows=%d codes=%d", cbe, (time.perf_counter()-t0)*1000, len(rubric_rows) if rubric_rows else 0, len(all_codes))

        # Pivot rubric data: {rubric_code: {fiscal_year: value}}
        rubric_pivot = {}
        for row in rubric_rows:
            code = row["rubric_code"]
            fy = row["fiscal_year"]
            val = row["value"]
            if code not in rubric_pivot:
                rubric_pivot[code] = {}
            rubric_pivot[code][str(fy)] = float(val) if val is not None else None

        logger.info("financials.total cbe=%s ms=%.0f summary_rows=%d", cbe, (time.perf_counter()-t_total)*1000, len(hist))
        return {
            "summary": [_serialize_row(r) for r in hist],
            "rubric_data": rubric_pivot,
            "pdf_only": pdf_only,
        }
    except Exception as e:
        logger.exception("Company financials query failed cbe=%s ms=%.0f", cbe, (time.perf_counter()-t_total)*1000)
        raise HTTPException(status_code=500, detail="Internal server error")
