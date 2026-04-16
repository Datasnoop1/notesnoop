"""Companies financials router — load financial data from NBB and read history."""

import logging
import os
from typing import Optional

import requests as http_requests
from fastapi import APIRouter, Depends, HTTPException, Query

from db import fetch_all, fetch_one, get_connection, put_connection
from auth import get_current_user
from utils import clean_cbe
from ._helpers import _serialize_row

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# POST /api/companies/{cbe}/load
# ---------------------------------------------------------------------------

@router.post("/{cbe}/load")
async def load_company_data(cbe: str, fiscal_year: Optional[int] = Query(None, description="Only load filings for this fiscal year"), user=Depends(get_current_user)):
    """Load financial data from NBB for this company.

    1. Fetch filing references (optionally filtered by fiscal year)
    2. For each reference (most recent 5), fetch JSON-XBRL filing
    3. Parse rubric codes and values
    4. Insert into financial_data table
    5. Refresh financial_latest and financial_by_year for this company
    """
    import time
    import uuid
    import psycopg2.extras

    cbe = clean_cbe(cbe)

    nbb_key = os.getenv("NBB_AUTHENTIC_KEY", "")
    nbb_base = os.getenv("NBB_BASE_URL", "https://ws.cbso.nbb.be")

    if not nbb_key:
        raise HTTPException(status_code=503, detail="NBB API key not configured")

    # --- Step 1: Fetch filing references ---
    headers_ref = {
        "Accept": "application/json",
        "NBB-CBSO-Subscription-Key": nbb_key,
        "X-Request-Id": str(uuid.uuid4()),
        "User-Agent": "Datasnoop/1.0 (Belgian Company Intelligence)",
    }
    ref_params = {}
    if fiscal_year:
        ref_params["fiscalYear"] = str(fiscal_year)

    try:
        resp = http_requests.get(
            f"{nbb_base}/authentic/legalEntity/{cbe}/references",
            headers=headers_ref, params=ref_params or None, timeout=15,
        )
    except Exception as e:
        logger.error("NBB references request failed for %s: %s", cbe, e)
        raise HTTPException(status_code=502, detail=f"NBB API connection error: {e}")

    if resp.status_code != 200:
        raise HTTPException(
            status_code=resp.status_code,
            detail=f"NBB API error fetching references: HTTP {resp.status_code}",
        )

    references = resp.json()
    if not references:
        return {
            "enterprise_number": cbe,
            "filings_found": 0,
            "filings_loaded": 0,
            "rubrics_loaded": 0,
            "status": "no_filings",
        }

    # Try up to 15 references to find 5 successful filings (some return 404)
    refs_to_load = references[:15]

    # --- Step 2-4: Fetch, parse, and insert each filing ---
    conn = get_connection()
    total_rubrics = 0
    filings_loaded = 0
    errors = []

    try:
        cur = conn.cursor()

        for ref in refs_to_load:
            if filings_loaded >= 5:
                break  # Stop after 5 successful filings
            ref_number = ref.get("ReferenceNumber", "")
            if not ref_number:
                continue

            # Check if already loaded (skip duplicates)
            cur.execute(
                "SELECT 1 FROM nbb_load_log WHERE enterprise_number = %s AND deposit_key = %s",
                (cbe, ref_number),
            )
            if cur.fetchone():
                logger.info("Skipping already-loaded filing %s for %s", ref_number, cbe)
                continue

            # Respect NBB rate limits
            time.sleep(1)

            # Fetch JSON-XBRL data
            headers_json = {
                "Accept": "application/x.jsonxbrl",
                "NBB-CBSO-Subscription-Key": nbb_key,
                "X-Request-Id": str(uuid.uuid4()),
                "User-Agent": "Datasnoop/1.0 (Belgian Company Intelligence)",
            }
            try:
                filing_resp = http_requests.get(
                    f"{nbb_base}/authentic/deposit/{ref_number}/accountingData",
                    headers=headers_json, timeout=30,
                )
            except Exception as e:
                logger.error("NBB filing request failed for ref %s: %s", ref_number, e)
                errors.append(f"ref {ref_number}: connection error")
                continue

            if filing_resp.status_code != 200:
                logger.warning(
                    "NBB filing %s returned HTTP %d", ref_number, filing_resp.status_code,
                )
                errors.append(f"ref {ref_number}: HTTP {filing_resp.status_code}")
                continue

            filing_json = filing_resp.json()

            # Extract metadata from reference
            deposit_date = ref.get("DepositDate", "")
            filing_model = ref.get("ModelType", "")
            exercise = ref.get("ExerciseDates", {})
            end_date = exercise.get("endDate", "")
            fiscal_year = int(end_date[:4]) if end_date and len(end_date) >= 4 else None

            # Parse rubrics (handle both capitalized and lowercase keys)
            rows = []
            for rubric in filing_json.get("Rubrics", filing_json.get("rubrics", [])):
                code = rubric.get("Code", rubric.get("code", ""))
                value = rubric.get("Value", rubric.get("value"))
                period = rubric.get("Period", rubric.get("period", "N"))

                if code and value is not None:
                    rows.append((
                        cbe, ref_number, fiscal_year, deposit_date,
                        filing_model, code, period, float(value),
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
                    total_rubrics += len(rows)
                    filings_loaded += 1
                    logger.info(
                        "Loaded filing %s for %s: %d rubrics (FY %s) — committed",
                        ref_number, cbe, len(rows), fiscal_year,
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

            # --- Extract administrators from filing ---
            admins = filing_json.get("Administrators", {})
            for person in admins.get("NaturalPersons", []):
                p = person.get("Person", {})
                name = f"{p.get('FirstName', '')} {p.get('LastName', '')}".strip()
                if not name:
                    continue
                for mandate in person.get("Mandates", []):
                    role = mandate.get("FunctionMandate", "")
                    dates = mandate.get("MandateDates", {})
                    try:
                        cur.execute("""
                            INSERT INTO administrator (enterprise_number, name, role, mandate_start, mandate_end, person_type)
                            VALUES (%s, %s, %s, %s, %s, 'natural')
                            ON CONFLICT DO NOTHING
                        """, (cbe, name, role, dates.get("StartDate"), dates.get("EndDate")))
                    except Exception:
                        pass
            for lp in admins.get("LegalPersons", []):
                lp_name = lp.get("Entity", {}).get("Name", "")
                if not lp_name:
                    continue
                lp_id = lp.get("Entity", {}).get("Identifier", "")
                for mandate in lp.get("Mandates", []):
                    role = mandate.get("FunctionMandate", "")
                    dates = mandate.get("MandateDates", {})
                    try:
                        cur.execute("""
                            INSERT INTO administrator (enterprise_number, name, role, mandate_start, mandate_end, identifier, person_type)
                            VALUES (%s, %s, %s, %s, %s, %s, 'legal')
                            ON CONFLICT DO NOTHING
                        """, (cbe, lp_name, role, dates.get("StartDate"), dates.get("EndDate"), lp_id or None))
                    except Exception:
                        pass

            # --- Extract participating interests (subsidiaries) ---
            interests = filing_json.get("ParticipatingInterests", [])
            if isinstance(interests, list):
                for pi in interests:
                    entity = pi.get("Entity", {})
                    pi_name = entity.get("Name", "")
                    pi_id = entity.get("Identifier", "")
                    if not pi_name:
                        continue
                    # Get ownership percentage from holdings
                    pct = None
                    for holding in pi.get("ParticipatingInterestHeld", []):
                        pct_str = holding.get("PercentageDirectlyHeld")
                        if pct_str:
                            try:
                                pct = float(pct_str) * 100  # 0.2 → 20%
                            except (ValueError, TypeError):
                                pass
                            break
                    try:
                        cur.execute("""
                            INSERT INTO participating_interest (enterprise_number, name, ownership_pct, identifier, fiscal_year, country)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT DO NOTHING
                        """, (cbe, pi_name, pct, pi_id or None, str(fiscal_year) if fiscal_year else None, "BE"))
                    except Exception:
                        pass

            # --- Extract shareholders ---
            shareholders = filing_json.get("Shareholders", {})
            for sh in shareholders.get("EntityShareHolders", []):
                sh_name = sh.get("Entity", {}).get("Name", "")
                sh_id = sh.get("Entity", {}).get("Identifier", "")
                sh_pct = None
                for holding in sh.get("SharesHeld", sh.get("ParticipatingInterestHeld", [])):
                    pct_str = holding.get("PercentageDirectlyHeld")
                    if pct_str:
                        try:
                            sh_pct = float(pct_str) * 100
                        except (ValueError, TypeError):
                            pass
                        break
                if sh_name:
                    try:
                        cur.execute("""
                            INSERT INTO shareholder (enterprise_number, name, ownership_pct, shareholder_type, identifier, fiscal_year)
                            VALUES (%s, %s, %s, 'entity', %s, %s)
                            ON CONFLICT DO NOTHING
                        """, (cbe, sh_name, sh_pct, sh_id or None, str(fiscal_year) if fiscal_year else None))
                    except Exception:
                        pass
            for sh in shareholders.get("IndividualShareHolders", []):
                p = sh.get("Person", {})
                sh_name = f"{p.get('FirstName', '')} {p.get('LastName', '')}".strip()
                if sh_name:
                    try:
                        cur.execute("""
                            INSERT INTO shareholder (enterprise_number, name, shareholder_type, fiscal_year)
                            VALUES (%s, %s, 'individual', %s)
                            ON CONFLICT DO NOTHING
                        """, (cbe, sh_name, str(fiscal_year) if fiscal_year else None))
                    except Exception:
                        pass

            conn.commit()

        # --- Step 5: Refresh materialized tables for this company ---
        _refresh_materialized_for_company(cur, conn, cbe)

        cur.close()
    except Exception as e:
        conn.rollback()
        logger.exception("Error loading financial data for %s", cbe)
        raise HTTPException(status_code=500, detail=f"Error loading data: {e}")
    finally:
        from db import put_connection
        put_connection(conn)

    result = {
        "enterprise_number": cbe,
        "filings_found": len(references),
        "filings_loaded": filings_loaded,
        "rubrics_loaded": total_rubrics,
        "status": "loaded" if filings_loaded > 0 else "no_new_data",
    }
    if errors:
        result["errors"] = errors
    return result


def _refresh_materialized_for_company(cur, conn, cbe: str):
    """Refresh financial_latest and financial_by_year for a single company.

    Instead of rebuilding the full tables (expensive), we delete+reinsert
    only the rows for this company using the financial_summary view.
    """
    # Refresh financial_latest for this company
    cur.execute("DELETE FROM financial_latest WHERE enterprise_number = %s", (cbe,))
    cur.execute("""
        INSERT INTO financial_latest
        SELECT enterprise_number, fiscal_year, filing_model,
               revenue, ebit, da, ebitda, net_profit,
               equity, lt_financial_debt, st_financial_debt, cash,
               total_assets, fte_total, personnel_costs
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

    # Also upsert company_info if this company isn't in it yet
    cur.execute("SELECT 1 FROM company_info WHERE enterprise_number = %s", (cbe,))
    if not cur.fetchone():
        cur.execute("""
            INSERT INTO company_info (enterprise_number, name, city, zipcode, nace_code)
            SELECT
                %s,
                MAX(d.denomination),
                MAX(a.municipality_nl),
                MAX(a.zipcode),
                MAX(act.nace_code)
            FROM enterprise e
            LEFT JOIN denomination d
                   ON d.entity_number = e.enterprise_number
                  AND d.type_of_denomination = '001'
                  AND d.language IN ('2', '1')
            LEFT JOIN address a
                   ON a.entity_number = e.enterprise_number
                  AND a.type_of_address = 'REGO'
            LEFT JOIN activity act
                   ON act.entity_number = e.enterprise_number
                  AND act.classification = 'MAIN'
            WHERE e.enterprise_number = %s
        """, (cbe, cbe))

    conn.commit()
    logger.info("Refreshed materialized tables for %s", cbe)


# ---------------------------------------------------------------------------
# GET /api/companies/{cbe}/financials
# ---------------------------------------------------------------------------

@router.get("/{cbe}/financials")
async def get_company_financials(cbe: str):
    """Financial history from financial_summary.

    SQL extracted from app/pages/2_company.py load_company_detail() hist query.
    """
    cbe = clean_cbe(cbe)

    try:
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

        if not hist:
            return {"summary": [], "pnl": {}}

        # P&L rubric data
        pnl_codes = [
            "70", "74", "70/76A", "60", "61", "62", "630", "631/4", "635/8",
            "640/8", "60/66A", "9901", "75", "65", "9902", "76", "66",
            "9903", "67/77", "9904",
        ]
        bs_codes = [
            "20/28", "21", "22", "28", "29/58", "3", "41", "54/58",
            "20/58", "10/15", "16", "17", "43", "44", "10/49",
        ]
        all_codes = list(dict.fromkeys(pnl_codes + bs_codes))
        placeholders = ",".join(["%s"] * len(all_codes))

        rubric_rows = fetch_all(f"""
            SELECT fiscal_year, rubric_code, value
            FROM financial_data
            WHERE enterprise_number = %s
              AND period = 'N'
              AND rubric_code IN ({placeholders})
        """, [cbe] + all_codes)

        # Pivot rubric data: {rubric_code: {fiscal_year: value}}
        rubric_pivot = {}
        for row in rubric_rows:
            code = row["rubric_code"]
            fy = row["fiscal_year"]
            val = row["value"]
            if code not in rubric_pivot:
                rubric_pivot[code] = {}
            rubric_pivot[code][str(fy)] = float(val) if val is not None else None

        return {
            "summary": [_serialize_row(r) for r in hist],
            "rubric_data": rubric_pivot,
        }
    except Exception as e:
        logger.exception("Company financials query failed")
        raise HTTPException(status_code=500, detail="Internal server error")
