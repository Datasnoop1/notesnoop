"""Companies router — search, detail, financials, structure, and network graph."""

import logging
import os
from collections import deque
from typing import Optional

import requests as http_requests
from fastapi import APIRouter, Depends, HTTPException, Query

from db import fetch_all, fetch_one, execute, get_connection, put_connection, get_conn
from auth import get_current_user, optional_user
from ai_client import ai_complete

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/companies", tags=["companies"])

ROLE_LABELS = {
    "fct:m10": "Director", "fct:m11": "Managing director",
    "fct:m12": "Chairman", "fct:m13": "Administrator",
    "fct:m14": "Secretary", "fct:m15": "Treasurer",
    "fct:m20": "Statutory auditor", "fct:m30": "Liquidator",
    "fct:m40": "Daily management",
}

MAX_NETWORK_NODES = 200


def _clean_cbe(identifier) -> Optional[str]:
    """Strip dots/spaces from identifier, return 10-digit CBE or None."""
    if not identifier:
        return None
    c = str(identifier).replace(".", "").replace(" ", "").strip()
    return c if c.isdigit() and len(c) == 10 else None


def _serialize_row(row: dict) -> dict:
    """Convert Decimal/date types to JSON-safe primitives."""
    import decimal
    import datetime
    out = {}
    for k, v in row.items():
        if isinstance(v, decimal.Decimal):
            out[k] = float(v)
        elif isinstance(v, (datetime.date, datetime.datetime)):
            out[k] = str(v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# GET /api/companies/search?q=...
# ---------------------------------------------------------------------------

@router.get("/search")
async def search_companies(q: str = Query(..., min_length=1)):
    """Search companies by name or CBE number.

    SQL extracted from app/pages/2_company.py search_companies().
    """
    query = q.strip()
    cbe_clean = query.replace(".", "").replace(" ", "")

    try:
        if cbe_clean.isdigit():
            # CBE prefix search on enterprise (fast, indexed)
            rows = fetch_all("""
                SELECT e.enterprise_number, COALESCE(ci.name, e.enterprise_number) AS "name",
                       e.status, e.juridical_form AS "jf_label", ci.city,
                       COALESCE(nl.description, ci.nace_code) AS "sector", e.start_date,
                       fl.revenue, fl.ebitda,
                       CASE WHEN fl.revenue > 0 THEN ROUND((fl.ebitda / fl.revenue * 100)::numeric, 1) END AS "ebitda_margin_pct",
                       fl.fte_total, fl.fiscal_year
                FROM enterprise e
                LEFT JOIN company_info ci ON ci.enterprise_number = e.enterprise_number
                LEFT JOIN financial_latest fl ON fl.enterprise_number = e.enterprise_number
                LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
                WHERE e.enterprise_number LIKE %s
                LIMIT 20
            """, (f"{cbe_clean}%",))
        else:
            # First: search company_info (170K, fast, has financials)
            rows = fetch_all("""
                SELECT ci.enterprise_number, ci.name,
                       e.status, e.juridical_form AS "jf_label", ci.city,
                       COALESCE(nl.description, ci.nace_code) AS "sector", e.start_date,
                       fl.revenue, fl.ebitda,
                       CASE WHEN fl.revenue > 0 THEN ROUND((fl.ebitda / fl.revenue * 100)::numeric, 1) END AS "ebitda_margin_pct",
                       fl.fte_total, fl.fiscal_year
                FROM company_info ci
                JOIN enterprise e ON e.enterprise_number = ci.enterprise_number
                LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
                LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
                WHERE ci.name ILIKE %s
                ORDER BY ci.name
                LIMIT 20
            """, (f"%{query}%",))

            # If not enough results, also search denomination table
            if len(rows) < 20:
                remaining = 20 - len(rows)
                existing_cbes = {r["enterprise_number"] for r in rows}
                extra = fetch_all("""
                    SELECT e.enterprise_number, d.denomination AS "name",
                           e.status, e.juridical_form AS "jf_label",
                           a.municipality_nl AS "city",
                           NULL AS "sector", e.start_date,
                           NULL::real AS "revenue", NULL::real AS "ebitda",
                           NULL::numeric AS "ebitda_margin_pct",
                           NULL::real AS "fte_total", NULL::integer AS "fiscal_year"
                    FROM denomination d
                    JOIN enterprise e ON e.enterprise_number = d.entity_number
                    LEFT JOIN address a ON a.entity_number = e.enterprise_number AND a.type_of_address = 'REGO'
                    WHERE d.denomination ILIKE %s
                      AND d.type_of_denomination = '001'
                      AND d.language IN ('2','1')
                    ORDER BY d.denomination
                    LIMIT %s
                """, (f"%{query}%", remaining + 10))
                for r in extra:
                    if r["enterprise_number"] not in existing_cbes:
                        rows.append(r)
                        existing_cbes.add(r["enterprise_number"])
                        if len(rows) >= 20:
                            break

            # If no results, try alternative/fuzzy matches
            if not rows:
                words = query.split()
                if len(words) > 1:
                    # Try matching any word
                    conditions = " OR ".join(["ci.name ILIKE %s"] * len(words))
                    params = tuple(f"%{w}%" for w in words)
                    rows = fetch_all(f"""
                        SELECT ci.enterprise_number, ci.name,
                               e.status, e.juridical_form AS "jf_label", ci.city,
                               COALESCE(nl.description, ci.nace_code) AS "sector", e.start_date,
                               fl.revenue, fl.ebitda,
                               CASE WHEN fl.revenue > 0 THEN ROUND((fl.ebitda / fl.revenue * 100)::numeric, 1) END AS "ebitda_margin_pct",
                               fl.fte_total, fl.fiscal_year
                        FROM company_info ci
                        JOIN enterprise e ON e.enterprise_number = ci.enterprise_number
                        LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
                        LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
                        WHERE {conditions}
                        ORDER BY ci.name LIMIT 20
                    """, params)
                elif len(query) >= 3:
                    # Try prefix match
                    rows = fetch_all("""
                        SELECT ci.enterprise_number, ci.name,
                               e.status, e.juridical_form AS "jf_label", ci.city,
                               COALESCE(nl.description, ci.nace_code) AS "sector", e.start_date,
                               fl.revenue, fl.ebitda,
                               CASE WHEN fl.revenue > 0 THEN ROUND((fl.ebitda / fl.revenue * 100)::numeric, 1) END AS "ebitda_margin_pct",
                               fl.fte_total, fl.fiscal_year
                        FROM company_info ci
                        JOIN enterprise e ON e.enterprise_number = ci.enterprise_number
                        LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
                        LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
                        WHERE ci.name ILIKE %s
                        ORDER BY ci.name LIMIT 20
                    """, (f"{query}%",))

        return [_serialize_row(r) for r in rows]
    except Exception as e:
        logger.exception("Company search failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/companies/semantic-search?q=...
# ---------------------------------------------------------------------------

@router.get("/semantic-search")
async def semantic_search(q: str = Query(..., min_length=1)):
    """Fuzzy / semantic company search using pg_trgm trigram similarity.

    Searches company_info.name with trigram similarity scoring, then falls
    back to ILIKE if no good trigram matches are found.  When the
    company_embedding table contains vectors in the future, cosine-similarity
    results will be merged in automatically.
    """
    query = q.strip()

    try:
        # --- Phase 1: trigram similarity on company_info.name --------
        trgm_rows = fetch_all("""
            SELECT ci.enterprise_number, ci.name,
                   e.status, e.juridical_form AS "jf_label", ci.city,
                   COALESCE(nl.description, ci.nace_code) AS "sector",
                   e.start_date,
                   fl.revenue, fl.ebitda,
                   CASE WHEN fl.revenue > 0
                        THEN ROUND((fl.ebitda / fl.revenue * 100)::numeric, 1)
                   END AS "ebitda_margin_pct",
                   fl.fte_total, fl.fiscal_year,
                   similarity(ci.name, %s) AS score
            FROM company_info ci
            JOIN enterprise e ON e.enterprise_number = ci.enterprise_number
            LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
            LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
            WHERE similarity(ci.name, %s) > 0.15
               OR ci.name ILIKE %s
            ORDER BY similarity(ci.name, %s) DESC, ci.name
            LIMIT 25
        """, (query, query, f"%{query}%", query))

        # --- Phase 2: vector cosine search (when embeddings exist) ---
        emb_rows = []
        try:
            has_embeddings = fetch_one(
                "SELECT EXISTS(SELECT 1 FROM company_embedding LIMIT 1) AS has_data"
            )
            if has_embeddings and has_embeddings.get("has_data"):
                emb_rows = fetch_all("""
                    SELECT ce.enterprise_number, ci.name,
                           e.status, e.juridical_form AS "jf_label", ci.city,
                           COALESCE(nl.description, ci.nace_code) AS "sector",
                           e.start_date,
                           fl.revenue, fl.ebitda,
                           CASE WHEN fl.revenue > 0
                                THEN ROUND((fl.ebitda / fl.revenue * 100)::numeric, 1)
                           END AS "ebitda_margin_pct",
                           fl.fte_total, fl.fiscal_year,
                           0.0::float AS score
                    FROM company_embedding ce
                    JOIN enterprise e ON e.enterprise_number = ce.enterprise_number
                    LEFT JOIN company_info ci ON ci.enterprise_number = ce.enterprise_number
                    LEFT JOIN financial_latest fl ON fl.enterprise_number = ce.enterprise_number
                    LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
                    WHERE ce.description ILIKE %s
                    ORDER BY ce.description
                    LIMIT 10
                """, (f"%{query}%",))
        except Exception:
            pass  # embedding table may not exist yet in some environments

        # --- Merge & deduplicate ----------------------------------
        seen = set()
        merged = []
        for row in trgm_rows + emb_rows:
            cbe = row["enterprise_number"]
            if cbe not in seen:
                seen.add(cbe)
                merged.append(row)

        # Drop the internal score column before returning
        for row in merged:
            row.pop("score", None)

        return [_serialize_row(r) for r in merged[:25]]

    except Exception as e:
        logger.exception("Semantic search failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/companies/{cbe}
# ---------------------------------------------------------------------------

@router.get("/{cbe}")
async def get_company_detail(cbe: str):
    """Full company header detail.

    SQL extracted from app/pages/2_company.py load_company_detail() header query.
    """
    cbe = cbe.strip().replace(".", "")

    try:
        # Fast path: try company_info first (170K rows, indexed)
        header = fetch_one("""
            SELECT e.enterprise_number, e.status, e.start_date,
                   e.juridical_form AS "jf_label",
                   COALESCE(ci.name, d.denomination, e.enterprise_number) AS "name",
                   COALESCE(ci.city, a.municipality_nl) AS "city",
                   a.zipcode, a.street_nl AS "street", a.house_number,
                   ci.nace_code,
                   COALESCE(nl.description, ci.nace_code) AS "nace_label",
                   (SELECT value FROM contact WHERE entity_number = e.enterprise_number AND contact_type = 'WEB' LIMIT 1) AS "website"
            FROM enterprise e
            LEFT JOIN company_info ci ON ci.enterprise_number = e.enterprise_number
            LEFT JOIN denomination d ON d.entity_number = e.enterprise_number
                 AND d.type_of_denomination = '001' AND d.language IN ('2','1')
            LEFT JOIN address a ON a.entity_number = e.enterprise_number AND a.type_of_address = 'REGO'
            LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
            WHERE e.enterprise_number = %s LIMIT 1
        """, (cbe,))

        if not header:
            raise HTTPException(status_code=404, detail=f"Company {cbe} not found")

        return _serialize_row(header)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Company detail query failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# POST /api/companies/{cbe}/load
# ---------------------------------------------------------------------------

@router.post("/{cbe}/load")
async def load_company_data(cbe: str, user=Depends(optional_user)):
    """Load financial data from NBB for this company.

    1. Fetch filing references
    2. For each reference (most recent 5), fetch JSON-XBRL filing
    3. Parse rubric codes and values
    4. Insert into financial_data table
    5. Refresh financial_latest and financial_by_year for this company
    """
    import time
    import uuid
    import psycopg2.extras

    cbe = cbe.strip().replace(".", "").zfill(10)

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
    try:
        resp = http_requests.get(
            f"{nbb_base}/authentic/legalEntity/{cbe}/references",
            headers=headers_ref, timeout=15,
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

    # Limit to 5 most recent filings (references come newest-first from NBB)
    refs_to_load = references[:5]

    # --- Step 2-4: Fetch, parse, and insert each filing ---
    conn = get_connection()
    total_rubrics = 0
    filings_loaded = 0
    errors = []

    try:
        cur = conn.cursor()

        for ref in refs_to_load:
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
                total_rubrics += len(rows)
                filings_loaded += 1
                logger.info(
                    "Loaded filing %s for %s: %d rubrics (FY %s)",
                    ref_number, cbe, len(rows), fiscal_year,
                )
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
    cbe = cbe.strip().replace(".", "")

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


# ---------------------------------------------------------------------------
# GET /api/companies/{cbe}/structure
# ---------------------------------------------------------------------------

@router.get("/{cbe}/structure")
async def get_company_structure(cbe: str):
    """Admins, shareholders, participating interests, and Staatsblad publications.

    SQL extracted from app/pages/2_company.py load_company_detail().
    """
    cbe = cbe.strip().replace(".", "")

    try:
        # Only return admins from the most recent filing
        admins = fetch_all("""
            WITH latest AS (
                SELECT MAX(deposit_key) AS dk
                FROM administrator WHERE enterprise_number = %s
            )
            SELECT DISTINCT ON (name, role) name, role, person_type, identifier,
                   mandate_start, mandate_end, representative_name, fiscal_year, deposit_key
            FROM administrator a
            JOIN latest l ON a.deposit_key = l.dk
            WHERE a.enterprise_number = %s
            ORDER BY name, role
        """, (cbe, cbe))

        # Deduplicate participating interests: latest filing per subsidiary
        pis = fetch_all("""
            SELECT DISTINCT ON (name) name, identifier, ownership_pct, country,
                   equity_value, net_result, fiscal_year
            FROM participating_interest
            WHERE enterprise_number = %s
            ORDER BY name, deposit_key DESC
        """, (cbe,))

        # Deduplicate shareholders: latest filing per shareholder
        shareholders = fetch_all("""
            SELECT DISTINCT ON (name) name, identifier, ownership_pct,
                   shareholder_type, shares_held, fiscal_year
            FROM shareholder
            WHERE enterprise_number = %s
            ORDER BY name, deposit_key DESC
        """, (cbe,))
        sb_pubs = fetch_all(
            "SELECT pub_date, pub_type, reference, pdf_url FROM staatsblad_publication "
            "WHERE enterprise_number = %s ORDER BY pub_date DESC",
            (cbe,),
        )

        # Enrich admin rows with role labels
        for admin in admins:
            admin["role_label"] = ROLE_LABELS.get(admin.get("role", ""), admin.get("role", ""))

        return {
            "administrators": [_serialize_row(r) for r in admins],
            "participating_interests": [_serialize_row(r) for r in pis],
            "shareholders": [_serialize_row(r) for r in shareholders],
            "staatsblad_publications": [_serialize_row(r) for r in sb_pubs],
        }
    except Exception as e:
        logger.exception("Company structure query failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/companies/{cbe}/network
# ---------------------------------------------------------------------------

def _fetch_connections(cbes: list) -> tuple:
    """Batch-fetch subsidiaries and shareholders for a set of CBEs.

    SQL extracted from app/pages/2_company.py fetch_connections().
    """
    if not cbes:
        return [], []
    with get_conn() as conn:
        import psycopg2.extras
        ph = ",".join(["%s"] * len(cbes))
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            f"SELECT DISTINCT enterprise_number, name, identifier, ownership_pct, country "
            f"FROM participating_interest WHERE enterprise_number IN ({ph})",
            list(cbes),
        )
        subs = [dict(r) for r in cur.fetchall()]

        cur.execute(
            f"SELECT DISTINCT enterprise_number, name, identifier, ownership_pct, shareholder_type "
            f"FROM shareholder WHERE enterprise_number IN ({ph})",
            list(cbes),
        )
        shs = [dict(r) for r in cur.fetchall()]

        cur.close()
        conn.commit()
        return subs, shs


def _fetch_entity_names(cbes: list) -> dict:
    """Batch-resolve CBE numbers to company names.

    SQL extracted from app/pages/2_company.py fetch_entity_names().
    """
    if not cbes:
        return {}
    with get_conn() as conn:
        ph = ",".join(["%s"] * len(cbes))
        cur = conn.cursor()
        cur.execute(
            f"SELECT entity_number, denomination FROM denomination "
            f"WHERE entity_number IN ({ph}) AND type_of_denomination = '001' "
            f"GROUP BY entity_number, denomination",
            list(cbes),
        )
        rows = cur.fetchall()
        cur.close()
        conn.commit()
        return {r[0]: r[1] for r in rows}


@router.get("/{cbe}/network")
async def get_company_network(cbe: str, max_depth: int = Query(1, ge=1, le=3)):
    """BFS network graph data for the corporate spider-web.

    Logic extracted from app/pages/2_company.py bfs_build_graph().
    Returns nodes and edges in a JSON-friendly format for frontend rendering.
    """
    cbe = cbe.strip().replace(".", "")

    try:
        # Get central company name
        header = fetch_one("""
            SELECT d.denomination AS "name"
            FROM denomination d
            WHERE d.entity_number = %s AND d.type_of_denomination = '001'
            LIMIT 1
        """, (cbe,))
        central_name = header["name"] if header else cbe

        # Get direct relationships
        admins = fetch_all(
            "SELECT * FROM administrator WHERE enterprise_number = %s",
            (cbe,),
        )
        shareholders_rows = fetch_all(
            "SELECT * FROM shareholder WHERE enterprise_number = %s",
            (cbe,),
        )
        pis_rows = fetch_all(
            "SELECT * FROM participating_interest WHERE enterprise_number = %s",
            (cbe,),
        )

        # Build graph via BFS
        nodes = []
        edges = []
        visited = {cbe}
        nav_options = {}
        truncated = False

        # Central node
        nodes.append({
            "id": cbe,
            "label": central_name,
            "type": "central",
            "size": 35,
            "color": "#6366f1",
            "cbe": cbe,
            "depth": 0,
        })

        frontier = set()

        # Shareholders at depth 0
        seen_sh_names = set()
        for i, sh in enumerate(shareholders_rows):
            sname = sh.get("name") or "Unknown"
            if sname in seen_sh_names:
                continue
            seen_sh_names.add(sname)

            cbe_clean = _clean_cbe(sh.get("identifier"))
            is_indiv = sh.get("shareholder_type") == "individual"
            pct = sh.get("ownership_pct")
            nid = cbe_clean if cbe_clean else f"sh_{i}"

            node_size = max(14, min(28, int(18 + (float(pct) if pct else 0) / 10))) if not is_indiv else 14

            nodes.append({
                "id": nid,
                "label": sname,
                "type": "shareholder",
                "subtype": "individual" if is_indiv else "company",
                "size": node_size,
                "color": "#86efac" if is_indiv else "#22c55e",
                "cbe": cbe_clean,
                "depth": 1,
                "ownership_pct": float(pct) if pct else None,
            })
            edges.append({
                "source": nid,
                "target": cbe,
                "type": "shareholder",
                "label": f"{pct:.0f}%" if pct else "",
                "color": "#22c55e",
                "dash": "dash",
            })

            if cbe_clean and cbe_clean not in visited:
                frontier.add(cbe_clean)
                nav_options[cbe_clean] = sname

        # Subsidiaries at depth 0
        seen_pi_names = set()
        for i, pi in enumerate(pis_rows):
            pname = pi.get("name") or "Unknown"
            if pname in seen_pi_names:
                continue
            seen_pi_names.add(pname)

            cbe_clean = _clean_cbe(pi.get("identifier"))
            pct = pi.get("ownership_pct")
            country = pi.get("country") or ""
            nid = cbe_clean if cbe_clean else f"pi_{i}"

            node_size = max(14, min(28, int(18 + (float(pct) if pct else 0) / 10)))

            nodes.append({
                "id": nid,
                "label": pname,
                "type": "subsidiary",
                "size": node_size,
                "color": "#f97316",
                "cbe": cbe_clean,
                "depth": 1,
                "ownership_pct": float(pct) if pct else None,
                "country": country,
            })
            edges.append({
                "source": cbe,
                "target": nid,
                "type": "subsidiary",
                "label": f"{pct:.0f}%" if pct else "",
                "color": "#f97316",
                "dash": "solid",
            })

            if cbe_clean and cbe_clean not in visited:
                frontier.add(cbe_clean)
                nav_options[cbe_clean] = pname

        # Admins at depth 0
        seen_admin_names = set()
        for i, ad in enumerate(admins):
            aname = ad.get("name") or "Unknown"
            role_key = ad.get("role", "")
            name_role = f"{aname}_{role_key}"
            if name_role in seen_admin_names:
                continue
            seen_admin_names.add(name_role)

            role = ROLE_LABELS.get(role_key, role_key or "Administrator")
            cbe_clean = _clean_cbe(ad.get("identifier"))
            is_legal = ad.get("person_type") == "legal"
            nid = cbe_clean if cbe_clean else f"ad_{i}"

            existing = [n for n in nodes if n["id"] == nid]
            if not existing:
                nodes.append({
                    "id": nid,
                    "label": aname,
                    "type": "admin",
                    "subtype": "legal" if is_legal else "natural",
                    "size": 14 if is_legal else 12,
                    "color": "#06b6d4" if is_legal else "#94a3b8",
                    "cbe": cbe_clean,
                    "depth": 1,
                })
            edges.append({
                "source": nid,
                "target": cbe,
                "type": "admin",
                "label": role,
                "color": "#94a3b8",
                "dash": "dot",
            })

            if cbe_clean:
                nav_options[cbe_clean] = aname

        visited.update(frontier)

        # BFS expansion for deeper levels
        queue = deque(frontier)
        current_depth = 1

        while queue and current_depth < max_depth:
            batch_cbes = set()
            while queue:
                batch_cbes.add(queue.popleft())

            if not batch_cbes or len(nodes) >= MAX_NETWORK_NODES:
                if len(nodes) >= MAX_NETWORK_NODES:
                    truncated = True
                break

            sub_recs, sh_recs = _fetch_connections(list(sorted(batch_cbes)))

            new_cbes = set()
            for rec in sub_recs + sh_recs:
                c = _clean_cbe(rec.get("identifier"))
                if c and c not in {n["id"] for n in nodes}:
                    new_cbes.add(c)
            name_map = _fetch_entity_names(list(sorted(new_cbes))) if new_cbes else {}

            d = current_depth + 1
            next_frontier = set()

            # Shareholders of expanded entities
            seen_edges = set()
            for rec in sh_recs:
                source_cbe = rec["enterprise_number"]
                target_cbe = _clean_cbe(rec.get("identifier"))
                sname = rec.get("name") or "Unknown"
                pct = rec.get("ownership_pct")

                nid = target_cbe if target_cbe else f"sh_d{d}_{sname[:10]}"
                edge_key = (nid, source_cbe)
                if edge_key in seen_edges:
                    continue
                seen_edges.add(edge_key)

                if len(nodes) >= MAX_NETWORK_NODES:
                    truncated = True
                    break

                existing = [n for n in nodes if n["id"] == nid]
                if not existing:
                    label = name_map.get(target_cbe, sname) if target_cbe else sname
                    nodes.append({
                        "id": nid,
                        "label": label,
                        "type": "shareholder",
                        "size": max(8, 14 - d * 3),
                        "color": "#bbf7d0",
                        "cbe": target_cbe,
                        "depth": d,
                        "ownership_pct": float(pct) if pct else None,
                    })
                    if target_cbe:
                        nav_options[target_cbe] = label

                edges.append({
                    "source": nid,
                    "target": source_cbe,
                    "type": "shareholder",
                    "label": f"{pct:.0f}%" if pct else "",
                    "color": "#bbf7d0",
                    "dash": "dash",
                })

                if target_cbe and target_cbe not in visited:
                    next_frontier.add(target_cbe)

            # Subsidiaries of expanded entities
            seen_edges = set()
            for rec in sub_recs:
                source_cbe = rec["enterprise_number"]
                target_cbe = _clean_cbe(rec.get("identifier"))
                pname = rec.get("name") or "Unknown"
                pct = rec.get("ownership_pct")
                country = rec.get("country") or ""

                nid = target_cbe if target_cbe else f"pi_d{d}_{pname[:10]}"
                edge_key = (source_cbe, nid)
                if edge_key in seen_edges:
                    continue
                seen_edges.add(edge_key)

                if len(nodes) >= MAX_NETWORK_NODES:
                    truncated = True
                    break

                existing = [n for n in nodes if n["id"] == nid]
                if not existing:
                    label = name_map.get(target_cbe, pname) if target_cbe else pname
                    nodes.append({
                        "id": nid,
                        "label": label,
                        "type": "subsidiary",
                        "size": max(8, 14 - d * 3),
                        "color": "#fed7aa",
                        "cbe": target_cbe,
                        "depth": d,
                        "ownership_pct": float(pct) if pct else None,
                        "country": country,
                    })
                    if target_cbe:
                        nav_options[target_cbe] = label

                edges.append({
                    "source": source_cbe,
                    "target": nid,
                    "type": "subsidiary",
                    "label": f"{pct:.0f}%" if pct else "",
                    "color": "#fed7aa",
                    "dash": "solid",
                })

                if target_cbe and target_cbe not in visited:
                    next_frontier.add(target_cbe)

            visited.update(next_frontier)
            for c in next_frontier:
                queue.append(c)
            current_depth += 1

        return {
            "nodes": nodes,
            "edges": edges,
            "nav_options": nav_options,
            "truncated": truncated,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Company network query failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ── Sector Benchmarking ──────────────────────────────────────────

@router.get("/{cbe}/sector-benchmark")
async def sector_benchmark(cbe: str):
    """Return percentile rankings for a company within its NACE sector (single batched query)."""
    cbe = cbe.strip().replace(".", "").zfill(10)

    try:
        info = fetch_one(
            "SELECT nace_code FROM company_info WHERE enterprise_number = %s", (cbe,),
        )
        if not info or not info.get("nace_code"):
            return {"error": "no_nace", "benchmarks": []}

        nace = info["nace_code"]

        # Single query: get company values + all percentiles in one shot
        row = fetch_one("""
            WITH company AS (
                SELECT revenue, ebitda, net_profit, equity, total_assets, fte_total, fiscal_year,
                       CASE WHEN revenue > 0 THEN ebitda / revenue * 100 END AS ebitda_margin,
                       CASE WHEN total_assets > 0 THEN equity / total_assets * 100 END AS equity_ratio
                FROM financial_latest WHERE enterprise_number = %s
            ),
            peers AS (
                SELECT fl.*,
                       CASE WHEN fl.revenue > 0 THEN fl.ebitda / fl.revenue * 100 END AS ebitda_margin,
                       CASE WHEN fl.total_assets > 0 THEN fl.equity / fl.total_assets * 100 END AS equity_ratio
                FROM financial_latest fl
                JOIN company_info ci ON ci.enterprise_number = fl.enterprise_number
                WHERE ci.nace_code = %s
            )
            SELECT
                (SELECT COUNT(*) FROM peers WHERE revenue IS NOT NULL) AS peer_count,
                c.fiscal_year, c.revenue, c.ebitda, c.net_profit, c.equity, c.total_assets, c.fte_total,
                c.ebitda_margin, c.equity_ratio,
                -- Revenue
                (SELECT COUNT(*) FROM peers WHERE revenue < c.revenue AND revenue IS NOT NULL) AS rev_below,
                (SELECT COUNT(*) FROM peers WHERE revenue IS NOT NULL) AS rev_total,
                (SELECT PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY revenue) FROM peers WHERE revenue IS NOT NULL) AS rev_p25,
                (SELECT PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY revenue) FROM peers WHERE revenue IS NOT NULL) AS rev_med,
                (SELECT PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY revenue) FROM peers WHERE revenue IS NOT NULL) AS rev_p75,
                -- EBITDA
                (SELECT COUNT(*) FROM peers WHERE ebitda < c.ebitda AND ebitda IS NOT NULL) AS ebitda_below,
                (SELECT COUNT(*) FROM peers WHERE ebitda IS NOT NULL) AS ebitda_total,
                (SELECT PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY ebitda) FROM peers WHERE ebitda IS NOT NULL) AS ebitda_p25,
                (SELECT PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY ebitda) FROM peers WHERE ebitda IS NOT NULL) AS ebitda_med,
                (SELECT PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY ebitda) FROM peers WHERE ebitda IS NOT NULL) AS ebitda_p75,
                -- Net Profit
                (SELECT COUNT(*) FROM peers WHERE net_profit < c.net_profit AND net_profit IS NOT NULL) AS np_below,
                (SELECT COUNT(*) FROM peers WHERE net_profit IS NOT NULL) AS np_total,
                (SELECT PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY net_profit) FROM peers WHERE net_profit IS NOT NULL) AS np_med,
                -- FTE
                (SELECT COUNT(*) FROM peers WHERE fte_total < c.fte_total AND fte_total IS NOT NULL) AS fte_below,
                (SELECT COUNT(*) FROM peers WHERE fte_total IS NOT NULL) AS fte_total_cnt,
                (SELECT PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY fte_total) FROM peers WHERE fte_total IS NOT NULL) AS fte_med,
                -- Total Assets
                (SELECT COUNT(*) FROM peers WHERE total_assets < c.total_assets AND total_assets IS NOT NULL) AS ta_below,
                (SELECT COUNT(*) FROM peers WHERE total_assets IS NOT NULL) AS ta_total,
                (SELECT PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY total_assets) FROM peers WHERE total_assets IS NOT NULL) AS ta_med,
                -- EBITDA Margin
                (SELECT COUNT(*) FROM peers WHERE ebitda_margin < c.ebitda_margin AND ebitda_margin IS NOT NULL) AS em_below,
                (SELECT COUNT(*) FROM peers WHERE ebitda_margin IS NOT NULL) AS em_total,
                (SELECT PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY ebitda_margin) FROM peers WHERE ebitda_margin IS NOT NULL) AS em_med,
                -- Equity Ratio
                (SELECT COUNT(*) FROM peers WHERE equity_ratio < c.equity_ratio AND equity_ratio IS NOT NULL) AS er_below,
                (SELECT COUNT(*) FROM peers WHERE equity_ratio IS NOT NULL) AS er_total,
                (SELECT PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY equity_ratio) FROM peers WHERE equity_ratio IS NOT NULL) AS er_med
            FROM company c
        """, (cbe, nace))

        if not row or not row.get("fiscal_year"):
            return {"error": "no_financials", "benchmarks": []}

        nace_label = fetch_one("SELECT description FROM nace_lookup WHERE nace_code = %s", (nace,))

        def pct(below, total):
            return round((below / total) * 100, 1) if total and total > 0 else None

        def fv(v):
            return float(v) if v is not None else None

        benchmarks = []
        defs = [
            ("Revenue", "eur", "revenue", "rev_below", "rev_total", "rev_p25", "rev_med", "rev_p75"),
            ("EBITDA", "eur", "ebitda", "ebitda_below", "ebitda_total", "ebitda_p25", "ebitda_med", "ebitda_p75"),
            ("Net Profit", "eur", "net_profit", "np_below", "np_total", None, "np_med", None),
            ("FTE", "num", "fte_total", "fte_below", "fte_total_cnt", None, "fte_med", None),
            ("Total Assets", "eur", "total_assets", "ta_below", "ta_total", None, "ta_med", None),
            ("EBITDA Margin", "pct", "ebitda_margin", "em_below", "em_total", None, "em_med", None),
            ("Equity Ratio", "pct", "equity_ratio", "er_below", "er_total", None, "er_med", None),
        ]
        for label, fmt, val_key, below_key, total_key, p25_key, med_key, p75_key in defs:
            val = row.get(val_key)
            total = row.get(total_key)
            if val is None or not total:
                continue
            benchmarks.append({
                "metric": label, "format": fmt,
                "value": fv(val),
                "percentile": pct(row.get(below_key, 0), total),
                "p25": fv(row.get(p25_key)) if p25_key else None,
                "median": fv(row.get(med_key)) if med_key else None,
                "p75": fv(row.get(p75_key)) if p75_key else None,
                "peer_count": total,
            })

        return {
            "nace_code": nace,
            "nace_label": nace_label["description"] if nace_label else nace,
            "fiscal_year": row["fiscal_year"],
            "peer_count": row.get("peer_count", 0),
            "benchmarks": benchmarks,
        }
    except Exception as e:
        logger.exception("Sector benchmark failed for %s", cbe)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/companies/{cbe}/similar
# ---------------------------------------------------------------------------

@router.get("/{cbe}/similar")
async def get_similar_companies(cbe: str):
    """Find up to 10 companies in the same NACE sector with closest revenue."""
    cbe = cbe.strip().replace(".", "")

    try:
        # Get the target company's NACE code and latest revenue
        target = fetch_one("""
            SELECT ci.nace_code, fl.revenue
            FROM company_info ci
            LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
            WHERE ci.enterprise_number = %s
        """, (cbe,))

        if not target:
            raise HTTPException(status_code=404, detail=f"Company {cbe} not found")

        nace = target.get("nace_code")
        revenue = target.get("revenue")

        if not nace:
            return []

        if revenue and revenue > 0:
            # Find companies in same sector with revenue within 0.5x to 2x
            rev_min = float(revenue) * 0.5
            rev_max = float(revenue) * 2.0
            rows = fetch_all("""
                SELECT ci.enterprise_number, ci.name, ci.city,
                       fl.revenue, fl.ebitda, fl.fte_total, fl.fiscal_year
                FROM company_info ci
                JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
                WHERE ci.nace_code = %s
                  AND ci.enterprise_number != %s
                  AND fl.revenue IS NOT NULL
                  AND fl.revenue BETWEEN %s AND %s
                ORDER BY ABS(fl.revenue - %s)
                LIMIT 10
            """, (nace, cbe, rev_min, rev_max, float(revenue)))
        else:
            # No revenue data — just return companies in the same sector
            rows = fetch_all("""
                SELECT ci.enterprise_number, ci.name, ci.city,
                       fl.revenue, fl.ebitda, fl.fte_total, fl.fiscal_year
                FROM company_info ci
                LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
                WHERE ci.nace_code = %s
                  AND ci.enterprise_number != %s
                ORDER BY fl.revenue DESC NULLS LAST
                LIMIT 10
            """, (nace, cbe))

        return [_serialize_row(r) for r in rows]
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Similar companies failed for %s", cbe)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/companies/{cbe}/deep-network?depth=3
# ---------------------------------------------------------------------------

MAX_DEEP_NETWORK_NODES = 100


@router.get("/{cbe}/deep-network")
async def get_deep_network(cbe: str, depth: int = Query(3, ge=1, le=4)):
    """Deep corporate network graph — traverse administrator, shareholder,
    and participating_interest links up to 4 hops to find hidden connections.

    Uses BFS with batched queries at each depth level.  Nodes are companies
    and people; edges carry the relationship type and a human-readable label.
    Total nodes are capped at MAX_DEEP_NETWORK_NODES to prevent explosion.
    """
    cbe = cbe.strip().replace(".", "").zfill(10)

    try:
        # Resolve the starting company name
        header = fetch_one(
            "SELECT denomination AS name FROM denomination "
            "WHERE entity_number = %s AND type_of_denomination = '001' LIMIT 1",
            (cbe,),
        )
        if not header:
            raise HTTPException(status_code=404, detail=f"Company {cbe} not found")

        nodes: list[dict] = []
        edges: list[dict] = []
        node_ids: set[str] = set()
        truncated = False

        def _add_node(nid: str, name: str, ntype: str, d: int) -> bool:
            """Add a node if not already present. Returns True if added."""
            nonlocal truncated
            if nid in node_ids:
                return False
            if len(nodes) >= MAX_DEEP_NETWORK_NODES:
                truncated = True
                return False
            node_ids.add(nid)
            nodes.append({"id": nid, "name": name, "type": ntype, "depth": d})
            return True

        def _add_edge(src: str, tgt: str, rel: str, label: str):
            """Add an edge (duplicates possible between same pair via different rels)."""
            edges.append({
                "source": src, "target": tgt,
                "relationship": rel, "label": label,
            })

        # Seed node
        _add_node(cbe, header["name"], "company", 0)

        # BFS frontier — set of CBE numbers to expand at the next depth
        frontier: set[str] = {cbe}

        for current_depth in range(1, depth + 1):
            if not frontier or len(nodes) >= MAX_DEEP_NETWORK_NODES:
                break

            batch = list(sorted(frontier))
            frontier = set()

            # ── Fetch all relationships for the current batch ──────────
            ph = ",".join(["%s"] * len(batch))

            # 1. Administrators OF these companies
            admin_rows = fetch_all(
                f"SELECT DISTINCT enterprise_number, name, role, person_type, identifier "
                f"FROM administrator WHERE enterprise_number IN ({ph})",
                batch,
            )

            # 2. Companies where these entities serve as administrator (reverse)
            admin_reverse_rows = fetch_all(
                f"SELECT DISTINCT enterprise_number, name, role, person_type, identifier "
                f"FROM administrator WHERE identifier IN ({ph})",
                batch,
            )

            # 3. Shareholders OF these companies
            sh_rows = fetch_all(
                f"SELECT DISTINCT enterprise_number, name, identifier, ownership_pct, shareholder_type "
                f"FROM shareholder WHERE enterprise_number IN ({ph})",
                batch,
            )

            # 4. Companies where these entities are shareholders (reverse)
            sh_reverse_rows = fetch_all(
                f"SELECT DISTINCT enterprise_number, name, identifier, ownership_pct, shareholder_type "
                f"FROM shareholder WHERE identifier IN ({ph})",
                batch,
            )

            # 5. Participating interests (subsidiaries) OF these companies
            pi_rows = fetch_all(
                f"SELECT DISTINCT enterprise_number, name, identifier, ownership_pct, country "
                f"FROM participating_interest WHERE enterprise_number IN ({ph})",
                batch,
            )

            # 6. Companies that hold participating interests IN these entities (parent lookup)
            pi_reverse_rows = fetch_all(
                f"SELECT DISTINCT enterprise_number, name, identifier, ownership_pct, country "
                f"FROM participating_interest WHERE identifier IN ({ph})",
                batch,
            )

            # Collect all new CBE numbers we discover so we can batch-resolve names
            new_cbes: set[str] = set()

            def _collect_cbe(identifier) -> str | None:
                c = _clean_cbe(identifier)
                if c and c not in node_ids:
                    new_cbes.add(c)
                return c

            # Scan all rows for new CBEs before adding nodes
            for row in admin_rows:
                _collect_cbe(row.get("identifier"))
            for row in admin_reverse_rows:
                _collect_cbe(row.get("enterprise_number"))
            for row in sh_rows:
                _collect_cbe(row.get("identifier"))
            for row in sh_reverse_rows:
                _collect_cbe(row.get("enterprise_number"))
            for row in pi_rows:
                _collect_cbe(row.get("identifier"))
            for row in pi_reverse_rows:
                _collect_cbe(row.get("enterprise_number"))

            # Batch-resolve names for all new CBEs
            name_map = _fetch_entity_names(list(sorted(new_cbes))) if new_cbes else {}

            # ── Process administrators (forward: company -> admin) ──────
            seen_admin = set()
            for row in admin_rows:
                ent = row["enterprise_number"]
                aname = row.get("name") or "Unknown"
                role_key = row.get("role") or ""
                is_legal = row.get("person_type") == "legal"
                cbe_id = _clean_cbe(row.get("identifier"))
                nid = cbe_id if cbe_id else f"person:{aname}"
                ntype = "company" if is_legal and cbe_id else "person"
                edge_key = (nid, ent, "administrator", role_key)
                if edge_key in seen_admin:
                    continue
                seen_admin.add(edge_key)

                label_name = name_map.get(cbe_id, aname) if cbe_id else aname
                role_label = ROLE_LABELS.get(role_key, role_key or "Administrator")
                added = _add_node(nid, label_name, ntype, current_depth)
                _add_edge(nid, ent, "administrator", role_label)

                if cbe_id and added:
                    frontier.add(cbe_id)

            # ── Process administrators (reverse: admin -> other companies) ──
            seen_admin_rev = set()
            for row in admin_reverse_rows:
                target_ent = row["enterprise_number"]
                identifier = row.get("identifier")
                cbe_id = _clean_cbe(identifier)
                if not cbe_id or cbe_id not in node_ids:
                    continue  # only expand from known nodes
                role_key = row.get("role") or ""
                edge_key = (cbe_id, target_ent, "administrator_reverse", role_key)
                if edge_key in seen_admin_rev:
                    continue
                seen_admin_rev.add(edge_key)

                target_name = name_map.get(target_ent, row.get("name") or target_ent)
                role_label = ROLE_LABELS.get(role_key, role_key or "Administrator")
                added = _add_node(target_ent, target_name, "company", current_depth)
                _add_edge(cbe_id, target_ent, "administrator", role_label)
                if added:
                    frontier.add(target_ent)

            # ── Process shareholders (forward: company -> shareholder) ──
            seen_sh = set()
            for row in sh_rows:
                ent = row["enterprise_number"]
                sname = row.get("name") or "Unknown"
                cbe_id = _clean_cbe(row.get("identifier"))
                pct = row.get("ownership_pct")
                is_indiv = row.get("shareholder_type") == "individual"
                nid = cbe_id if cbe_id else f"person:{sname}"
                ntype = "company" if cbe_id else "person"
                edge_key = (nid, ent, "shareholder")
                if edge_key in seen_sh:
                    continue
                seen_sh.add(edge_key)

                label_name = name_map.get(cbe_id, sname) if cbe_id else sname
                pct_label = f"{pct:.0f}%" if pct else ""
                added = _add_node(nid, label_name, ntype, current_depth)
                _add_edge(nid, ent, "shareholder", pct_label)
                if cbe_id and added:
                    frontier.add(cbe_id)

            # ── Process shareholders (reverse: entity holds shares elsewhere) ──
            seen_sh_rev = set()
            for row in sh_reverse_rows:
                target_ent = row["enterprise_number"]
                cbe_id = _clean_cbe(row.get("identifier"))
                if not cbe_id or cbe_id not in node_ids:
                    continue
                pct = row.get("ownership_pct")
                edge_key = (cbe_id, target_ent, "shareholder_reverse")
                if edge_key in seen_sh_rev:
                    continue
                seen_sh_rev.add(edge_key)

                target_name = name_map.get(target_ent, row.get("name") or target_ent)
                pct_label = f"{pct:.0f}%" if pct else ""
                added = _add_node(target_ent, target_name, "company", current_depth)
                _add_edge(cbe_id, target_ent, "shareholder", pct_label)
                if added:
                    frontier.add(target_ent)

            # ── Process participating interests (forward: company -> subsidiary) ──
            seen_pi = set()
            for row in pi_rows:
                ent = row["enterprise_number"]
                pname = row.get("name") or "Unknown"
                cbe_id = _clean_cbe(row.get("identifier"))
                pct = row.get("ownership_pct")
                nid = cbe_id if cbe_id else f"sub:{pname}"
                ntype = "company" if cbe_id else "subsidiary"
                edge_key = (ent, nid, "participating_interest")
                if edge_key in seen_pi:
                    continue
                seen_pi.add(edge_key)

                label_name = name_map.get(cbe_id, pname) if cbe_id else pname
                pct_label = f"{pct:.0f}%" if pct else ""
                added = _add_node(nid, label_name, ntype, current_depth)
                _add_edge(ent, nid, "participating_interest", pct_label)
                if cbe_id and added:
                    frontier.add(cbe_id)

            # ── Process participating interests (reverse: parent companies) ──
            seen_pi_rev = set()
            for row in pi_reverse_rows:
                parent_ent = row["enterprise_number"]
                cbe_id = _clean_cbe(row.get("identifier"))
                if not cbe_id or cbe_id not in node_ids:
                    continue
                pct = row.get("ownership_pct")
                edge_key = (parent_ent, cbe_id, "participating_interest_reverse")
                if edge_key in seen_pi_rev:
                    continue
                seen_pi_rev.add(edge_key)

                parent_name = name_map.get(parent_ent, row.get("name") or parent_ent)
                pct_label = f"{pct:.0f}%" if pct else ""
                added = _add_node(parent_ent, parent_name, "company", current_depth)
                _add_edge(parent_ent, cbe_id, "participating_interest", pct_label)
                if added:
                    frontier.add(parent_ent)

            # Only expand CBEs that were actually added as nodes
            frontier = {c for c in frontier if c in node_ids} - set(batch)

        return {
            "nodes": nodes,
            "edges": edges,
            "truncated": truncated,
            "depth_reached": min(depth, max((n["depth"] for n in nodes), default=0)),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Deep network query failed for %s", cbe)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# AI Enrichment — company profile summaries via OpenRouter
# ---------------------------------------------------------------------------

_enrichment_table_ensured = False


def _ensure_enrichment_table():
    """Create enrichment table if it does not exist (idempotent)."""
    global _enrichment_table_ensured
    if _enrichment_table_ensured:
        return
    execute("""
        CREATE TABLE IF NOT EXISTS company_enrichment (
            enterprise_number VARCHAR(10) PRIMARY KEY,
            summary TEXT,
            generated_at TIMESTAMP DEFAULT NOW()
        )
    """)
    # Add website/LinkedIn scraping columns (idempotent)
    for col in ("website_summary", "linkedin_summary", "website_url"):
        try:
            execute(f"""
                ALTER TABLE company_enrichment ADD COLUMN IF NOT EXISTS {col} TEXT
            """)
        except Exception:
            pass  # column already exists or DB doesn't support IF NOT EXISTS
    _enrichment_table_ensured = True


@router.post("/{cbe}/enrich")
async def enrich_company(cbe: str, user=Depends(get_current_user)):
    """Generate an AI company profile summary via OpenRouter.

    Gathers existing company data (name, sector, city, financials) and asks
    the LLM to write a concise 2-3 sentence company profile.
    """
    _ensure_enrichment_table()

    cbe = cbe.strip().replace(".", "").zfill(10)

    # Gather company data for the prompt
    company = fetch_one("""
        SELECT ci.name, ci.city, ci.nace_code,
               COALESCE(nl.description, ci.nace_code) AS sector,
               fl.revenue, fl.ebitda, fl.fte_total, fl.fiscal_year
        FROM company_info ci
        LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
        LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
        WHERE ci.enterprise_number = %s
    """, (cbe,))

    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    # Build the prompt from available data
    parts = []
    if company.get("name"):
        parts.append(f"Company: {company['name']}")
    if company.get("sector"):
        parts.append(f"Sector: {company['sector']}")
    if company.get("city"):
        parts.append(f"Location: {company['city']}, Belgium")
    if company.get("revenue"):
        parts.append(f"Revenue: EUR {company['revenue']:,.0f}")
    if company.get("ebitda"):
        parts.append(f"EBITDA: EUR {company['ebitda']:,.0f}")
    if company.get("fte_total"):
        parts.append(f"FTE: {company['fte_total']:,.0f}")
    if company.get("fiscal_year"):
        parts.append(f"Fiscal year: {company['fiscal_year']}")

    if not parts:
        raise HTTPException(
            status_code=422, detail="Not enough data to generate a profile"
        )

    prompt = (
        "Based on the following data about a Belgian company, write a concise "
        "2-3 sentence company profile summary suitable for an investor audience. "
        "Be factual, do not speculate.\n\n"
        + "\n".join(parts)
    )

    system = (
        "You are a financial analyst assistant. Write concise, professional "
        "company summaries for private equity deal sourcing."
    )

    summary = await ai_complete(prompt, system=system)

    if not summary:
        raise HTTPException(
            status_code=503,
            detail="AI service unavailable — check OPENROUTER_API_KEY",
        )

    # Store (upsert) the enrichment
    execute("""
        INSERT INTO company_enrichment (enterprise_number, summary, generated_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT (enterprise_number)
        DO UPDATE SET summary = EXCLUDED.summary, generated_at = NOW()
    """, (cbe, summary))

    return {"summary": summary}


@router.get("/{cbe}/enrichment")
async def get_enrichment(cbe: str, user=Depends(optional_user)):
    """Fetch existing AI-generated enrichment for a company."""
    _ensure_enrichment_table()

    cbe = cbe.strip().replace(".", "").zfill(10)

    row = fetch_one("""
        SELECT summary, generated_at, website_summary, linkedin_summary, website_url
        FROM company_enrichment
        WHERE enterprise_number = %s
    """, (cbe,))

    if not row:
        return None

    return _serialize_row(row)


# ---------------------------------------------------------------------------
# POST /api/companies/{cbe}/scrape-website
# ---------------------------------------------------------------------------

@router.post("/{cbe}/scrape-website")
async def scrape_company_website(cbe: str, user=Depends(get_current_user)):
    """Scrape company website via Zenrows and extract structured data with AI.

    Looks up the company website from the contact table (contact_type='WEB'),
    scrapes it, then uses AI to extract a description, products/services,
    employee mentions, and key people.
    """
    from scraper import scrape_url, _strip_html

    _ensure_enrichment_table()
    cbe = cbe.strip().replace(".", "").zfill(10)

    # 1. Find the company's website
    row = fetch_one("""
        SELECT value FROM contact
        WHERE entity_number = %s AND contact_type = 'WEB'
        LIMIT 1
    """, (cbe,))

    if not row or not row.get("value"):
        raise HTTPException(status_code=404, detail="No website found for this company")

    website_url = row["value"].strip()
    # Ensure URL has a scheme
    if not website_url.startswith("http"):
        website_url = "https://" + website_url

    # 2. Scrape the website
    html = await scrape_url(website_url)
    if not html:
        raise HTTPException(
            status_code=502,
            detail="Could not scrape the website — check ZENROWS_API_KEY or try again later",
        )

    # 3. Extract text from HTML
    page_text = _strip_html(html)
    if len(page_text) < 50:
        raise HTTPException(status_code=422, detail="Website returned too little content to analyse")

    # 4. AI extraction
    prompt = (
        "Analyse the following text scraped from a Belgian company's website. "
        "Extract and return a JSON object with these fields:\n"
        '- "summary": A concise 2-3 sentence company description\n'
        '- "products": A comma-separated list of main products or services\n'
        '- "employees": Any mentioned number of employees, or "unknown"\n'
        '- "key_people": Names and roles of key people mentioned, or "none found"\n\n'
        "Return ONLY valid JSON, no markdown fences.\n\n"
        f"Website text:\n{page_text}"
    )

    system = (
        "You are a data extraction assistant. Return only valid JSON. "
        "Be concise and factual. If information is not available, use sensible defaults."
    )

    ai_response = await ai_complete(prompt, system=system)
    if not ai_response:
        raise HTTPException(status_code=503, detail="AI service unavailable")

    # 5. Try to parse AI response as JSON, fall back to raw text
    import json
    try:
        extracted = json.loads(ai_response.strip())
    except json.JSONDecodeError:
        # AI didn't return clean JSON — wrap the raw text
        extracted = {
            "summary": ai_response.strip(),
            "products": "unknown",
            "employees": "unknown",
            "key_people": "none found",
        }

    # 6. Store in company_enrichment
    website_summary = json.dumps(extracted, ensure_ascii=False)
    execute("""
        INSERT INTO company_enrichment (enterprise_number, website_summary, website_url, generated_at)
        VALUES (%s, %s, %s, NOW())
        ON CONFLICT (enterprise_number)
        DO UPDATE SET website_summary = EXCLUDED.website_summary,
                      website_url = EXCLUDED.website_url,
                      generated_at = NOW()
    """, (cbe, website_summary, website_url))

    return {
        "summary": extracted.get("summary", ""),
        "products": extracted.get("products", ""),
        "employees": extracted.get("employees", "unknown"),
        "key_people": extracted.get("key_people", "none found"),
        "website_url": website_url,
    }


# ---------------------------------------------------------------------------
# POST /api/companies/{cbe}/scrape-linkedin
# ---------------------------------------------------------------------------

@router.post("/{cbe}/scrape-linkedin")
async def scrape_company_linkedin(cbe: str, user=Depends(get_current_user)):
    """Scrape company LinkedIn profile via Zenrows and extract data with AI.

    Constructs a LinkedIn company URL from the company name, scrapes it
    with JS rendering and premium proxies, then uses AI to extract
    description, employee count, industry, and specialties.
    """
    from scraper import scrape_url, _strip_html, slugify_company_name

    _ensure_enrichment_table()
    cbe = cbe.strip().replace(".", "").zfill(10)

    # 1. Get company name to build LinkedIn URL
    company = fetch_one("""
        SELECT COALESCE(ci.name, d.denomination) AS name
        FROM enterprise e
        LEFT JOIN company_info ci ON ci.enterprise_number = e.enterprise_number
        LEFT JOIN denomination d ON d.entity_number = e.enterprise_number
             AND d.type_of_denomination = '001' AND d.language IN ('2','1')
        WHERE e.enterprise_number = %s
        LIMIT 1
    """, (cbe,))

    if not company or not company.get("name"):
        raise HTTPException(status_code=404, detail="Company not found")

    company_name = company["name"]
    slug = slugify_company_name(company_name)
    linkedin_url = f"https://www.linkedin.com/company/{slug}"

    # 2. Scrape LinkedIn (requires JS rendering + premium proxy)
    html = await scrape_url(linkedin_url, js_render=True, premium_proxy=True)
    if not html:
        raise HTTPException(
            status_code=502,
            detail="Could not scrape LinkedIn — check ZENROWS_API_KEY or try again later",
        )

    # 3. Extract text from HTML
    page_text = _strip_html(html)
    if len(page_text) < 50:
        raise HTTPException(
            status_code=422,
            detail="LinkedIn page returned too little content — the company page may not exist",
        )

    # 4. AI extraction
    prompt = (
        "Analyse the following text scraped from a LinkedIn company page. "
        "Extract and return a JSON object with these fields:\n"
        '- "summary": A concise 2-3 sentence company description\n'
        '- "employee_count": Number of employees listed, or "unknown"\n'
        '- "industry": The industry listed on the page, or "unknown"\n'
        '- "specialties": A comma-separated list of specialties, or "none found"\n\n'
        "Return ONLY valid JSON, no markdown fences.\n\n"
        f"LinkedIn page text:\n{page_text}"
    )

    system = (
        "You are a data extraction assistant. Return only valid JSON. "
        "Be concise and factual. If information is not available, use sensible defaults."
    )

    ai_response = await ai_complete(prompt, system=system)
    if not ai_response:
        raise HTTPException(status_code=503, detail="AI service unavailable")

    # 5. Try to parse AI response as JSON
    import json
    try:
        extracted = json.loads(ai_response.strip())
    except json.JSONDecodeError:
        extracted = {
            "summary": ai_response.strip(),
            "employee_count": "unknown",
            "industry": "unknown",
            "specialties": "none found",
        }

    # 6. Store in company_enrichment
    linkedin_summary = json.dumps(extracted, ensure_ascii=False)
    execute("""
        INSERT INTO company_enrichment (enterprise_number, linkedin_summary, generated_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT (enterprise_number)
        DO UPDATE SET linkedin_summary = EXCLUDED.linkedin_summary,
                      generated_at = NOW()
    """, (cbe, linkedin_summary))

    return {
        "summary": extracted.get("summary", ""),
        "employee_count": extracted.get("employee_count", "unknown"),
        "industry": extracted.get("industry", "unknown"),
        "specialties": extracted.get("specialties", "none found"),
        "linkedin_url": linkedin_url,
    }
