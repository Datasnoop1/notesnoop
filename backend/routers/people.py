"""People router — search administrators and shareholders by name."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from db import fetch_all, fetch_one, execute, get_conn
from auth import get_current_user, optional_user
from ai_client import ai_complete

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/people", tags=["people"])


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
# GET /api/people/search?q=...
# ---------------------------------------------------------------------------

@router.get("/search")
async def search_people(q: str = Query(..., min_length=1)):
    """Search administrators and shareholders by name.

    SQL extracted from app/pages/5_people.py search_people().
    Returns distinct names with connection counts.
    """
    query = f"%{q.strip()}%"

    try:
        with get_conn() as conn:
            import psycopg2.extras
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            # Group by LOWER(name) to deduplicate case variations
            # (e.g. "Dries Bertrem" vs "Dries BERTREM"), display as INITCAP
            cur.execute("""
                SELECT INITCAP(MIN(name)) AS name,
                       COUNT(DISTINCT enterprise_number) AS n_admin_cos
                FROM administrator
                WHERE name ILIKE %s
                  AND person_type = 'natural'
                GROUP BY LOWER(name)
                UNION
                SELECT INITCAP(MIN(name)) AS name,
                       COUNT(DISTINCT enterprise_number) AS n_sh_cos
                FROM shareholder
                WHERE name ILIKE %s
                  AND shareholder_type = 'individual'
                GROUP BY LOWER(name)
                ORDER BY n_admin_cos DESC, name
                LIMIT 50
            """, (query, query))
            rows = [dict(r) for r in cur.fetchall()]
            cur.close()
            conn.commit()

        # Aggregate by name (union may produce duplicates for same name in both tables)
        agg = {}
        for row in rows:
            name = row["name"]
            cnt = row["n_admin_cos"]
            agg[name] = agg.get(name, 0) + cnt

        result = [
            {"name": name, "company_count": cnt}
            for name, cnt in sorted(agg.items(), key=lambda x: (-x[1], x[0]))
        ]
        return result

    except Exception as e:
        logger.exception("People search failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/people/{name}/connections
# ---------------------------------------------------------------------------

@router.get("/{name}/connections")
async def get_person_connections(name: str):
    """Load all company connections for a person/entity name.

    SQL extracted from app/pages/5_people.py load_person_connections().
    Returns administrator roles and shareholdings.
    """
    try:
        # Administrator roles — case-insensitive match since search returns INITCAP names
        admin_rows = fetch_all("""
            SELECT
                a.enterprise_number,
                COALESCE(d.denomination, a.enterprise_number) AS "company_name",
                a.role,
                a.mandate_start,
                a.mandate_end,
                a.representative_name,
                fl.revenue,
                fl.ebitda,
                fl.fte_total,
                fl.fiscal_year
            FROM administrator a
            LEFT JOIN denomination d ON d.entity_number = a.enterprise_number
                AND d.type_of_denomination = '001' AND d.language IN ('2','1')
            LEFT JOIN financial_latest fl ON fl.enterprise_number = a.enterprise_number
            WHERE LOWER(a.name) = LOWER(%s)
            ORDER BY a.mandate_start DESC
        """, (name,))

        # Shareholdings — case-insensitive match
        holding_rows = fetch_all("""
            SELECT
                s.enterprise_number,
                COALESCE(d.denomination, s.enterprise_number) AS "company_name",
                s.ownership_pct,
                s.shares_held,
                fl.revenue,
                fl.ebitda,
                fl.fte_total,
                fl.fiscal_year
            FROM shareholder s
            LEFT JOIN denomination d ON d.entity_number = s.enterprise_number
                AND d.type_of_denomination = '001' AND d.language IN ('2','1')
            LEFT JOIN financial_latest fl ON fl.enterprise_number = s.enterprise_number
            WHERE LOWER(s.name) = LOWER(%s)
            ORDER BY s.ownership_pct DESC NULLS LAST
        """, (name,))

        # Enrich admin rows with role labels
        role_labels = {
            "fct:m10": "Director", "fct:m11": "Managing director",
            "fct:m12": "Chairman", "fct:m13": "Administrator",
            "fct:m14": "Secretary", "fct:m15": "Treasurer",
            "fct:m20": "Statutory auditor", "fct:m30": "Liquidator",
            "fct:m40": "Daily management",
        }
        for row in admin_rows:
            row["role_label"] = role_labels.get(row.get("role", ""), row.get("role", ""))

        # Deduplicate
        seen_admin = set()
        unique_admins = []
        for row in admin_rows:
            key = (row["enterprise_number"], row.get("role"))
            if key not in seen_admin:
                seen_admin.add(key)
                unique_admins.append(row)

        seen_hold = set()
        unique_holdings = []
        for row in holding_rows:
            key = row["enterprise_number"]
            if key not in seen_hold:
                seen_hold.add(key)
                unique_holdings.append(row)

        # Count distinct companies
        all_cbes = set()
        for row in admin_rows:
            all_cbes.add(row["enterprise_number"])
        for row in holding_rows:
            all_cbes.add(row["enterprise_number"])

        return {
            "name": name,
            "total_companies": len(all_cbes),
            "admin_count": len(seen_admin),
            "holding_count": len(seen_hold),
            "administrator_roles": [_serialize_row(r) for r in unique_admins],
            "shareholdings": [_serialize_row(r) for r in unique_holdings],
        }

    except Exception as e:
        logger.exception("Person connections query failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# AI Enrichment — people profile summaries via OpenRouter
# ---------------------------------------------------------------------------

_people_enrichment_table_ensured = False


def _ensure_people_enrichment_table():
    """Create people_enrichment table if it does not exist (idempotent)."""
    global _people_enrichment_table_ensured
    if _people_enrichment_table_ensured:
        return
    execute("""
        CREATE TABLE IF NOT EXISTS people_enrichment (
            person_name TEXT PRIMARY KEY,
            summary TEXT,
            generated_at TIMESTAMP DEFAULT NOW()
        )
    """)
    _people_enrichment_table_ensured = True


# ---------------------------------------------------------------------------
# POST /api/people/{name}/enrich
# ---------------------------------------------------------------------------

@router.post("/{name}/enrich")
async def enrich_person(name: str, lang: str | None = None, user=Depends(get_current_user)):
    """Generate an AI professional profile summary for a person.

    Looks up their admin roles and holdings from the database,
    builds a prompt, and calls the AI to write a 2-3 sentence profile.
    ``lang`` (``nl``/``fr``/``en``) controls the output language.
    """
    _ensure_people_enrichment_table()

    # Gather admin roles — case-insensitive match
    admin_rows = fetch_all("""
        SELECT
            COALESCE(d.denomination, a.enterprise_number) AS company_name,
            a.role,
            a.mandate_start,
            a.mandate_end
        FROM administrator a
        LEFT JOIN denomination d ON d.entity_number = a.enterprise_number
            AND d.type_of_denomination = '001' AND d.language IN ('2','1')
        WHERE LOWER(a.name) = LOWER(%s)
        ORDER BY a.mandate_start DESC NULLS LAST
        LIMIT 20
    """, (name,))

    # Gather holdings — case-insensitive match
    holding_rows = fetch_all("""
        SELECT
            COALESCE(d.denomination, s.enterprise_number) AS company_name,
            s.ownership_pct
        FROM shareholder s
        LEFT JOIN denomination d ON d.entity_number = s.enterprise_number
            AND d.type_of_denomination = '001' AND d.language IN ('2','1')
        WHERE LOWER(s.name) = LOWER(%s)
        ORDER BY s.ownership_pct DESC NULLS LAST
        LIMIT 20
    """, (name,))

    if not admin_rows and not holding_rows:
        raise HTTPException(
            status_code=422,
            detail="Not enough data to generate a profile for this person",
        )

    # Build the prompt
    parts = [f"Person: {name}"]

    if admin_rows:
        role_labels = {
            "fct:m10": "Director", "fct:m11": "Managing director",
            "fct:m12": "Chairman", "fct:m13": "Administrator",
            "fct:m14": "Secretary", "fct:m15": "Treasurer",
            "fct:m20": "Statutory auditor", "fct:m30": "Liquidator",
            "fct:m40": "Daily management",
        }
        role_lines = []
        for r in admin_rows:
            role = role_labels.get(r.get("role", ""), r.get("role", ""))
            company = r.get("company_name", "unknown")
            active = "current" if not r.get("mandate_end") else "ended"
            role_lines.append(f"  - {role} at {company} ({active})")
        parts.append("Corporate roles:\n" + "\n".join(role_lines))

    if holding_rows:
        hold_lines = []
        for h in holding_rows:
            company = h.get("company_name", "unknown")
            pct = h.get("ownership_pct")
            pct_str = f" ({pct:.1f}%)" if pct else ""
            hold_lines.append(f"  - {company}{pct_str}")
        parts.append("Holdings/Shareholdings:\n" + "\n".join(hold_lines))

    prompt = (
        "Based on this person's corporate roles, write a 2-3 sentence "
        "professional profile. Be factual, do not speculate.\n\n"
        + "\n".join(parts)
    )

    system = (
        "You are a financial analyst assistant. Write concise, professional "
        "person profiles for private equity deal sourcing."
    )

    summary = await ai_complete(prompt, system=system, lang=lang)

    if not summary:
        raise HTTPException(
            status_code=503,
            detail="AI service unavailable — check OPENROUTER_API_KEY",
        )

    # Store (upsert) the enrichment
    execute("""
        INSERT INTO people_enrichment (person_name, summary, generated_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT (person_name)
        DO UPDATE SET summary = EXCLUDED.summary, generated_at = NOW()
    """, (name, summary))

    return {"summary": summary}


# ---------------------------------------------------------------------------
# GET /api/people/{name}/enrichment
# ---------------------------------------------------------------------------

@router.get("/{name}/enrichment")
async def get_person_enrichment(name: str, user=Depends(optional_user)):
    """Fetch existing AI-generated enrichment for a person."""
    _ensure_people_enrichment_table()

    row = fetch_one("""
        SELECT summary, generated_at
        FROM people_enrichment
        WHERE person_name = %s
    """, (name,))

    if not row:
        return None

    return _serialize_row(row)
