"""Companies routers — shared helpers, constants, and prompt templates."""

import logging
from collections import defaultdict
from typing import Optional

import psycopg2.extras

from db import fetch_all, fetch_one, get_conn
from utils import clean_cbe

logger = logging.getLogger(__name__)


ROLE_LABELS = {
    "fct:m10": "Director", "fct:m11": "Managing director",
    "fct:m12": "Chairman", "fct:m13": "Administrator",
    "fct:m14": "Secretary", "fct:m15": "Treasurer",
    "fct:m20": "Statutory auditor", "fct:m30": "Liquidator",
    "fct:m40": "Daily management",
}

MAX_NETWORK_NODES = 200

MAX_DEEP_NETWORK_NODES = 100

STAATSBLAD_BASE = "https://www.ejustice.just.fgov.be"

ADMIN_EXTRACTION_PROMPT = """Given this Belgian Staatsblad (Official Gazette) publication about board changes for company {name} (CBE {cbe}):

{pdf_text}

Extract all person names and their roles (e.g. Bestuurder, Zaakvoerder, Gedelegeerd bestuurder, Vaste vertegenwoordiger, etc).
Return JSON:
{{
  "appointments": [{{"name": "Full Name", "role": "Bestuurder"}}],
  "resignations": [{{"name": "Full Name", "role": "Bestuurder"}}]
}}
Return only the JSON, no markdown fences."""


def _clean_cbe(identifier) -> Optional[str]:
    """Strip dots/spaces from identifier, return 10-digit CBE or None."""
    if not identifier:
        return None
    c = clean_cbe(identifier)
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


def _resolve_nace_label(
    nace_code: Optional[str],
    preferred_version: Optional[str] = "2008",
) -> Optional[str]:
    """Resolve one NACE code to a display label.

    Prefer the requested KBO version when we know it, then fall back to the
    legacy static lookup so older rows still display something useful.
    """
    if not nace_code:
        return None

    preferred_category = f"Nace{preferred_version}" if preferred_version else None
    row = fetch_one(
        """
        SELECT COALESCE(
            preferred_nl.description,
            preferred_fr.description,
            preferred_en.description,
            legacy.description,
            q.nace_code
        ) AS description
        FROM (SELECT %s AS nace_code, %s AS preferred_category) q
        LEFT JOIN code preferred_nl
               ON preferred_nl.category = q.preferred_category
              AND preferred_nl.code = q.nace_code
              AND preferred_nl.language = 'NL'
        LEFT JOIN code preferred_fr
               ON preferred_fr.category = q.preferred_category
              AND preferred_fr.code = q.nace_code
              AND preferred_fr.language = 'FR'
        LEFT JOIN code preferred_en
               ON preferred_en.category = q.preferred_category
              AND preferred_en.code = q.nace_code
              AND preferred_en.language = 'EN'
        LEFT JOIN nace_lookup legacy ON legacy.nace_code = q.nace_code
        """,
        (nace_code, preferred_category),
    )
    return row["description"] if row else nace_code


def _fetch_connections(cbes: list, include_historical: bool = False) -> tuple:
    """Batch-fetch subsidiaries and shareholders for a set of CBEs.

    When ``include_historical`` is False (the default) we keep only rows
    from each enterprise's most recent fiscal_year — so the spider web
    shows only the present cap-table / participation list. Older filings
    represent past ownership snapshots and just clutter the graph.
    """
    if not cbes:
        return [], []
    with get_conn() as conn:
        ph = ",".join(["%s"] * len(cbes))
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        if include_historical:
            cur.execute(
                f"SELECT DISTINCT enterprise_number, name, identifier, ownership_pct, country "
                f"FROM participating_interest WHERE enterprise_number IN ({ph})",
                list(cbes),
            )
        else:
            cur.execute(
                f"WITH latest AS ("
                f"  SELECT enterprise_number, MAX(fiscal_year) AS fy "
                f"  FROM participating_interest WHERE enterprise_number IN ({ph}) "
                f"  GROUP BY enterprise_number"
                f") "
                f"SELECT DISTINCT pi.enterprise_number, pi.name, pi.identifier, "
                f"       pi.ownership_pct, pi.country "
                f"FROM participating_interest pi "
                f"JOIN latest l ON l.enterprise_number = pi.enterprise_number "
                f"             AND l.fy = pi.fiscal_year",
                list(cbes),
            )
        subs = [dict(r) for r in cur.fetchall()]

        if include_historical:
            cur.execute(
                f"SELECT DISTINCT enterprise_number, name, identifier, ownership_pct, shareholder_type "
                f"FROM shareholder WHERE enterprise_number IN ({ph})",
                list(cbes),
            )
        else:
            cur.execute(
                f"WITH latest AS ("
                f"  SELECT enterprise_number, MAX(fiscal_year) AS fy "
                f"  FROM shareholder WHERE enterprise_number IN ({ph}) "
                f"  GROUP BY enterprise_number"
                f") "
                f"SELECT DISTINCT s.enterprise_number, s.name, s.identifier, "
                f"       s.ownership_pct, s.shareholder_type "
                f"FROM shareholder s "
                f"JOIN latest l ON l.enterprise_number = s.enterprise_number "
                f"             AND l.fy = s.fiscal_year",
                list(cbes),
            )
        shs = [dict(r) for r in cur.fetchall()]

        cur.close()
        conn.commit()
        return subs, shs


def _fetch_latest_nbb_admins_batch(
    cbes: list[str], by_identifier: bool = False
) -> dict[str, list[dict]]:
    """For each CBE in `cbes`, return its admins from the LATEST NBB
    annual-filing snapshot.

    "Latest" = highest financial_summary.deposit_date for the company,
    falling back to lexicographic deposit_key when deposit_date is
    missing. Mirrors the snapshot logic in
    backend/routers/companies/structure.py — the admins tab.

    `sb_*` deposit_keys (legacy Staatsblad-sourced rows from the old
    /extract-admins endpoint) are excluded so the snapshot is NBB-only.

    With ``by_identifier=True`` the WHERE clause filters by
    administrator.identifier instead of enterprise_number — used for the
    reverse-direction BFS lookup ("which companies currently name this
    CBE as an admin"). Returns dict keyed by enterprise_number either way.
    """
    if not cbes:
        return {}
    ph = ",".join(["%s"] * len(cbes))
    scope = f"a.identifier IN ({ph})" if by_identifier else f"a.enterprise_number IN ({ph})"
    rows = fetch_all(
        rf"""
        WITH candidates AS (
            SELECT a.enterprise_number, a.deposit_key
            FROM administrator a
            WHERE {scope}
              AND a.deposit_key NOT LIKE 'sb\_%%' ESCAPE '\'
        ),
        latest AS (
            -- Bypass the `financial_summary` view: it aggregates the entire
            -- 39M-row `financial_data` table at query time, which forces a
            -- full seq-scan + on-disk hash-aggregate for batch lookups
            -- (~50s for 6 CBEs). Joining `financial_data` directly with
            -- predicate-pushdown on enterprise_number uses idx_admin_ent +
            -- financial_data_pkey and runs in <30ms.
            SELECT DISTINCT ON (a.enterprise_number)
                   a.enterprise_number,
                   a.deposit_key AS dk,
                   MAX(fd.deposit_date) AS deposit_date
            FROM administrator a
            JOIN candidates c
              ON c.enterprise_number = a.enterprise_number
            LEFT JOIN financial_data fd
              ON fd.enterprise_number = a.enterprise_number
             AND fd.deposit_key = a.deposit_key
             AND fd.period = 'N'
            WHERE a.deposit_key NOT LIKE 'sb\_%%' ESCAPE '\'
            GROUP BY a.enterprise_number, a.deposit_key
            ORDER BY a.enterprise_number,
                     MAX(fd.deposit_date) DESC NULLS LAST,
                     a.deposit_key DESC
        )
        SELECT DISTINCT ON (a.enterprise_number, a.name, a.role)
               a.enterprise_number, a.name, a.role, a.person_type,
               a.identifier, a.mandate_start, a.mandate_end,
               a.fiscal_year, a.deposit_key, l.deposit_date
        FROM administrator a
        JOIN latest l ON l.enterprise_number = a.enterprise_number
                     AND l.dk = a.deposit_key
        ORDER BY a.enterprise_number, a.name, a.role
        """,
        list(cbes),
    )
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["enterprise_number"]].append(row)
    return grouped


def _fetch_admin_events_batch(cbes: list[str]) -> dict[str, list[dict]]:
    """Fetch all admin_event rows from staatsblad_event for the batch,
    grouped by enterprise_number. Returns events in chronological order
    (the merge logic in structure_merge.py re-sorts anyway, but the order
    keeps debugging readable)."""
    if not cbes:
        return {}
    ph = ",".join(["%s"] * len(cbes))
    rows = fetch_all(
        f"""
        SELECT enterprise_number, id, pub_reference, pub_date, event_type,
               sub_type, event_date, person_name, person_role, entity_name,
               summary
        FROM staatsblad_event
        WHERE enterprise_number IN ({ph})
          AND event_type = 'admin_event'
        ORDER BY enterprise_number, pub_date ASC, id ASC
        """,
        list(cbes),
    )
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["enterprise_number"]].append(row)
    return grouped


def fetch_current_admins_for_batch(cbes: list[str]) -> list[dict]:
    """Return the merged "current admin" list for each CBE in the batch.

    Logic mirrors GET /api/companies/{cbe}/structure (the admins tab):
    the latest NBB filing is the baseline snapshot; later Staatsblad
    appointment / resignation / renewal events are layered on top.
    Older Staatsblad events that pre-date the NBB snapshot are ignored
    (they're already reflected in NBB).

    Returns a flat list of admin dicts, each shaped like the NBB
    administrator row (enterprise_number, name, role, person_type,
    identifier, mandate_start, mandate_end, fiscal_year, deposit_key)
    plus extra annotations (source, as_of, role_label) from the merge.
    """
    if not cbes:
        return []
    # Local import to avoid circular module load — structure_merge has
    # no project deps but _helpers is imported very early in the routers
    # package init chain.
    from .structure_merge import merge_admins_with_staatsblad

    import datetime as _dt

    nbb_by_ent = _fetch_latest_nbb_admins_batch(cbes)
    sb_by_ent = _fetch_admin_events_batch(cbes)
    today = _dt.date.today().isoformat()

    result: list[dict] = []
    for ent_cbe in cbes:
        nbb_for_ent = nbb_by_ent.get(ent_cbe, [])
        sb_for_ent = sb_by_ent.get(ent_cbe, [])
        if not nbb_for_ent and not sb_for_ent:
            continue
        merged, _ = merge_admins_with_staatsblad(
            nbb_for_ent, sb_for_ent, role_labels=ROLE_LABELS
        )
        for admin in merged:
            # Skip admins whose term has already ended — this helper is the
            # "currently active" entry point used by the spiderweb's BFS.
            # The structure tab consumes the unfiltered merge directly so
            # past directors still appear there.
            mandate_end = admin.get("mandate_end")
            if mandate_end and str(mandate_end) <= today:
                continue
            # SB-only rows (created from events) lack enterprise_number —
            # the merge helper preserves it from the NBB seed but doesn't
            # set it for events. Stamp it here so downstream BFS code can
            # treat every row uniformly.
            admin.setdefault("enterprise_number", ent_cbe)
            result.append(admin)
    return result


def fetch_current_admin_companies_for_person(name: str) -> list[dict]:
    """Return enterprises where `name` is currently a director.

    Looks up every enterprise where the person/entity has an NBB row OR
    a Staatsblad admin_event, then runs the same NBB-snapshot + Staatsblad
    merge per enterprise to confirm the mandate is still active. Returns
    one row per (enterprise, role) with at least
    {enterprise_number, role}.
    """
    if not name:
        return []
    # Find candidate enterprises — anywhere this name appears as an admin
    # (NBB or Staatsblad). Case- and punctuation-insensitive match keeps
    # the spelling differences between the two sources from hiding rows.
    candidates = fetch_all(
        r"""
        SELECT DISTINCT enterprise_number
        FROM administrator
        WHERE LOWER(REGEXP_REPLACE(name, '[.,]', '', 'g'))
            = LOWER(REGEXP_REPLACE(%s, '[.,]', '', 'g'))
          AND deposit_key NOT LIKE 'sb\_%%' ESCAPE '\'
        UNION
        SELECT DISTINCT enterprise_number
        FROM staatsblad_event
        WHERE event_type = 'admin_event'
          AND LOWER(REGEXP_REPLACE(COALESCE(person_name, entity_name), '[.,]', '', 'g'))
            = LOWER(REGEXP_REPLACE(%s, '[.,]', '', 'g'))
        """,
        (name, name),
    )
    cbes = [c["enterprise_number"] for c in candidates if c.get("enterprise_number")]
    if not cbes:
        return []
    merged = fetch_current_admins_for_batch(cbes)
    # Filter to rows that match the queried name (case- and punctuation-
    # insensitive), since the merged list contains every admin of every
    # candidate company.
    import re

    def _norm(value: str) -> str:
        return re.sub(r"[.,]", "", (value or "")).lower()

    needle = _norm(name)
    return [row for row in merged if _norm(row.get("name", "")) == needle]


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
