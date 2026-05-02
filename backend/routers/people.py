"""People router — search administrators and shareholders by name."""

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from cache import ttl_cache
from db import fetch_all, fetch_one, execute, get_conn
from auth import get_current_user, optional_user
from feature_flags import person_public_url_enabled
from routers.admin import _require_admin
from ai_client import ai_complete
from search_normalization import (
    ilike_escape as _v2_ilike_escape,
    normalize_name as _v2_normalize_name,
    phonetic_key as _v2_phonetic_key,
    reversed_key as _v2_reversed_key,
    tokenize as _v2_tokenize,
)

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
        elif isinstance(v, UUID):
            out[k] = str(v)
        else:
            out[k] = v
    return out


def _require_person_v1_access(user: Optional[dict]) -> Optional[dict]:
    """Hide Person v1 from non-admins while the public URL flag is off."""
    if person_public_url_enabled():
        return user
    if user is None:
        raise HTTPException(status_code=404, detail="Not found")
    try:
        return _require_admin(user)
    except HTTPException:
        raise HTTPException(status_code=404, detail="Not found")


# ---------------------------------------------------------------------------
# GET /api/people/search?q=...
# ---------------------------------------------------------------------------

# Intentionally sync — see `search_companies` in companies/search.py for
# the rationale. Sync psycopg2 inside `async def` blocks the event loop
# and serialises every concurrent search.
@router.get("/search")
def search_people(q: str = Query(..., min_length=2, max_length=200)):
    """Search admins/shareholders/staatsblad-events by name — V2.

    Handles accent-insensitivity, name-order reversal, legal-suffix
    stripping, trigram fuzzy, and Double-Metaphone phonetic fallback.
    Each name returned includes company_count, up to 3 top_companies
    ordered by revenue, and the internal relevance score.
    """
    raw = (q or "").strip()
    if len(raw) < 2:
        return []
    return _search_people_cached(raw.lower())


@ttl_cache(ttl_seconds=3600, maxsize=4096)
def _search_people_cached(raw: str):
    """Memoised core of /api/people/search.

    60s TTL is short enough that newly-loaded admins (e.g. fresh NBB
    backload, fresh staatsblad scrape) surface within a minute, yet
    long enough to collapse the typing burst when a user iterates on
    short prefixes like "col" → "colr" → "colru". The post-CTE
    LATERAL joins on this query take ~500-1500 ms cold even with the
    trigram length-gate; caching makes repeat hits near-instant.
    Cache key is the lowercased raw query, so case variants share a
    row.
    """
    nq = _v2_normalize_name(raw)
    tokens = _v2_tokenize(raw)
    rev = _v2_reversed_key(raw)
    phon = _v2_phonetic_key(raw) or None

    # Wildcard-escape tokens to neutralise user-supplied %/_/\\.
    tok1 = f"%{_v2_ilike_escape(tokens[0])}%" if len(tokens) >= 1 else None
    tok2 = f"%{_v2_ilike_escape(tokens[1])}%" if len(tokens) >= 2 else None
    tok3 = f"%{_v2_ilike_escape(tokens[2])}%" if len(tokens) >= 3 else None
    tok4 = f"%{_v2_ilike_escape(tokens[3])}%" if len(tokens) >= 4 else None
    # Person address fallback kept at ≥4 (street names like "Rue " qualify).
    addr_like = f"%{_v2_ilike_escape(raw)}%" if len(raw) >= 4 else None
    zip_q = raw if raw.isdigit() and len(raw) == 4 else None

    params = {
        "nq": nq or None,
        "rev": rev or None,
        "phon": phon,
        "tok1": tok1, "tok2": tok2, "tok3": tok3, "tok4": tok4,
        "addr_like": addr_like,
        "zip_q": zip_q,
        "n_tokens": len(tokens),
    }

    try:
        rows = fetch_all(_PEOPLE_V2_SQL, params)
    except Exception:
        logger.exception("people search V2 failed for q=%r", raw[:80])
        raise HTTPException(status_code=500, detail="search_failed")

    def _coerce_top(v):
        """JSONB column returns as list[dict] directly; handle None."""
        return v if isinstance(v, list) else []

    return [
        {
            "name": r["name"],
            "company_count": int(r["company_count"]) if r.get("company_count") is not None else 0,
            "top_companies": _coerce_top(r.get("top_companies")),
            "score": float(r["score"]) if r.get("score") is not None else 0.0,
            # `dominant_city` and `dominant_postcode` come from the
            # Staatsblad `person_domicile_*` columns when available.
            # Fall back to the highest-revenue company's city as a
            # proxy so common names still get some disambiguation
            # while the staatsblad re-extraction is still running.
            "dominant_city": r.get("dominant_city"),
            "dominant_postcode": r.get("dominant_postcode"),
            "has_domicile": bool(r.get("has_domicile")),
        }
        for r in rows
    ]


# Scored CTE. The UNION arms below each emit `(name, enterprise_number,
# src, base_score)` rows. `grouped` reduces to one row per (lowercase
# name, company) so a person who is both admin + shareholder of the
# same entity counts once. `aggregated` is one row per name with the
# top-3 highest-revenue companies.
_PEOPLE_V2_SQL = """
WITH
-- MATERIALIZED forces Postgres to evaluate the 12 UNION arms once and
-- spool the result, instead of inlining the CTE into every downstream
-- reference. Downstream `grouped` joins to denomination/staatsblad/
-- financial_latest by enterprise_number, and re-evaluating those LIMIT
-- arms per join row blew up cost. With ~500-1000 hits per query the
-- materialised set is small and reuse pays for itself.
people_hits AS MATERIALIZED (
    -- 1.0: exact normalised match OR exact reversed (order-agnostic)
    SELECT a.name, a.enterprise_number, 'admin' AS src, 1.0::real AS base
    FROM administrator a
    WHERE a.person_type = 'natural'
      AND a.name_normalized IS NOT NULL
      AND (
          (%(nq)s IS NOT NULL AND a.name_normalized = %(nq)s)
          OR (%(rev)s IS NOT NULL AND a.name_reversed = %(rev)s)
      )
    UNION ALL
    SELECT s.name, s.enterprise_number, 'shareholder', 1.0::real
    FROM shareholder s
    WHERE s.shareholder_type = 'individual'
      AND s.name_normalized IS NOT NULL
      AND (
          (%(nq)s IS NOT NULL AND s.name_normalized = %(nq)s)
          OR (%(rev)s IS NOT NULL AND s.name_reversed = %(rev)s)
      )
    UNION ALL
    SELECT e.person_name AS name, e.enterprise_number, 'staatsblad', 1.0::real
    FROM staatsblad_event e
    WHERE e.event_type = 'admin_event'
      AND e.person_name IS NOT NULL
      AND e.person_name_normalized IS NOT NULL
      AND (
          (%(nq)s IS NOT NULL AND e.person_name_normalized = %(nq)s)
          OR (%(rev)s IS NOT NULL AND e.person_name_reversed = %(rev)s)
      )

    UNION ALL
    -- 0.7: every typed token ILIKE-matches the normalised name (any order).
    -- Each LIMIT-bearing subquery MUST be wrapped in parens when placed
    -- between UNION ALL clauses, otherwise the LIMIT applies to the
    -- whole union (Postgres parse error).
    (SELECT a.name, a.enterprise_number, 'admin', 0.7::real
     FROM administrator a
     WHERE a.person_type = 'natural'
       AND a.name_normalized IS NOT NULL
       AND %(n_tokens)s >= 1
       AND (%(tok1)s IS NULL OR a.name_normalized ILIKE %(tok1)s ESCAPE '\\')
       AND (%(tok2)s IS NULL OR a.name_normalized ILIKE %(tok2)s ESCAPE '\\')
       AND (%(tok3)s IS NULL OR a.name_normalized ILIKE %(tok3)s ESCAPE '\\')
       AND (%(tok4)s IS NULL OR a.name_normalized ILIKE %(tok4)s ESCAPE '\\')
     LIMIT 500)
    UNION ALL
    (SELECT s.name, s.enterprise_number, 'shareholder', 0.7::real
     FROM shareholder s
     WHERE s.shareholder_type = 'individual'
       AND s.name_normalized IS NOT NULL
       AND %(n_tokens)s >= 1
       AND (%(tok1)s IS NULL OR s.name_normalized ILIKE %(tok1)s ESCAPE '\\')
       AND (%(tok2)s IS NULL OR s.name_normalized ILIKE %(tok2)s ESCAPE '\\')
       AND (%(tok3)s IS NULL OR s.name_normalized ILIKE %(tok3)s ESCAPE '\\')
       AND (%(tok4)s IS NULL OR s.name_normalized ILIKE %(tok4)s ESCAPE '\\')
     LIMIT 500)
    UNION ALL
    (SELECT e.person_name, e.enterprise_number, 'staatsblad', 0.7::real
     FROM staatsblad_event e
     WHERE e.event_type = 'admin_event'
       AND e.person_name_normalized IS NOT NULL
       AND %(n_tokens)s >= 1
       AND (%(tok1)s IS NULL OR e.person_name_normalized ILIKE %(tok1)s ESCAPE '\\')
       AND (%(tok2)s IS NULL OR e.person_name_normalized ILIKE %(tok2)s ESCAPE '\\')
       AND (%(tok3)s IS NULL OR e.person_name_normalized ILIKE %(tok3)s ESCAPE '\\')
       AND (%(tok4)s IS NULL OR e.person_name_normalized ILIKE %(tok4)s ESCAPE '\\')
     LIMIT 500)

    UNION ALL
    -- 0.4: trigram fuzzy for typo tolerance.
    -- Gated to length(nq) >= 4: on 3-char queries the GIN trigram bitmap
    -- explodes to 2.7s+ over the 1M admin rows even with LIMIT 200,
    -- because the index pre-filter passes too many candidates and the
    -- recheck scans them all. Matching company-search.py and suggest's
    -- length-gate behaviour. The exact / token-AND arms above already
    -- handle short prefixes; trigram is purely typo tolerance.
    (SELECT a.name, a.enterprise_number, 'admin',
            LEAST(0.4, similarity(a.name_normalized, %(nq)s))::real
     FROM administrator a
     WHERE a.person_type = 'natural'
       AND %(nq)s IS NOT NULL
       AND length(%(nq)s) >= 4
       AND a.name_normalized %% %(nq)s
       AND similarity(a.name_normalized, %(nq)s) > 0.3
     LIMIT 200)
    UNION ALL
    (SELECT s.name, s.enterprise_number, 'shareholder',
            LEAST(0.4, similarity(s.name_normalized, %(nq)s))::real
     FROM shareholder s
     WHERE s.shareholder_type = 'individual'
       AND %(nq)s IS NOT NULL
       AND length(%(nq)s) >= 4
       AND s.name_normalized %% %(nq)s
       AND similarity(s.name_normalized, %(nq)s) > 0.3
     LIMIT 200)

    UNION ALL
    -- 0.3: Double Metaphone phonetic fallback (Braet ↔ Braete ↔ Brait).
    -- Exact match on the phonetic key — dmetaphone output is 1-4 chars
    -- per token so trigram similarity is degenerate here; equality is
    -- both cheaper and semantically correct.
    (SELECT a.name, a.enterprise_number, 'admin', 0.3::real
     FROM administrator a
     WHERE %(phon)s IS NOT NULL
       AND a.person_type = 'natural'
       AND a.name_phonetic = %(phon)s
     LIMIT 200)
    UNION ALL
    (SELECT s.name, s.enterprise_number, 'shareholder', 0.3::real
     FROM shareholder s
     WHERE %(phon)s IS NOT NULL
       AND s.shareholder_type = 'individual'
       AND s.name_phonetic = %(phon)s
     LIMIT 200)

    UNION ALL
    -- 0.2: address fallback
    (SELECT a.name, a.enterprise_number, 'admin', 0.2::real
     FROM administrator a
     JOIN address ad ON ad.entity_number = a.enterprise_number
     WHERE a.person_type = 'natural'
       AND ad.type_of_address = 'REGO'
       AND %(addr_like)s IS NOT NULL
       AND (
          ad.street_nl          ILIKE %(addr_like)s ESCAPE '\\'
          OR ad.street_fr       ILIKE %(addr_like)s ESCAPE '\\'
          OR ad.municipality_nl ILIKE %(addr_like)s ESCAPE '\\'
          OR ad.municipality_fr ILIKE %(addr_like)s ESCAPE '\\'
          OR (%(zip_q)s IS NOT NULL AND ad.zipcode = %(zip_q)s)
      )
     LIMIT 500)

    -- ===================================================================
    -- Affiliation arms: a softer link than admin/shareholder. Person X
    -- represents a corporate director (Company A) of Company B, so X is
    -- "affiliated" with Company A even though the name may never appear
    -- in Company A's own filings. Scores are uniformly ~0.55x of the
    -- admin counterparts so a direct admin/shareholder hit always beats
    -- a same-arm affiliation hit at the MAX(base) dedup step downstream.
    -- ===================================================================
    UNION ALL
    -- 0.55: exact normalised match OR exact reversed
    (SELECT af.person_name AS name, af.enterprise_number, 'affiliation' AS src,
            0.55::real AS base
     FROM affiliation af
     WHERE af.name_normalized IS NOT NULL
       AND (
           (%(nq)s IS NOT NULL AND af.name_normalized = %(nq)s)
           OR (%(rev)s IS NOT NULL AND af.name_reversed = %(rev)s)
       )
     LIMIT 500)
    UNION ALL
    -- 0.4: token-AND
    (SELECT af.person_name, af.enterprise_number, 'affiliation', 0.4::real
     FROM affiliation af
     WHERE af.name_normalized IS NOT NULL
       AND %(n_tokens)s >= 1
       AND (%(tok1)s IS NULL OR af.name_normalized ILIKE %(tok1)s ESCAPE '\\')
       AND (%(tok2)s IS NULL OR af.name_normalized ILIKE %(tok2)s ESCAPE '\\')
       AND (%(tok3)s IS NULL OR af.name_normalized ILIKE %(tok3)s ESCAPE '\\')
       AND (%(tok4)s IS NULL OR af.name_normalized ILIKE %(tok4)s ESCAPE '\\')
     LIMIT 500)
    UNION ALL
    -- 0.25: trigram fuzzy. Same length-4 gate as the admin/shareholder
    -- trigram arms above — 3-char queries fan out catastrophically.
    (SELECT af.person_name, af.enterprise_number, 'affiliation',
            LEAST(0.25, similarity(af.name_normalized, %(nq)s))::real
     FROM affiliation af
     WHERE %(nq)s IS NOT NULL
       AND length(%(nq)s) >= 4
       AND af.name_normalized %% %(nq)s
       AND similarity(af.name_normalized, %(nq)s) > 0.3
     LIMIT 200)
    UNION ALL
    -- 0.2: phonetic
    (SELECT af.person_name, af.enterprise_number, 'affiliation', 0.2::real
     FROM affiliation af
     WHERE %(phon)s IS NOT NULL
       AND af.name_phonetic = %(phon)s
     LIMIT 200)
),
grouped AS (
    SELECT LOWER(h.name) AS name_key,
           MAX(h.base)   AS best_base,
           h.enterprise_number,
           -- True iff every hit for this (name, company) pair is an
           -- affiliation row. False as soon as a single admin /
           -- shareholder / staatsblad hit appears, so direct
           -- relationships always win the visual ranking downstream.
           BOOL_AND(h.src = 'affiliation') AS affiliation_only,
           COALESCE(nl.denomination, h.enterprise_number) AS company_name,
           COALESCE(fl.revenue, 0) AS revenue,
           ci.city AS company_city,
           -- Structured person-domicile from staatsblad, extracted by
           -- the prompt_v3 OCR pipeline. Populated progressively as
           -- the re-extraction cron processes historical rows; NULL
           -- when unavailable. This lets us distinguish two
           -- different "Jan De Clerck"s registered at different
           -- addresses, which KBO data alone can't do.
           sbd.person_domicile_city     AS person_city,
           sbd.person_domicile_postcode AS person_postcode,
           -- Strip punctuation before INITCAP so "BRAET, TIM" displays
           -- as "Braet Tim" rather than "Braet, Tim".
           MIN(INITCAP(REGEXP_REPLACE(h.name, '[^[:alpha:][:space:]]', '', 'g'))) AS display_name
    FROM people_hits h
    -- LATERAL denomination lookup: only fetches the best name per
    -- enterprise_number we actually hit (~500 rows) rather than
    -- scanning the full 3.3M-row denomination table in a CTE.
    LEFT JOIN LATERAL (
        SELECT denomination
        FROM denomination d
        WHERE d.entity_number = h.enterprise_number
          AND d.type_of_denomination = '001'
        ORDER BY CASE d.language WHEN '2' THEN 1 WHEN '1' THEN 2 ELSE 3 END
        LIMIT 1
    ) nl ON TRUE
    -- LATERAL: most-recent staatsblad admin event with a populated
    -- domicile for THIS (person, company) combo. We use the event
    -- with the highest person_domicile_confidence and most-recent
    -- extraction timestamp so progressive backfill keeps improving
    -- the signal without breaking older fallback results.
    LEFT JOIN LATERAL (
        SELECT person_domicile_city,
               person_domicile_postcode
        FROM staatsblad_event e
        WHERE e.enterprise_number = h.enterprise_number
          AND e.event_type = 'admin_event'
          AND LOWER(COALESCE(e.person_name, '')) = LOWER(h.name)
          AND e.person_domicile_city IS NOT NULL
        ORDER BY COALESCE(e.person_domicile_confidence, 0) DESC,
                 e.person_domicile_extracted_at DESC NULLS LAST,
                 e.pub_date DESC
        LIMIT 1
    ) sbd ON TRUE
    LEFT JOIN financial_latest fl ON fl.enterprise_number = h.enterprise_number
    LEFT JOIN company_info ci     ON ci.enterprise_number = h.enterprise_number
    GROUP BY LOWER(h.name), h.enterprise_number, nl.denomination, fl.revenue,
             ci.city, sbd.person_domicile_city, sbd.person_domicile_postcode
),
aggregated AS (
    -- Group key includes the inferred person_city + person_postcode:
    -- two "Jan De Clerck"s whose staatsblad rows disagree on city
    -- become two distinct result rows. When staatsblad has no
    -- domicile (still being backfilled), COALESCE('') lets them
    -- collapse into one row — same as before.
    SELECT name_key,
           COALESCE(person_city, '')     AS group_city,
           COALESCE(person_postcode, '') AS group_postcode,
           MIN(display_name) AS name,
           MAX(best_base)    AS score,
           COUNT(DISTINCT enterprise_number) AS company_count,
           -- Prefer structured person_city over the company-city proxy
           -- so UI disambiguator tags are accurate once staatsblad
           -- backfill catches up.
           COALESCE(
             MAX(person_city),
             (ARRAY_AGG(company_city ORDER BY revenue DESC NULLS LAST) FILTER (WHERE company_city IS NOT NULL))[1]
           ) AS dominant_city,
           MAX(person_postcode) AS dominant_postcode,
           -- Was the disambiguator derived from a real staatsblad
           -- domicile row? Frontend can render differently
           -- ("Antwerpen" vs "Antwerpen  ·  via Staatsblad").
           BOOL_OR(person_city IS NOT NULL) AS has_domicile,
           JSONB_AGG(
             JSONB_BUILD_OBJECT(
               'name', company_name,
               'cbe', enterprise_number,
               -- Frontend renders affiliation-only entries with a
               -- softer pill + tooltip ("represents a corporate
               -- director — not a direct mandate").
               'affiliation_only', affiliation_only
             )
             ORDER BY affiliation_only ASC, revenue DESC NULLS LAST, company_name
           ) AS company_list
    FROM grouped
    GROUP BY name_key, COALESCE(person_city, ''), COALESCE(person_postcode, '')
)
-- First 20 kept inline so the frontend can expand without another
-- round-trip. Heavier people (50+ companies) are rare; the
-- /people/{name}/connections endpoint already covers that tail.
SELECT name, company_count, score,
       dominant_city, dominant_postcode, has_domicile,
       (
         SELECT JSONB_AGG(elem)
         FROM (
           SELECT elem
           FROM jsonb_array_elements(company_list) WITH ORDINALITY AS x(elem, n)
           WHERE n <= 20
         ) sub
       ) AS top_companies
FROM aggregated
ORDER BY score DESC, company_count DESC, name ASC
LIMIT 50
"""


# ---------------------------------------------------------------------------
# GET /api/people/person/{person_id}
# ---------------------------------------------------------------------------

@router.get("/person/{person_id}")
async def get_person_v1(person_id: str, user=Depends(optional_user)):
    """Internal Person v1 audit profile by stable person_id."""
    _require_person_v1_access(user)

    try:
        person_uuid = str(UUID(person_id.strip()))
    except ValueError:
        raise HTTPException(status_code=404, detail="Not found")

    person = fetch_one(
        """
        SELECT
            person_id::text,
            canonical_name,
            name_normalized,
            primary_city,
            primary_postcode,
            role_count,
            first_seen_date,
            last_seen_date,
            cluster_version,
            status,
            merged_into::text,
            created_at
        FROM person
        WHERE person_id = %s
        """,
        (person_uuid,),
    )
    if not person:
        raise HTTPException(status_code=404, detail="Not found")
    if person.get("status") == "tombstone":
        raise HTTPException(status_code=410, detail="Gone")

    links = fetch_all(
        """
        SELECT
            pl.id,
            pl.source_table,
            pl.source_pk,
            pl.source_mention_seq,
            pl.source_field,
            pl.enterprise_number,
            COALESCE(d.denomination, pl.enterprise_number) AS company_name,
            pl.name_as_written,
            pl.link_kind,
            pl.confidence,
            pl.confirmed_by_human,
            pl.cluster_version
        FROM person_link pl
        LEFT JOIN denomination d
            ON d.entity_number = pl.enterprise_number
           AND d.type_of_denomination = '001'
           AND d.language IN ('2', '1')
        WHERE pl.person_id = %s
        ORDER BY pl.confidence DESC,
                 pl.source_table ASC,
                 pl.enterprise_number ASC NULLS LAST,
                 pl.id ASC
        LIMIT 500
        """,
        (person_uuid,),
    )

    source_counts = fetch_all(
        """
        SELECT
            source_table,
            count(*)::int AS link_count,
            min(confidence)::float AS min_confidence,
            max(confidence)::float AS max_confidence
        FROM person_link
        WHERE person_id = %s
        GROUP BY source_table
        ORDER BY source_table
        """,
        (person_uuid,),
    )

    merge_log = fetch_all(
        """
        SELECT
            id,
            op_kind,
            primary_id::text,
            secondary_id::text,
            moved_link_ids,
            op_at,
            op_by,
            reason
        FROM person_merge_log
        WHERE primary_id = %s OR secondary_id = %s
        ORDER BY op_at DESC, id DESC
        LIMIT 50
        """,
        (person_uuid, person_uuid),
    )

    return {
        "person": _serialize_row(person),
        "links": [_serialize_row(r) for r in links],
        "source_counts": [_serialize_row(r) for r in source_counts],
        "merge_log": [_serialize_row(r) for r in merge_log],
        "public_url_enabled": person_public_url_enabled(),
    }


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

        # Affiliations: weak link via corporate-director representation.
        # Surface ALL filings that introduced the link (one row per
        # via_enterprise_number) so the frontend can render breadcrumbs.
        # Probe-then-query: the table may not exist on environments that
        # haven't applied the affiliation migration yet — return empty
        # rather than 500.
        affiliation_rows: list[dict] = []
        with get_conn() as _probe_conn:
            with _probe_conn.cursor() as _probe_cur:
                _probe_cur.execute(
                    "SELECT to_regclass('public.affiliation') IS NOT NULL"
                )
                affiliation_table_present = bool(_probe_cur.fetchone()[0])
        if affiliation_table_present:
            affiliation_rows = fetch_all("""
                SELECT
                    af.enterprise_number,
                    COALESCE(d.denomination, af.enterprise_number) AS company_name,
                    af.via_enterprise_number,
                    COALESCE(via_d.denomination, af.via_enterprise_number) AS via_company_name,
                    af.via_deposit_key,
                    af.fiscal_year,
                    af.affiliation_type,
                    af.first_seen_at,
                    af.last_seen_at,
                    fl.revenue,
                    fl.ebitda,
                    fl.fte_total,
                    fl.fiscal_year AS fl_fiscal_year
                FROM affiliation af
                LEFT JOIN denomination d
                    ON d.entity_number = af.enterprise_number
                    AND d.type_of_denomination = '001' AND d.language IN ('2','1')
                LEFT JOIN denomination via_d
                    ON via_d.entity_number = af.via_enterprise_number
                    AND via_d.type_of_denomination = '001' AND via_d.language IN ('2','1')
                LEFT JOIN financial_latest fl
                    ON fl.enterprise_number = af.enterprise_number
                WHERE LOWER(af.person_name) = LOWER(%s)
                ORDER BY af.last_seen_at DESC, af.enterprise_number
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

        # Affiliations dedup by enterprise_number — multiple filings can
        # observe the same (person, company) link; collapse to one card
        # but keep the list of source filings for provenance breadcrumbs.
        affiliations_by_ent: dict[str, dict] = {}
        for row in affiliation_rows:
            cbe_key = row.get("enterprise_number") or ""
            if not cbe_key:
                continue
            existing = affiliations_by_ent.get(cbe_key)
            if existing is None:
                row_copy = dict(row)
                row_copy["sources"] = [
                    {
                        "via_enterprise_number": row.get("via_enterprise_number"),
                        "via_company_name": row.get("via_company_name"),
                        "via_deposit_key": row.get("via_deposit_key"),
                        "fiscal_year": row.get("fiscal_year"),
                    }
                ]
                affiliations_by_ent[cbe_key] = row_copy
            else:
                existing["sources"].append(
                    {
                        "via_enterprise_number": row.get("via_enterprise_number"),
                        "via_company_name": row.get("via_company_name"),
                        "via_deposit_key": row.get("via_deposit_key"),
                        "fiscal_year": row.get("fiscal_year"),
                    }
                )
        unique_affiliations = list(affiliations_by_ent.values())

        # Count distinct companies (union across all sources).
        all_cbes = set()
        for row in unique_admins:
            all_cbes.add(row.get("enterprise_number") or "")
        for row in holding_rows:
            all_cbes.add(row["enterprise_number"])
        for row in unique_affiliations:
            all_cbes.add(row.get("enterprise_number") or "")
        all_cbes.discard("")

        return {
            "name": name,
            "total_companies": len(all_cbes),
            "admin_count": len(seen_admin),
            "holding_count": len(seen_hold),
            "affiliation_count": len(unique_affiliations),
            "administrator_roles": [_serialize_row(r) for r in unique_admins],
            "shareholdings": [_serialize_row(r) for r in unique_holdings],
            "affiliations": [_serialize_row(r) for r in unique_affiliations],
        }

    except Exception as e:
        logger.exception("Person connections query failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# AI Enrichment — people profile summaries via OpenRouter
# ---------------------------------------------------------------------------

_people_enrichment_table_ensured = False


def _ensure_people_enrichment_table():
    """Compatibility shim for people_enrichment moved to tracked migrations."""
    global _people_enrichment_table_ensured
    if _people_enrichment_table_ensured:
        return
    _people_enrichment_table_ensured = True


# ---------------------------------------------------------------------------
# POST /api/people/{name}/enrich
# ---------------------------------------------------------------------------

@router.post("/{name}/enrich")
async def enrich_person(name: str, lang: str | None = None, user=Depends(optional_user)):
    """Generate an AI professional profile summary for a person.

    Looks up their admin roles and holdings from the database,
    builds a prompt, and calls the AI to write a 2-3 sentence profile.
    ``lang`` (``nl``/``fr``/``en``) controls the output language.

    Anonymous-friendly per operator policy. Tier-bucketed under
    ``ai_enrichments_per_day``.
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
