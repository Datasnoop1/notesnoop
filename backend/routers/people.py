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
async def search_people(q: str = Query(..., min_length=2)):
    """Search administrators and shareholders by name OR address.

    Returns each distinct name with:
      - ``company_count``: distinct companies the person touches (UNION of
        admin + shareholder roles, deduped — a person who is BOTH admin
        and shareholder of "Acme NV" only counts as 1).
      - ``top_companies``: up to 3 connected company names, ordered by
        latest filing revenue (so users see flagship companies first,
        not alphabetically-first shell SPRLs).

    Input is space-tolerant (extra/trailing whitespace, double spaces) and
    escapes ILIKE wildcards so a literal ``%`` in a name doesn't blow up
    matching. ``min_length=2`` guards against a single-character query
    fanning out to millions of rows.

    Address-based path: if the query matches a street, municipality, or
    zipcode, we also surface persons connected (admin or shareholder) to
    companies registered at that address. Useful when the user knows the
    location but not the name.
    """
    # Tolerate user sloppiness: trim, collapse internal whitespace, escape
    # ILIKE wildcards so a literal `%` in a name doesn't blow up matching.
    cleaned = " ".join(q.split())
    if len(cleaned) < 2:
        return []
    safe = cleaned.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    query = f"%{safe}%"
    # Detect Belgian-style 4-digit zip; address-pattern matches more
    # broadly (street / municipality / zipcode prefix).
    zip_q = cleaned if cleaned.isdigit() and len(cleaned) == 4 else None
    # Gate the address path to ≥4 chars to keep `addr_match` from doing a
    # multi-million-row ILIKE on noise like "ab". Streets like "Rue" still
    # qualify ("Rue " = 4 chars after we collapse whitespace).
    addr_q = query if (len(cleaned) >= 4 or zip_q) else None

    try:
        with get_conn() as conn:
            import psycopg2.extras
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            # Plan:
            # 1. `hits`: union of (a) admin and shareholder rows whose own
            #    name matches the pattern, (b) admin/shareholder rows whose
            #    company's registered address matches the pattern. Capped
            #    per-source so q="a" can't OOM.
            # 2. `per_person`: aggregate distinct (name, enterprise) pairs
            #    so a person counted as both admin AND shareholder of the
            #    same company doesn't get double-counted.
            # 3. Join `denomination` (DISTINCT ON to pick one name per CBE,
            #    NL preferred) and `financial_latest` (for revenue sort).
            # 4. Final aggregate: pick the 3 highest-revenue company names.
            cur.execute("""
                WITH addr_match AS (
                    -- Skip the entire scan when neither addr_q nor zip_q
                    -- are set; the leading IS-NOT-NULL pair short-circuits
                    -- the WHERE so the planner returns zero rows cheaply.
                    SELECT DISTINCT entity_number
                    FROM address
                    WHERE type_of_address = 'REGO'
                      AND (%s IS NOT NULL OR %s IS NOT NULL)
                      AND (
                          (%s IS NOT NULL AND street_nl ILIKE %s ESCAPE '\\')
                          OR (%s IS NOT NULL AND street_fr ILIKE %s ESCAPE '\\')
                          OR (%s IS NOT NULL AND municipality_nl ILIKE %s ESCAPE '\\')
                          OR (%s IS NOT NULL AND municipality_fr ILIKE %s ESCAPE '\\')
                          OR (%s IS NOT NULL AND zipcode = %s)
                      )
                    LIMIT 2000
                ),
                hits AS (
                    (SELECT a.name, a.enterprise_number
                     FROM administrator a
                     WHERE a.name ILIKE %s ESCAPE '\\'
                       AND a.person_type = 'natural'
                     LIMIT 5000)
                    UNION
                    (SELECT s.name, s.enterprise_number
                     FROM shareholder s
                     WHERE s.name ILIKE %s ESCAPE '\\'
                       AND s.shareholder_type = 'individual'
                     LIMIT 5000)
                    UNION
                    (SELECT a.name, a.enterprise_number
                     FROM administrator a
                     JOIN addr_match m ON m.entity_number = a.enterprise_number
                     WHERE a.person_type = 'natural'
                     LIMIT 5000)
                    UNION
                    (SELECT s.name, s.enterprise_number
                     FROM shareholder s
                     JOIN addr_match m ON m.entity_number = s.enterprise_number
                     WHERE s.shareholder_type = 'individual'
                     LIMIT 5000)
                    UNION
                    -- Stage 3: Staatsblad admin-event person_name hits.
                    (SELECT e.person_name AS name, e.enterprise_number
                     FROM staatsblad_event e
                     WHERE e.event_type = 'admin_event'
                       AND e.person_name IS NOT NULL
                       AND e.person_name ILIKE %s ESCAPE '\\'
                     LIMIT 5000)
                ),
                names AS (
                    SELECT DISTINCT ON (entity_number) entity_number, denomination
                    FROM denomination
                    WHERE type_of_denomination = '001'
                    ORDER BY entity_number,
                             CASE language WHEN '2' THEN 1 WHEN '1' THEN 2 ELSE 3 END
                ),
                per_company AS (
                    SELECT
                        LOWER(h.name) AS name_key,
                        INITCAP(MIN(h.name)) AS display_name,
                        h.enterprise_number,
                        COALESCE(n.denomination, h.enterprise_number) AS company_name,
                        COALESCE(fl.revenue, 0) AS revenue
                    FROM hits h
                    LEFT JOIN names n ON n.entity_number = h.enterprise_number
                    LEFT JOIN financial_latest fl ON fl.enterprise_number = h.enterprise_number
                    GROUP BY LOWER(h.name), h.enterprise_number, n.denomination, fl.revenue
                ),
                ranked AS (
                    SELECT name_key, MIN(display_name) AS display_name, enterprise_number,
                           MIN(company_name) AS company_name, MAX(revenue) AS revenue
                    FROM per_company
                    GROUP BY name_key, enterprise_number
                ),
                aggregated AS (
                    SELECT name_key,
                           MIN(display_name) AS name,
                           COUNT(*) AS company_count,
                           ARRAY_AGG(company_name ORDER BY revenue DESC NULLS LAST, company_name) AS company_names
                    FROM ranked
                    GROUP BY name_key
                )
                SELECT name, company_count, company_names[1:3] AS top_companies
                FROM aggregated
                ORDER BY company_count DESC, name
                LIMIT 50
            """, (
                # addr_match guards (2 short-circuit + 4 ILIKE pairs + 2 zip equality)
                addr_q, zip_q,
                addr_q, addr_q,
                addr_q, addr_q,
                addr_q, addr_q,
                addr_q, addr_q,
                zip_q, zip_q,
                # name-arm placeholders (admin + shareholder + staatsblad)
                query, query, query,
            ))
            rows = [dict(r) for r in cur.fetchall()]
            cur.close()
            conn.commit()

        return [
            {
                "name": r["name"],
                "company_count": int(r["company_count"]) if r["company_count"] is not None else 0,
                "top_companies": r.get("top_companies") or [],
            }
            for r in rows
        ]

    except Exception as e:
        logger.exception("People search failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/people/{name}/connections
# ---------------------------------------------------------------------------

@router.get("/{name}/connections")
async def get_person_connections(name: str):
    """Load all company connections for a person/entity name.

    Phase 3c: admin connections are now unioned across both data
    sources — the NBB snapshot (annual filings, year-old) AND
    `staatsblad_event.admin_event` rows (fresh). Each connection is
    annotated with `as_of` and `source` ('nbb' | 'staatsblad') so the
    frontend network graph can render data-freshness visually.
    """
    try:
        # NBB snapshot admin connections.
        nbb_admin_rows = fetch_all("""
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

        # Staatsblad admin events.  Aggregate to the (CBE, role)
        # granularity so each row represents one mandate in the
        # timeline; pick the LATEST event as the "current state".
        staatsblad_admin_rows = fetch_all("""
            WITH events AS (
                SELECT
                    e.enterprise_number,
                    COALESCE(d.denomination, e.enterprise_number) AS company_name,
                    COALESCE(NULLIF(e.person_role, ''), 'Administrator') AS role,
                    e.sub_type,
                    COALESCE(e.event_date, e.pub_date) AS mandate_date,
                    e.pub_date,
                    e.pub_reference,
                    -- Coalesce NULL + empty role to a single bucket so
                    -- a person with one mandate doesn't split into two
                    -- "current-state" rows.
                    ROW_NUMBER() OVER (
                        PARTITION BY e.enterprise_number,
                                     COALESCE(NULLIF(e.person_role, ''), '')
                        ORDER BY e.pub_date DESC, e.id DESC
                    ) AS rn
                FROM staatsblad_event e
                LEFT JOIN denomination d ON d.entity_number = e.enterprise_number
                    AND d.type_of_denomination = '001' AND d.language IN ('2','1')
                WHERE e.event_type = 'admin_event'
                  AND LOWER(COALESCE(e.person_name, e.entity_name, '')) = LOWER(%s)
            )
            SELECT ev.enterprise_number, ev.company_name, ev.role, ev.sub_type,
                   ev.mandate_date, ev.pub_date, ev.pub_reference,
                   fl.revenue, fl.ebitda, fl.fte_total, fl.fiscal_year
            FROM events ev
            LEFT JOIN financial_latest fl ON fl.enterprise_number = ev.enterprise_number
            WHERE ev.rn = 1
            ORDER BY ev.pub_date DESC
        """, (name,))

        # Shareholdings — unchanged (no shareholder events yet from
        # the extractor; that's a Phase 4+ idea).
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

        # NBB role labels (KBO fct:* codes)
        role_labels = {
            "fct:m10": "Director", "fct:m11": "Managing director",
            "fct:m12": "Chairman", "fct:m13": "Administrator",
            "fct:m14": "Secretary", "fct:m15": "Treasurer",
            "fct:m20": "Statutory auditor", "fct:m30": "Liquidator",
            "fct:m40": "Daily management",
        }

        # Annotate NBB rows with source/as_of.  fiscal_year → 'YYYY-12-31'.
        for row in nbb_admin_rows:
            row["role_label"] = role_labels.get(row.get("role", ""), row.get("role", ""))
            row["source"] = "nbb"
            fy = row.get("fiscal_year") or ""
            if isinstance(fy, str) and len(fy) >= 4 and fy[:4].isdigit():
                row["as_of"] = f"{fy[:4]}-12-31"
            else:
                row["as_of"] = None

        # Annotate Staatsblad rows. sub_type='resignation' → mandate is
        # ended, so we flag it via mandate_end and don't surface it in
        # the "active" count.
        for row in staatsblad_admin_rows:
            row["role_label"] = row.get("role") or "Administrator"
            row["source"] = "staatsblad"
            row["mandate_start"] = (
                str(row.get("mandate_date")) if row.get("mandate_date") else None
            )
            sub = (row.get("sub_type") or "").lower()
            if sub in ("resignation", "end", "termination"):
                row["mandate_end"] = str(row.get("mandate_date")) if row.get("mandate_date") else None
            else:
                row["mandate_end"] = None
            row["as_of"] = str(row.get("pub_date")) if row.get("pub_date") else None

        # Union + dedup by (CBE, role).  When both sources know the
        # same (CBE, role), keep whichever has the LATER as_of and
        # mark `source='merged'`.
        combined: dict[tuple[str, str], dict] = {}
        for row in nbb_admin_rows + staatsblad_admin_rows:
            key = (row.get("enterprise_number") or "", row.get("role") or "")
            existing = combined.get(key)
            if existing is None:
                combined[key] = row
                continue
            ex_date = existing.get("as_of") or ""
            this_date = row.get("as_of") or ""
            if this_date > ex_date:
                merged_row = {**row, "source": "merged"}
                combined[key] = merged_row
            else:
                existing["source"] = "merged"

        unique_admins = list(combined.values())
        seen_admin = set(combined.keys())

        # Shareholdings dedup unchanged.
        seen_hold = set()
        unique_holdings = []
        for row in holding_rows:
            key = row["enterprise_number"]
            if key not in seen_hold:
                seen_hold.add(key)
                unique_holdings.append(row)

        # Count distinct companies (union across both sources).
        all_cbes = set()
        for row in unique_admins:
            all_cbes.add(row.get("enterprise_number") or "")
        for row in holding_rows:
            all_cbes.add(row["enterprise_number"])
        all_cbes.discard("")

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
async def get_person_enrichment(name: str, lang: str | None = None, user=Depends(optional_user)):
    """Fetch existing AI-generated enrichment for a person.

    ``lang`` translates the cached summary on the fly; same in-process cache
    as the company enrichment endpoint. Per operator policy, translation
    runs for everyone (anon + auth) — cost is bounded by the in-process
    24h cache plus the global per-IP rate limit.
    """
    from ai_client import translate_cached

    _ensure_people_enrichment_table()

    row = fetch_one("""
        SELECT summary, generated_at
        FROM people_enrichment
        WHERE person_name = %s
    """, (name,))

    if not row:
        return None

    serialized = _serialize_row(row)
    if lang and serialized.get("summary"):
        serialized["summary"] = await translate_cached(name, "person_summary", serialized["summary"], lang)
    return serialized
