"""Companies search router — V2 scored CTE + category split.

`GET /api/companies/search?q=...`

Replaces the legacy 7-step fallback ladder with a single scored CTE query
that combines exact / prefix / token-AND / denomination / trigram /
address matches, weighted by quality (revenue, active status) and
popularity (click-count from activity_log). Results are partitioned into
`commercial` vs `nonprofit_or_public` buckets driven by the full KBO
juridical-form taxonomy (`juridical_form_category`).

CBE / VAT inputs short-circuit to an exact enterprise-number prefix
lookup before any text search fires.
"""

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

import psycopg2.extras
from cache import ttl_cache
from db import fetch_all, fetch_one, get_conn, normalize_name


def _search_with_trgm_threshold(sql: str, params: dict, threshold: float) -> list[dict]:
    """Run the main search SQL on a single connection, after setting
    pg_trgm's similarity threshold for this cursor only.

    `fetch_all` would otherwise re-acquire a (potentially different)
    pool connection for each call, losing the `SET` that has to share
    the session with the search query.

    `set_limit()` mutates the session-wide pg_trgm.similarity_threshold,
    which survives transaction rollback. We MUST reset it before returning
    the connection to the pool — otherwise the next caller borrowing this
    connection inherits our threshold and either over-recalls (slow) or
    under-recalls (misses results).

    Subtlety: when the inner query raises, the connection is in an
    aborted-transaction state and any further cur.execute() will fail
    with InFailedSqlTransaction. So we explicitly rollback first on the
    error path, then issue the reset on a clean session.
    """
    DEFAULT_THRESHOLD = 0.3  # Postgres pg_trgm default
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            raised = False
            try:
                cur.execute("SELECT set_limit(%s::real)", (threshold,))
                cur.execute(sql, params)
                rows = cur.fetchall()
            except Exception:
                raised = True
                # Clear the aborted transaction state so the reset below
                # actually executes. set_limit() is session-scoped, not
                # transactional — rollback does NOT undo it.
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise
            finally:
                # Restore the default. set_limit() works across all pg_trgm
                # versions we deploy on, vs RESET which can fail on older
                # builds. After a rollback this runs on a clean session.
                try:
                    cur.execute("SELECT set_limit(%s::real)", (DEFAULT_THRESHOLD,))
                except Exception:
                    # Last-ditch: if the connection is too broken to reset,
                    # discard it on the way out so the pool throws it away
                    # instead of handing the leaked threshold to the next
                    # caller. close() flips conn.closed=1, which the
                    # get_conn() context manager checks before putconn().
                    if raised:
                        try:
                            conn.close()
                        except Exception:
                            pass
        if not raised:
            conn.commit()
        return rows
from search_normalization import (
    detect_query_type,
    extract_cbe_digits,
    ilike_escape,
    normalize_name as normalize_name_v2,
    reversed_key,
    tokenize,
)
from ._helpers import _serialize_row

logger = logging.getLogger(__name__)
router = APIRouter()


# Bilingual / English aliases for major Belgian municipalities. KBO
# stores names in NL + FR only, so a user typing "Ghent" or "Antwerp"
# would otherwise miss every hit. Bidirectional pairs cover the
# cross-language case (NL ↔ FR ↔ EN). Lowercased on both sides.
MUNICIPALITY_ALIASES: dict[str, list[str]] = {
    "ghent":     ["gent", "gand"],
    "gent":      ["ghent", "gand"],
    "gand":      ["gent", "ghent"],
    "antwerp":   ["antwerpen", "anvers"],
    "antwerpen": ["antwerp", "anvers"],
    "anvers":    ["antwerp", "antwerpen"],
    "brussels":  ["brussel", "bruxelles"],
    "brussel":   ["brussels", "bruxelles"],
    "bruxelles": ["brussels", "brussel"],
    "bruges":    ["brugge"],
    "brugge":    ["bruges"],
    "liege":     ["liège", "luik"],
    "liège":     ["liege", "luik"],
    "luik":      ["liege", "liège"],
    "louvain":   ["leuven"],
    "leuven":    ["louvain"],
    "mechelen":  ["malines"],
    "malines":   ["mechelen"],
    "kortrijk":  ["courtrai"],
    "courtrai":  ["kortrijk"],
    "namur":     ["namen"],
    "namen":     ["namur"],
    "mons":      ["bergen"],
    "bergen":    ["mons"],
    "tournai":   ["doornik"],
    "doornik":   ["tournai"],
    "ostend":    ["oostende"],
    "oostende":  ["ostend"],
    "ypres":     ["ieper"],
    "ieper":     ["ypres"],
}


def expand_municipality(name: str) -> list[str]:
    """Return the input + any known multilingual aliases (deduped)."""
    name_lc = name.lower().strip()
    variants = [name_lc]
    for v in MUNICIPALITY_ALIASES.get(name_lc, []):
        if v not in variants:
            variants.append(v)
    return variants


def _build_loc_clauses(
    pc_filter: Optional[str],
    muni_filter: Optional[str],
    street_filter: Optional[str],
    params: dict[str, Any],
) -> list[str]:
    """Build the AND-joined WHERE clauses for a location-filter CTE.
    Mutates `params` to add the required psycopg2 bindings. Returns the
    list of safe column-level clauses; callers join with " AND ".
    All user-controlled values are bound — no string interpolation.
    """
    clauses: list[str] = []
    if pc_filter:
        clauses.append("a.zipcode ILIKE %(loc_postal)s ESCAPE '\\'")
        params["loc_postal"] = ilike_escape(pc_filter) + "%"
    if muni_filter:
        variants = expand_municipality(muni_filter)
        or_parts: list[str] = []
        for i, v in enumerate(variants):
            key = f"loc_muni_{i}"
            params[key] = f"%{ilike_escape(v)}%"
            or_parts.append(
                f"a.municipality_nl ILIKE %({key})s ESCAPE '\\'"
                f" OR a.municipality_fr ILIKE %({key})s ESCAPE '\\'"
            )
        clauses.append("(" + " OR ".join(or_parts) + ")")
    if street_filter:
        clauses.append(
            "(a.street_nl ILIKE %(loc_street)s ESCAPE '\\'"
            " OR a.street_fr ILIKE %(loc_street)s ESCAPE '\\')"
        )
        params["loc_street"] = f"%{ilike_escape(street_filter)}%"
    return clauses


# ---------------------------------------------------------------------------
# GET /api/companies/search?q=...  —  search V2
# ---------------------------------------------------------------------------

@router.get("/search")
async def search_companies(
    q: Optional[str] = Query(None, max_length=200),
    limit: int = Query(20, ge=1, le=50),
    postal_code: Optional[str] = Query(None, max_length=10),
    municipality: Optional[str] = Query(None, max_length=100),
    street: Optional[str] = Query(None, max_length=200),
):
    """Unified company search returning `{commercial, nonprofit_or_public}`.

    Short-circuits on CBE / VAT inputs. Otherwise runs a single scored
    SQL query and buckets by juridical_form_category.

    Optional location filters (postal_code / municipality / street) narrow
    the result set to companies whose registered address matches ALL
    provided filters. They work two ways:
      - alongside `q`: narrow the name search to that location
      - alone: browse top active companies in that location, no name term
        needed (sorted by revenue desc)

    Multilingual municipality names are handled — "Ghent", "Gent", and
    "Gand" all match the same city.
    """
    raw = (q or "").strip()
    pc = (postal_code or "").strip().lower() or None
    muni = (municipality or "").strip().lower() or None
    street_v = (street or "").strip().lower() or None
    has_loc = bool(pc or muni or street_v)

    if not raw and not has_loc:
        return _empty_response(raw)

    # Location-only browse — no `q`, just filter by REGO address.
    if not raw:
        return _search_location_only_cached(int(limit), pc, muni, street_v)

    # Cache by lowercased (q, limit, location-filter) tuple. Same
    # rationale as /api/people/search: typing-burst queries repeat
    # within 60s, the underlying KBO/NBB data updates daily at most,
    # and the post-CTE LATERAL JOIN + pg_trgm cost dominates.
    return _search_companies_cached(
        raw.lower(),
        int(limit),
        pc,
        muni,
        street_v,
    )


@ttl_cache(ttl_seconds=60, maxsize=2048)
def _search_companies_cached(
    raw: str,
    limit: int,
    pc_filter: Optional[str],
    muni_filter: Optional[str],
    street_filter: Optional[str],
) -> dict:
    """Memoised core. All args are primitive + hashable so the
    cache key is well-defined. Lowercasing in the wrapper keeps "Acme"
    and "acme" sharing one cache row."""

    # Filter values are already trimmed + lower-cased + None-coalesced
    # by the wrapper. ILIKE is case-insensitive so the lowercased copy
    # produces the same row set as the original mixed-case input.
    has_location_filter = bool(pc_filter or muni_filter or street_filter)

    qtype = detect_query_type(raw)

    # CBE / VAT short-circuit — exact prefix lookup, no text search.
    if qtype == "cbe":
        digits = extract_cbe_digits(raw) or ""
        # 9-digit CBEs (rare — KBO sometimes drops the leading zero on
        # display) are zero-padded by extract_cbe_digits. Prefix-match
        # on the first 9 digits too, so "403170701" still surfaces the
        # canonical "0403170701" record.
        pfx_candidates = [f"{digits}%"]
        if digits.startswith("0") and len(digits) == 10:
            pfx_candidates.append(f"{digits[1:]}%")
        try:
            rows: list[dict] = []
            seen: set[str] = set()
            for pfx in pfx_candidates:
                for r in fetch_all(_CBE_SQL, (pfx,)):
                    if r["enterprise_number"] in seen:
                        continue
                    seen.add(r["enterprise_number"])
                    rows.append(r)
        except Exception:
            logger.exception("CBE lookup failed for q=%r", raw[:80])
            raise HTTPException(500, "search_failed")
        return _build_response(raw, rows)

    # Text search. Normalise + tokenise once. Wildcard-escape each
    # value before wrapping in `%…%` so user-supplied `%`/`_`/`\` are
    # matched literally rather than doing a full-table scan.
    nq = normalize_name_v2(raw)
    tokens = tokenize(raw)
    # Up to 4 tokens. Extras collapse into the trigram / prefix paths.
    tok1 = f"%{ilike_escape(tokens[0])}%" if len(tokens) >= 1 else None
    tok2 = f"%{ilike_escape(tokens[1])}%" if len(tokens) >= 2 else None
    tok3 = f"%{ilike_escape(tokens[2])}%" if len(tokens) >= 3 else None
    tok4 = f"%{ilike_escape(tokens[3])}%" if len(tokens) >= 4 else None
    n_tokens = len(tokens)
    # Address fallback gated to ≥6 chars (was 4 — too loose, triggered
    # full-scan `address` ILIKE on a single letter). Person-like queries
    # don't need address fallback at all.
    #
    # Note: `migrations/2026-04-26_address_trgm.sql` is now applied (GIN
    # trigram indexes on street/municipality REGO rows). Lowering this
    # gate to ≥4 is a future tuning task — needs a load test first.
    addr_like = (
        f"%{ilike_escape(raw)}%"
        if len(raw) >= 6 and qtype != "person_like"
        else None
    )
    zip_q = raw if qtype == "zipcode" else None

    params: dict[str, Any] = {
        "nq": nq,
        "nq_prefix": (nq + "%") if nq else None,
        "tok1": tok1,
        "tok2": tok2,
        "tok3": tok3,
        "tok4": tok4,
        "n_tokens": n_tokens,
        "addr_like": addr_like,
        "zip_q": zip_q,
        "limit": max(limit, 20),
    }

    # Assemble the optional location-filter CTE. Kept out of the baseline
    # SQL so the common no-filter path runs exactly the same plan. All
    # user values go through %(name)s bindings — the only interpolation
    # is the AND-joined list of safe column-level clauses.
    loc_filter_cte = ""
    loc_filter_join = ""
    if has_location_filter:
        loc_clauses = _build_loc_clauses(
            pc_filter, muni_filter, street_filter, params
        )
        loc_filter_cte = (
            ", loc_filter AS (\n"
            "    SELECT DISTINCT a.entity_number AS enterprise_number\n"
            "    FROM address a\n"
            "    WHERE a.type_of_address = 'REGO'\n"
            "      AND " + "\n      AND ".join(loc_clauses) + "\n"
            "    LIMIT 5000\n"
            ")\n"
        )
        loc_filter_join = (
            "JOIN loc_filter lf ON lf.enterprise_number = h.enterprise_number"
        )

    sql = _SEARCH_SQL.replace("__LOC_FILTER_CTE__", loc_filter_cte)
    sql = sql.replace("__LOC_FILTER_JOIN__", loc_filter_join)

    try:
        # Force pg_trgm.similarity_threshold to 0.5 for THIS cursor.
        # Without it, short common queries like "dela" return 80k+
        # bitmap candidates (default threshold 0.3) and the recheck
        # eats ~1-2 s even though the final similarity > 0.35 filter
        # discards most of them. ALTER DATABASE sets this at DB-level
        # too; this guard keeps search fast if that ever gets RESET
        # by maintenance. Runs on the same cursor as the main query
        # so the session setting is guaranteed in effect.
        rows = _search_with_trgm_threshold(sql, params, 0.5)
    except Exception:
        logger.exception("company search V2 failed for q=%r", raw[:80])
        raise HTTPException(500, "search_failed")

    return _build_response(raw, rows)


# ---------------------------------------------------------------------------
# Location-only browse — no `q`, just filter by REGO address
# ---------------------------------------------------------------------------

@ttl_cache(ttl_seconds=60, maxsize=512)
def _search_location_only_cached(
    limit: int,
    pc_filter: Optional[str],
    muni_filter: Optional[str],
    street_filter: Optional[str],
) -> dict:
    """Browse active companies whose registered address (REGO) matches
    the supplied location filters, ranked by revenue. Used when the
    operator fills the `/search` location boxes but leaves the main
    query empty."""
    if not (pc_filter or muni_filter or street_filter):
        return _empty_response("")

    params: dict[str, Any] = {"limit": max(limit, 20)}
    loc_clauses = _build_loc_clauses(
        pc_filter, muni_filter, street_filter, params
    )
    if not loc_clauses:
        return _empty_response("")

    sql = _LOC_ONLY_SQL.replace(
        "__LOC_CLAUSES__", "\n      AND ".join(loc_clauses)
    )

    try:
        rows = fetch_all(sql, params)
    except Exception:
        logger.exception(
            "location-only search failed for pc=%r muni=%r street=%r",
            pc_filter, muni_filter, street_filter,
        )
        raise HTTPException(500, "search_failed")

    return _build_response("", rows)


# Location-only browse SQL. Same column shape as the scored path so
# `_serialize_row` + `_build_response` keep working unchanged.
#
# Ranking happens INSIDE the loc_filter CTE: per-entity DISTINCT ON
# folds duplicate REGO rows, then we ORDER BY revenue and LIMIT 5000.
# This guarantees the top-revenue companies in a given location aren't
# dropped by an arbitrary slice for big cities (Brussels REGO is
# ~60K rows; without inner sorting the outer LIMIT would see a random
# 5000 of them and miss the biggest names).
#
# No status filter — PE sourcing benefits from seeing dissolved /
# in-liquidation companies too. The status chip on the profile page
# (#35) makes the lifecycle stage obvious at a glance.
_LOC_ONLY_SQL = """
WITH loc_filter AS (
    SELECT enterprise_number, sort_rev
    FROM (
        SELECT DISTINCT ON (a.entity_number)
               a.entity_number               AS enterprise_number,
               COALESCE(fl.revenue, 0)::bigint AS sort_rev
        FROM address a
        LEFT JOIN financial_latest fl ON fl.enterprise_number = a.entity_number
        WHERE a.type_of_address = 'REGO'
          AND __LOC_CLAUSES__
        ORDER BY a.entity_number, COALESCE(fl.revenue, 0) DESC NULLS LAST
    ) per_entity
    ORDER BY sort_rev DESC NULLS LAST
    LIMIT 5000
)
SELECT
    e.enterprise_number,
    COALESCE(ci.name, d.denomination, e.enterprise_number) AS name,
    e.status,
    e.juridical_form,
    COALESCE(jfc.category, 'commercial')                AS form_category,
    ci.city,
    COALESCE(nl.description, ci.nace_code)              AS sector,
    e.start_date,
    fl.revenue, fl.ebitda,
    CASE WHEN fl.revenue > 0
         THEN ROUND((fl.ebitda / fl.revenue * 100)::numeric, 1)
    END AS ebitda_margin_pct,
    fl.fte_total, fl.fiscal_year,
    1.0::real AS score
FROM loc_filter lf
JOIN enterprise e                     ON e.enterprise_number = lf.enterprise_number
LEFT JOIN company_info ci             ON ci.enterprise_number = lf.enterprise_number
LEFT JOIN LATERAL (
    SELECT denomination
    FROM denomination d2
    WHERE d2.entity_number = lf.enterprise_number
      AND d2.type_of_denomination = '001'
      AND d2.language IN ('2', '1')
    ORDER BY CASE d2.language WHEN '2' THEN 1 WHEN '1' THEN 2 ELSE 3 END
    LIMIT 1
) d                                   ON TRUE
LEFT JOIN financial_latest fl         ON fl.enterprise_number = lf.enterprise_number
LEFT JOIN nace_lookup nl              ON nl.nace_code = ci.nace_code
LEFT JOIN juridical_form_category jfc ON jfc.code = e.juridical_form
ORDER BY lf.sort_rev DESC NULLS LAST,
         e.enterprise_number
LIMIT %(limit)s
"""


# ---------------------------------------------------------------------------
# Response shaping
# ---------------------------------------------------------------------------

def _empty_response(q: str) -> dict[str, Any]:
    return {
        "q": q,
        "commercial": [],
        "nonprofit_or_public": [],
        "total": {"commercial": 0, "nonprofit_or_public": 0},
    }


def _build_response(q: str, rows: list[dict]) -> dict[str, Any]:
    commercial: list[dict] = []
    nonprofit: list[dict] = []
    for raw_row in rows:
        row = _serialize_row(raw_row)
        cat = (row.get("form_category") or "commercial").lower()
        # `other` (foreign entities, condominiums) goes in the
        # demoted bucket — PE analysts don't usually care about them.
        if cat in ("nonprofit", "public", "other"):
            nonprofit.append(row)
        else:
            commercial.append(row)
    return {
        "q": q,
        "commercial": commercial[:20],
        "nonprofit_or_public": nonprofit[:10],
        "total": {
            "commercial": len(commercial),
            "nonprofit_or_public": len(nonprofit),
        },
    }


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

# CBE prefix path. %s is bound to the pattern (`"0403170701%"`).
_CBE_SQL = """
SELECT
    e.enterprise_number,
    COALESCE(ci.name, e.enterprise_number)              AS name,
    e.status,
    e.juridical_form,
    COALESCE(jfc.category, 'commercial')                AS form_category,
    ci.city,
    COALESCE(nl.description, ci.nace_code)              AS sector,
    e.start_date,
    fl.revenue, fl.ebitda,
    CASE WHEN fl.revenue > 0
         THEN ROUND((fl.ebitda / fl.revenue * 100)::numeric, 1)
    END AS ebitda_margin_pct,
    fl.fte_total, fl.fiscal_year,
    1.0::real AS score
FROM enterprise e
LEFT JOIN company_info ci   ON ci.enterprise_number = e.enterprise_number
LEFT JOIN financial_latest fl ON fl.enterprise_number = e.enterprise_number
LEFT JOIN nace_lookup nl    ON nl.nace_code = ci.nace_code
LEFT JOIN juridical_form_category jfc ON jfc.code = e.juridical_form
WHERE e.enterprise_number LIKE %s
ORDER BY e.enterprise_number
LIMIT 30
"""


# Scored text-search CTE. The six arms union into a single candidate
# set; MAX(score) dedupes on enterprise_number; final ranking applies
# quality + popularity multipliers.
#
# SAFETY: every user-controlled value is bound via named parameters
# (%(name)s). No f-strings or string concatenation into the SQL body.
# The ILIKE patterns (tok1..tok4, addr_like) are pre-wrapped in Python
# with the user's tokens, and pg_trgm % operator uses bound values.
_SEARCH_SQL = """
WITH
exact_match AS (
    SELECT ci.enterprise_number, 1.0::real AS base
    FROM company_info ci
    WHERE %(nq)s IS NOT NULL
      AND ci.name_normalized = %(nq)s
),
prefix_match AS (
    SELECT ci.enterprise_number, 0.7::real AS base
    FROM company_info ci
    WHERE %(nq_prefix)s IS NOT NULL
      AND ci.name_normalized LIKE %(nq_prefix)s
      AND ci.name_normalized <> %(nq)s
    LIMIT 200
),
token_and AS (
    SELECT ci.enterprise_number, 0.5::real AS base
    FROM company_info ci
    WHERE %(n_tokens)s >= 1
      AND ci.name_normalized IS NOT NULL
      AND (%(tok1)s IS NULL OR ci.name_normalized ILIKE %(tok1)s ESCAPE '\\')
      AND (%(tok2)s IS NULL OR ci.name_normalized ILIKE %(tok2)s ESCAPE '\\')
      AND (%(tok3)s IS NULL OR ci.name_normalized ILIKE %(tok3)s ESCAPE '\\')
      AND (%(tok4)s IS NULL OR ci.name_normalized ILIKE %(tok4)s ESCAPE '\\')
    LIMIT 200
),
denom_exact AS (
    -- Exact-equality match on a trade name (denomination). This is
    -- what surfaces e.g. "Viconco" when the user types "viconco" but
    -- the canonical company_info.name is blank or different. Scored
    -- high (0.85) — above prefix-on-name (0.7) — because a full-name
    -- match on the trade-name register is a near-certain hit.
    SELECT d.entity_number AS enterprise_number, 0.85::real AS base
    FROM denomination d
    WHERE %(nq)s IS NOT NULL
      AND length(%(nq)s) >= 3
      AND d.type_of_denomination IN ('001', '002', '003')
      AND d.denomination_normalized = %(nq)s
    LIMIT 50
),
denom_fuzzy AS (
    -- Fuzzy trigram fallback on denomination — gated to ≥4 chars and
    -- only fires when the exact arm above doesn't already have the
    -- name. Scored 0.4 so it sits below the company_info fuzzy arm.
    SELECT d.entity_number AS enterprise_number, 0.4::real AS base
    FROM denomination d
    WHERE %(nq)s IS NOT NULL
      AND length(%(nq)s) >= 4
      AND d.type_of_denomination = '001'
      AND d.language IN ('2', '1')
      AND d.denomination_normalized IS NOT NULL
      AND d.denomination_normalized %% %(nq)s
      AND similarity(d.denomination_normalized, %(nq)s) > 0.45
    LIMIT 100
),
trigram_match AS (
    -- Trigram fuzzy fallback. Gated to ≥4 chars + stricter threshold
    -- (0.35, up from 0.3) so short queries like "Ann" don't fan out
    -- to every "Anna/Ann/Anne/Annie" in a 170K-row table.
    SELECT ci.enterprise_number,
           LEAST(0.4, similarity(ci.name_normalized, %(nq)s))::real AS base
    FROM company_info ci
    WHERE %(nq)s IS NOT NULL
      AND length(%(nq)s) >= 4
      AND ci.name_normalized %% %(nq)s
      AND similarity(ci.name_normalized, %(nq)s) > 0.35
    LIMIT 200
),
addr_match AS (
    SELECT a.entity_number AS enterprise_number, 0.2::real AS base
    FROM address a
    WHERE a.type_of_address = 'REGO'
      AND %(addr_like)s IS NOT NULL
      AND (
          a.street_nl          ILIKE %(addr_like)s ESCAPE '\\'
          OR a.street_fr       ILIKE %(addr_like)s ESCAPE '\\'
          OR a.municipality_nl ILIKE %(addr_like)s ESCAPE '\\'
          OR a.municipality_fr ILIKE %(addr_like)s ESCAPE '\\'
          OR (%(zip_q)s IS NOT NULL AND a.zipcode = %(zip_q)s)
      )
    LIMIT 500
),
all_hits AS (
    SELECT enterprise_number, MAX(base) AS base FROM (
        SELECT * FROM exact_match
        UNION ALL SELECT * FROM prefix_match
        UNION ALL SELECT * FROM token_and
        UNION ALL SELECT * FROM denom_exact
        UNION ALL SELECT * FROM denom_fuzzy
        UNION ALL SELECT * FROM trigram_match
        UNION ALL SELECT * FROM addr_match
    ) u
    GROUP BY enterprise_number
)
__LOC_FILTER_CTE__
SELECT
    h.enterprise_number,
    COALESCE(ci.name, d.denomination, h.enterprise_number) AS name,
    e.status,
    e.juridical_form,
    COALESCE(jfc.category, 'commercial') AS form_category,
    ci.city,
    COALESCE(nl.description, ci.nace_code) AS sector,
    e.start_date,
    fl.revenue, fl.ebitda,
    CASE WHEN fl.revenue > 0
         THEN ROUND((fl.ebitda / fl.revenue * 100)::numeric, 1)
    END AS ebitda_margin_pct,
    fl.fte_total, fl.fiscal_year,
    (
        h.base
        * (1 + 0.15 * ln(GREATEST(10, COALESCE(fl.revenue, 0) + 10)) / ln(10))
        * CASE WHEN COALESCE(e.status, '') = 'AC' THEN 1.0 ELSE 0.3 END
        * (1 + 0.10 * LEAST(1.0, COALESCE(cp.click_count, 0) / 50.0))
    )::real AS score
FROM all_hits h
__LOC_FILTER_JOIN__
JOIN enterprise e                     ON e.enterprise_number = h.enterprise_number
LEFT JOIN company_info ci             ON ci.enterprise_number = h.enterprise_number
LEFT JOIN LATERAL (
    SELECT denomination
    FROM denomination d2
    WHERE d2.entity_number = h.enterprise_number
      AND d2.type_of_denomination = '001'
      AND d2.language IN ('2', '1')
    ORDER BY CASE d2.language WHEN '2' THEN 1 WHEN '1' THEN 2 ELSE 3 END
    LIMIT 1
) d                                   ON TRUE
LEFT JOIN financial_latest fl         ON fl.enterprise_number = h.enterprise_number
LEFT JOIN nace_lookup nl              ON nl.nace_code = ci.nace_code
LEFT JOIN juridical_form_category jfc ON jfc.code = e.juridical_form
LEFT JOIN company_popularity cp       ON cp.enterprise_number = h.enterprise_number
ORDER BY score DESC,
         COALESCE(fl.revenue, 0) DESC,
         name
LIMIT %(limit)s
"""


# ---------------------------------------------------------------------------
# Legacy endpoints — preserved unchanged for backward compatibility.
# Existing callers (semantic search tab, admin tooling) continue to work.
# ---------------------------------------------------------------------------

# GET /api/companies/semantic-search?q=...
@router.get("/semantic-search")
async def semantic_search(q: str = Query(..., min_length=1)):
    """Fuzzy / semantic company search using pg_trgm trigram similarity."""
    query = q.strip()
    nq = normalize_name(query)

    try:
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
                   GREATEST(
                       similarity(ci.name_normalized, %s),
                       similarity(ci.name, %s)
                   ) AS score
            FROM company_info ci
            JOIN enterprise e ON e.enterprise_number = ci.enterprise_number
            LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
            LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
            WHERE ci.name_normalized %% %s
               OR ci.name ILIKE %s
            ORDER BY score DESC, ci.name
            LIMIT 25
        """, (nq or query, query, nq or query, f"%{query}%"))

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
                    LIMIT 50
                """, (f"%{query}%",))
        except Exception:
            pass

        seen = set()
        merged = []
        for row in trgm_rows + emb_rows:
            cbe = row["enterprise_number"]
            if cbe not in seen:
                seen.add(cbe)
                merged.append(row)
        for row in merged:
            row.pop("score", None)
        return [_serialize_row(r) for r in merged[:25]]

    except Exception:
        logger.exception("Semantic search failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# GET /api/companies/fuzzy-match?name=...&threshold=0.3&limit=10
@router.get("/fuzzy-match")
async def fuzzy_match(
    name: str = Query(..., min_length=1),
    threshold: float = Query(0.3, ge=0.1, le=1.0),
    limit: int = Query(10, ge=1, le=50),
):
    """Fuzzy entity matching using pg_trgm on name_normalized."""
    normalized_query = normalize_name(name.strip())
    if not normalized_query:
        return []
    try:
        rows = fetch_all("""
            SELECT ci.enterprise_number, ci.name, ci.city, ci.nace_code,
                   COALESCE(nl.description, ci.nace_code) AS sector,
                   fl.revenue, fl.ebitda, fl.fte_total, fl.fiscal_year,
                   similarity(ci.name_normalized, %s) AS score
            FROM company_info ci
            LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
            LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
            WHERE ci.name_normalized IS NOT NULL
              AND similarity(ci.name_normalized, %s) > %s
            ORDER BY score DESC
            LIMIT %s
        """, (normalized_query, normalized_query, threshold, limit))
        return [_serialize_row(r) for r in rows]
    except Exception:
        logger.exception("Fuzzy match failed")
        raise HTTPException(status_code=500, detail="Internal server error")
