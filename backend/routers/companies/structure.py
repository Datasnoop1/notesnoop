"""Companies structure router — admins, shareholders, PIs, Staatsblad extraction."""

import logging
from collections import OrderedDict
from time import time as _time

import httpx
from fastapi import APIRouter, HTTPException, Query, Response

from db import fetch_all, fetch_one, get_conn, get_connection, put_connection
from feature_flags import ownership_graph_read_enabled
from utils import clean_cbe
from ._helpers import (
    _serialize_row,
    ROLE_LABELS,
    STAATSBLAD_BASE,
)
from .structure_merge import merge_admins_with_staatsblad

logger = logging.getLogger(__name__)
router = APIRouter()


# In-process cache of recent extract-admins attempts. Profile visits can
# fire this endpoint repeatedly for the same CBE; we don't want to burn
# LLM calls every time a company genuinely has no extractable admins.
# Single-process scope is fine while we run one backend container — when
# we scale out, swap this for Redis/Postgres.
_ADMIN_EXTRACT_CACHE: "OrderedDict[str, tuple[float, int]]" = OrderedDict()
_ADMIN_EXTRACT_CACHE_TTL = 1800  # 30 min — re-try later in case Staatsblad gains a pub
_ADMIN_EXTRACT_CACHE_MAX = 10_000

# Cache the affiliation-table presence probe at module scope. The table
# either exists (post-migration) or doesn't, and it doesn't appear and
# disappear within a single backend process lifetime, so a single probe
# is enough — saves an extra round-trip on every /structure call.
_AFFILIATION_TABLE_PRESENT: bool | None = None


def _admin_extract_cache_skip(cbe: str) -> bool:
    """True if we recently tried this CBE and got 0 admins back."""
    entry = _ADMIN_EXTRACT_CACHE.get(cbe)
    if not entry:
        return False
    ts, count = entry
    if _time() - ts > _ADMIN_EXTRACT_CACHE_TTL:
        _ADMIN_EXTRACT_CACHE.pop(cbe, None)
        return False
    return count == 0


def _admin_extract_cache_record(cbe: str, count: int) -> None:
    if len(_ADMIN_EXTRACT_CACHE) >= _ADMIN_EXTRACT_CACHE_MAX:
        _ADMIN_EXTRACT_CACHE.popitem(last=False)
    _ADMIN_EXTRACT_CACHE[cbe] = (_time(), count)


_CHAIN_MAX_DEPTH = 3


def _fetch_ownership_graph_structure(cbe: str) -> tuple[list[dict], list[dict], list[dict]]:
    """Return shareholders, PIs, and parent companies from ownership_edge_current."""
    shareholders = fetch_all("""
        SELECT
            COALESCE(p.canonical_name, owner_d.denomination, oe.parent_name_raw, oe.parent_id) AS name,
            CASE
                WHEN oe.parent_kind = 'company' THEN oe.parent_id
                ELSE oe.parent_identifier_value
            END AS identifier,
            oe.pct AS ownership_pct,
            CASE WHEN oe.parent_kind = 'person' THEN 'individual' ELSE 'entity' END AS shareholder_type,
            NULL::real AS shares_held,
            oe.fiscal_year,
            oe.edge_kind AS ownership_source,
            oe.parent_kind
        FROM ownership_edge_current oe
        LEFT JOIN person p
          ON oe.parent_kind = 'person'
         AND p.person_id::text = oe.parent_id
        LEFT JOIN LATERAL (
            SELECT d.denomination
            FROM denomination d
            WHERE d.entity_number = oe.parent_id
              AND d.type_of_denomination = '001'
              AND d.language IN ('2', '1')
            ORDER BY CASE d.language WHEN '2' THEN 0 WHEN '1' THEN 1 ELSE 2 END
            LIMIT 1
        ) owner_d ON oe.parent_kind = 'company'
        WHERE oe.child_kind = 'company'
          AND oe.child_id = %s
        ORDER BY oe.source_rank ASC,
                 oe.pct DESC NULLS LAST,
                 name NULLS LAST
    """, (cbe,))

    participating_interests = fetch_all("""
        SELECT
            COALESCE(child_d.denomination, oe.child_id) AS name,
            oe.child_id AS identifier,
            oe.pct AS ownership_pct,
            'BE' AS country,
            NULL::real AS equity_value,
            NULL::real AS net_result,
            oe.fiscal_year,
            oe.edge_kind AS ownership_source
        FROM ownership_edge_current oe
        LEFT JOIN LATERAL (
            SELECT d.denomination
            FROM denomination d
            WHERE d.entity_number = oe.child_id
              AND d.type_of_denomination = '001'
              AND d.language IN ('2', '1')
            ORDER BY CASE d.language WHEN '2' THEN 0 WHEN '1' THEN 1 ELSE 2 END
            LIMIT 1
        ) child_d ON true
        WHERE oe.parent_kind = 'company'
          AND oe.parent_id = %s
          AND oe.child_kind = 'company'
          AND oe.child_id <> %s
        ORDER BY oe.source_rank ASC,
                 oe.pct DESC NULLS LAST,
                 name NULLS LAST
    """, (cbe, cbe))

    parent_companies = fetch_all("""
        SELECT
            oe.parent_id AS enterprise_number,
            oe.pct AS ownership_pct,
            'BE' AS country,
            oe.fiscal_year,
            COALESCE(owner_d.denomination, oe.parent_name_raw, oe.parent_id) AS name,
            oe.edge_kind AS ownership_source
        FROM ownership_edge_current oe
        LEFT JOIN LATERAL (
            SELECT d.denomination
            FROM denomination d
            WHERE d.entity_number = oe.parent_id
              AND d.type_of_denomination = '001'
              AND d.language IN ('2', '1')
            ORDER BY CASE d.language WHEN '2' THEN 0 WHEN '1' THEN 1 ELSE 2 END
            LIMIT 1
        ) owner_d ON true
        WHERE oe.child_kind = 'company'
          AND oe.child_id = %s
          AND oe.parent_kind = 'company'
          AND oe.parent_id <> %s
        ORDER BY oe.source_rank ASC,
                 oe.pct DESC NULLS LAST,
                 name NULLS LAST
    """, (cbe, cbe))

    return shareholders, participating_interests, parent_companies


def _build_representation_chains(
    admins: list[dict],
    affiliation_table_present: bool,
) -> list[dict]:
    """Attach `representation_chain` to each legal-entity admin.

    For every admin where person_type='legal' and identifier is set we
    resolve "who represents that entity" up to MAX depth 3 using two
    batch queries:

      1. administrator table  — active mandates (mandate_end IS NULL OR
         mandate_end >= TODAY) for all collected CBEs in one round-trip.
      2. affiliation table fallback — for CBEs that returned no rows from
         administrator, we try the affiliation table (most recent row).

    Cycle detection: we track the set of CBEs visited on the current
    path. If we encounter a CBE already in the path we mark that node
    with cycle=True and stop descending.

    Each ChainLink shape:
      { cbe: str|None, name: str, role: str|None,
        person_type: str, depth: int, cycle: bool }
    """
    import datetime

    # Collect the seed CBEs — identifiers of legal-entity admins.
    seed_cbes: list[str] = []
    for a in admins:
        if a.get("person_type") == "legal" and a.get("identifier"):
            c = (a["identifier"] or "").strip().replace(".", "")
            if c and c.isdigit():
                seed_cbes.append(c)
    if not seed_cbes:
        return admins  # nothing to do

    today = datetime.date.today().isoformat()

    # ------------------------------------------------------------------
    # Batch-fetch active administrator rows for all CBEs we will ever
    # need.  We do BFS level-by-level so we can add newly discovered CBEs
    # to subsequent fetches.  With depth ≤ 3 this is at most 3 round-
    # trips total (most companies resolve in 1-2).
    # ------------------------------------------------------------------
    # Keyed by enterprise_number → list[dict] (only active mandates)
    fetched_admins: dict[str, list[dict]] = {}
    # Keyed by enterprise_number → list[dict] (affiliation fallback)
    fetched_affil: dict[str, list[dict]] = {}

    def _batch_fetch_admins(cbes: list[str]) -> None:
        """Populate fetched_admins for any cbes not yet fetched."""
        to_fetch = [c for c in cbes if c not in fetched_admins]
        if not to_fetch:
            return
        ph = ",".join(["%s"] * len(to_fetch))
        rows = fetch_all(
            rf"""
            SELECT a.enterprise_number,
                   a.name, a.role, a.person_type, a.identifier,
                   a.mandate_start, a.mandate_end
            FROM administrator a
            WHERE a.enterprise_number IN ({ph})
              AND a.deposit_key NOT LIKE 'sb\_%%' ESCAPE '\'
              AND (a.mandate_end IS NULL OR a.mandate_end >= %s)
            ORDER BY a.enterprise_number, a.name
            """,
            to_fetch + [today],
        )
        for c in to_fetch:
            fetched_admins[c] = []
        for row in rows:
            fetched_admins[row["enterprise_number"]].append(row)

    def _batch_fetch_affil(cbes: list[str]) -> None:
        """Populate fetched_affil for any cbes not yet fetched (fallback)."""
        if not affiliation_table_present:
            for c in cbes:
                fetched_affil[c] = []
            return
        to_fetch = [c for c in cbes if c not in fetched_affil]
        if not to_fetch:
            return
        ph = ",".join(["%s"] * len(to_fetch))
        rows = fetch_all(
            f"""
            SELECT DISTINCT ON (af.enterprise_number, af.person_name)
                   af.enterprise_number,
                   af.person_name AS name,
                   af.affiliation_type AS role,
                   'natural' AS person_type,
                   NULL AS identifier
            FROM affiliation af
            WHERE af.enterprise_number IN ({ph})
            ORDER BY af.enterprise_number, af.person_name,
                     af.last_seen_at DESC NULLS LAST
            """,
            to_fetch,
        )
        for c in to_fetch:
            fetched_affil[c] = []
        for row in rows:
            fetched_affil[row["enterprise_number"]].append(row)

    def _resolve_chain(start_cbe: str, visited: frozenset[str], depth: int) -> list[dict]:
        """Recursively build the chain starting from start_cbe."""
        if depth > _CHAIN_MAX_DEPTH:
            return []
        if start_cbe in visited:
            # cycle — caller should have already marked the node
            return []

        # Ensure we have data for this CBE
        _batch_fetch_admins([start_cbe])

        reps = fetched_admins.get(start_cbe, [])
        if not reps:
            # Fallback to affiliation table
            _batch_fetch_affil([start_cbe])
            reps = fetched_affil.get(start_cbe, [])

        if not reps:
            return []

        chain: list[dict] = []
        new_visited = visited | {start_cbe}
        for rep in reps:
            person_type = rep.get("person_type") or "natural"
            rep_cbe = None
            if person_type == "legal" and rep.get("identifier"):
                raw = (rep["identifier"] or "").strip().replace(".", "")
                if raw and raw.isdigit():
                    rep_cbe = raw

            is_cycle = rep_cbe is not None and rep_cbe in new_visited
            link: dict = {
                "cbe": rep_cbe,
                "name": rep.get("name") or "",
                "role": rep.get("role") or None,
                "person_type": person_type,
                "depth": depth,
                "cycle": is_cycle,
            }
            chain.append(link)

            # Recurse into legal-entity reps unless cycle or natural person
            if not is_cycle and rep_cbe and person_type == "legal":
                sub_chain = _resolve_chain(rep_cbe, new_visited | {rep_cbe}, depth + 1)
                chain.extend(sub_chain)

        return chain

    # Pre-fetch level-1 in one batch for efficiency
    _batch_fetch_admins(seed_cbes)

    result: list[dict] = []
    for admin in admins:
        if admin.get("person_type") == "legal" and admin.get("identifier"):
            raw = (admin["identifier"] or "").strip().replace(".", "")
            if raw and raw.isdigit():
                chain = _resolve_chain(raw, frozenset(), depth=1)
                if chain:
                    logger.info(
                        "representation_chain for admin %s (%s): %d links",
                        admin.get("name"), raw, len(chain),
                    )
                    admin = dict(admin)  # don't mutate the original
                    admin["representation_chain"] = chain
        result.append(admin)
    return result


@router.get("/{cbe}/structure")
async def get_company_structure(cbe: str, response: Response):
    """Admins, shareholders, participating interests, and Staatsblad publications.

    Phase 3b change: the `administrators` list is now a merged view
    using the latest NBB annual-filing snapshot as the baseline, then
    applying later Staatsblad appointment / resignation events. Each row
    is annotated with:
      - `source`: 'nbb' | 'staatsblad' | 'merged'
      - `as_of`: best-known date for the mandate (NBB fiscal-year close
        or Staatsblad event date)

    A new `administrator_events` field surfaces the raw Staatsblad
    admin_event timeline (newest first) so the UI can render a
    changes-over-time view.
    """
    cbe = clean_cbe(cbe)
    # Structure changes when staatsblad publishes appointment / resignation
    # notices — daily at most. 5 min browser cache + long SWR keeps the
    # tab switch + back-button paths instant. Overridden to no-store on
    # the empty path below — caching an empty response would let the
    # browser serve stale `[]` to the post-/load auto-refetch and hide
    # freshly extracted admins until the cache expires.
    response.headers["Cache-Control"] = "private, max-age=300, stale-while-revalidate=86400"

    try:
        # NBB snapshot — latest deposit per company.
        # EXCLUDE deposit_keys starting with 'sb_' — those are legacy
        # Staatsblad-sourced rows from the old /extract-admins endpoint.
        # They sort AFTER NBB keys lexicographically ('s' > 'n'), which
        # made MAX(deposit_key) pick a single Staatsblad filing and hide
        # every actual NBB director. Stage 3's authoritative Staatsblad
        # data now lives in staatsblad_event, so this seed is NBB-only.
        #
        # Prefer the actual NBB deposit_date when choosing / dating the
        # baseline snapshot; fiscal_year is only a fallback if the filing
        # date is missing.
        nbb_admins = fetch_all(r"""
            WITH latest AS (
                SELECT a.deposit_key AS dk,
                       MAX(fs.deposit_date) AS deposit_date
                FROM administrator a
                LEFT JOIN financial_summary fs
                  ON fs.enterprise_number = a.enterprise_number
                 AND fs.deposit_key = a.deposit_key
                WHERE a.enterprise_number = %s
                  AND a.deposit_key NOT LIKE 'sb\_%%' ESCAPE '\'
                GROUP BY a.deposit_key
                ORDER BY MAX(fs.deposit_date) DESC NULLS LAST,
                         a.deposit_key DESC
                LIMIT 1
            )
            SELECT DISTINCT ON (a.name, a.role)
                   a.name, a.role, a.person_type, a.identifier,
                   a.mandate_start, a.mandate_end, a.representative_name,
                   a.fiscal_year, a.deposit_key, l.deposit_date
            FROM administrator a
            JOIN latest l ON a.deposit_key = l.dk
            WHERE a.enterprise_number = %s
              AND a.deposit_key NOT LIKE 'sb\_%%' ESCAPE '\'
            ORDER BY a.name, a.role
        """, (cbe, cbe))

        # Staatsblad admin events (admin_event only — other categories
        # feed the enrichment side).
        staatsblad_admin_events = fetch_all("""
            SELECT id, pub_reference, pub_date, event_type, sub_type,
                   event_date, person_name, person_role, entity_name, summary
            FROM staatsblad_event
            WHERE enterprise_number = %s
              AND event_type = 'admin_event'
            ORDER BY pub_date ASC, id ASC
        """, (cbe,))

        admins_merged, admin_timeline = merge_admins_with_staatsblad(
            nbb_admins,
            staatsblad_admin_events,
            role_labels=ROLE_LABELS,
        )

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

        # Parent companies — reverse lookup against participating_interest.
        # Surfaces parents that disclose this CBE in their own filings, even
        # when this company itself has no shareholder schedule (typical for
        # abbreviated-form filers and non-filing subsidiaries). Mirrors the
        # spiderweb's reverse PI traversal in network.py so the People &
        # Ownership tab no longer looks empty for child entities the parent
        # has already declared.
        #
        # Latest fiscal_year per parent to avoid resurfacing prior filings
        # where the parent has since dropped this entity from its cap table.
        # The `relevant` CTE narrows the MAX scan to enterprises that have
        # ever named this CBE — without it, MAX would scan the whole table.
        # Exclude self-references — accounting quirks where a holding lists
        # itself in its own PI schedule shouldn't surface as a "parent of
        # itself" in the UI.
        parent_companies = fetch_all("""
            WITH relevant AS (
                SELECT DISTINCT enterprise_number
                FROM participating_interest
                WHERE identifier = %s
                  AND enterprise_number <> %s
            ),
            latest AS (
                SELECT pi.enterprise_number, MAX(pi.fiscal_year) AS fy
                FROM participating_interest pi
                JOIN relevant r ON r.enterprise_number = pi.enterprise_number
                GROUP BY pi.enterprise_number
            )
            SELECT DISTINCT ON (pi.enterprise_number)
                   pi.enterprise_number,
                   pi.ownership_pct,
                   pi.country,
                   pi.fiscal_year,
                   COALESCE(d.denomination, pi.enterprise_number) AS name
            FROM participating_interest pi
            JOIN latest l ON l.enterprise_number = pi.enterprise_number
                         AND l.fy = pi.fiscal_year
            LEFT JOIN denomination d
                ON d.entity_number = pi.enterprise_number
                AND d.type_of_denomination = '001'
                AND d.language IN ('2', '1')
            WHERE pi.identifier = %s
            ORDER BY pi.enterprise_number,
                     CASE d.language WHEN '2' THEN 0 WHEN '1' THEN 1 ELSE 2 END
        """, (cbe, cbe, cbe))
        ownership_graph_enabled = ownership_graph_read_enabled()
        if ownership_graph_enabled:
            shareholders, pis, parent_companies = _fetch_ownership_graph_structure(cbe)

        sb_pubs = fetch_all(
            "SELECT pub_date, pub_type, reference, pdf_url FROM staatsblad_publication "
            "WHERE enterprise_number = %s ORDER BY pub_date DESC",
            (cbe,),
        )

        # Affiliations — natural people who represent a corporate director
        # of THIS company. Probe-then-query: the table doesn't exist on
        # environments that haven't applied the affiliation migration yet;
        # treat that as an empty list rather than a 500. Probe result is
        # cached at module scope so we only pay the round-trip once per
        # process.
        global _AFFILIATION_TABLE_PRESENT
        affiliation_rows: list[dict] = []
        if _AFFILIATION_TABLE_PRESENT is None:
            with get_conn() as _probe_conn:
                with _probe_conn.cursor() as _probe_cur:
                    _probe_cur.execute(
                        "SELECT to_regclass('public.affiliation') IS NOT NULL"
                    )
                    _AFFILIATION_TABLE_PRESENT = bool(_probe_cur.fetchone()[0])
        if _AFFILIATION_TABLE_PRESENT:
            affiliation_rows = fetch_all("""
                SELECT
                    af.person_name,
                    af.via_enterprise_number,
                    COALESCE(via_d.denomination, af.via_enterprise_number) AS via_company_name,
                    af.fiscal_year,
                    af.affiliation_type,
                    af.last_seen_at
                FROM affiliation af
                LEFT JOIN denomination via_d
                    ON via_d.entity_number = af.via_enterprise_number
                    AND via_d.type_of_denomination = '001' AND via_d.language IN ('2','1')
                WHERE af.enterprise_number = %s
                ORDER BY af.last_seen_at DESC NULLS LAST, af.person_name
            """, (cbe,))

        # Dedupe by (person, via_company): one filing per row in the
        # source table, but the UI cares about the relationship.
        affiliations_dedup: dict[tuple[str, str], dict] = {}
        for row in affiliation_rows:
            key = (
                (row.get("person_name") or "").lower(),
                row.get("via_enterprise_number") or "",
            )
            if key not in affiliations_dedup:
                affiliations_dedup[key] = row

        # ------------------------------------------------------------------
        # Representation chains — for each legal-entity admin that has an
        # identifier (CBE), look up who represents *that* entity up to
        # depth 3. Done in two batch queries (one for administrator, one
        # for affiliation fallback) and stitched in Python; no per-admin
        # round-trips.
        # ------------------------------------------------------------------
        admins_with_chains = _build_representation_chains(
            admins_merged, affiliation_table_present=_AFFILIATION_TABLE_PRESENT
        )

        # If the response carries no actual structure data, the auto-load
        # on the profile is about to populate it. Don't cache `[]` for
        # 5 min — the post-/load refetch needs to see fresh rows as soon
        # as they land, not a stale empty snapshot.
        is_empty = (
            not admins_with_chains
            and not admin_timeline
            and not pis
            and not shareholders
            and not sb_pubs
            and not affiliations_dedup
            and not parent_companies
        )
        if is_empty:
            response.headers["Cache-Control"] = "no-store"

        return {
            "administrators": [_serialize_row(r) for r in admins_with_chains],
            "administrator_events": [_serialize_row(r) for r in admin_timeline],
            "participating_interests": [_serialize_row(r) for r in pis],
            "shareholders": [_serialize_row(r) for r in shareholders],
            "parent_companies": [_serialize_row(r) for r in parent_companies],
            "staatsblad_publications": [_serialize_row(r) for r in sb_pubs],
            "affiliations": [_serialize_row(r) for r in affiliations_dedup.values()],
            "ownership_graph_enabled": ownership_graph_enabled,
        }
    except Exception as e:
        logger.exception("Company structure query failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{cbe}/ownership-graph")
async def get_company_ownership_graph(
    cbe: str,
    max_depth: int = Query(6, ge=1, le=12),
):
    """Ownership graph read path, gated until production soak is complete."""
    if not ownership_graph_read_enabled():
        raise HTTPException(status_code=404, detail="Ownership graph is not enabled")

    cbe = clean_cbe(cbe)
    if not isinstance(max_depth, int):
        max_depth = 6
    try:
        shareholders, participating_interests, parent_companies = _fetch_ownership_graph_structure(cbe)
        ubo_walk = fetch_all("""
            SELECT depth,
                   parent_kind,
                   parent_id,
                   parent_name_raw,
                   child_id,
                   pct,
                   edge_kind,
                   source_rank,
                   path,
                   cycle
            FROM ownership_ubo_walk(%s, %s)
            ORDER BY depth ASC,
                     source_rank ASC,
                     pct DESC NULLS LAST,
                     parent_name_raw NULLS LAST
        """, (cbe, max_depth))
        return {
            "shareholders": [_serialize_row(r) for r in shareholders],
            "participating_interests": [_serialize_row(r) for r in participating_interests],
            "parent_companies": [_serialize_row(r) for r in parent_companies],
            "ubo_walk": [_serialize_row(r) for r in ubo_walk],
            "max_depth": max_depth,
        }
    except Exception:
        logger.exception("Ownership graph query failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# POST /api/companies/{cbe}/extract-admins
# ---------------------------------------------------------------------------

async def _download_pdf_text(pdf_url: str) -> str:
    """Download a Staatsblad PDF and extract text using pdfplumber."""
    import io

    try:
        import pdfplumber
    except ImportError:
        logger.warning("pdfplumber not installed — cannot extract PDF text")
        return ""

    full_url = f"{STAATSBLAD_BASE}{pdf_url}"
    # Cap PDF size to avoid memory exhaustion if Staatsblad ever serves a
    # huge scanned filing (or a pathological adversary). Most appointment
    # notices are well under a megabyte.
    MAX_PDF_BYTES = 10 * 1024 * 1024  # 10 MB
    try:
        async with httpx.AsyncClient() as client:
            # Stream so we can abort without buffering the whole body.
            async with client.stream(
                "GET", full_url,
                timeout=30,
                follow_redirects=True,
                headers={"User-Agent": "Datasnoop/1.0 (+https://datasnoop.be)"},
            ) as resp:
                if resp.status_code != 200:
                    logger.warning("Staatsblad PDF download failed (%s): %s", resp.status_code, full_url)
                    return ""
                content_length = resp.headers.get("content-length")
                if content_length and int(content_length) > MAX_PDF_BYTES:
                    logger.warning("Staatsblad PDF too large (%s bytes), skipping: %s", content_length, full_url)
                    return ""
                buf = bytearray()
                async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                    buf.extend(chunk)
                    if len(buf) > MAX_PDF_BYTES:
                        logger.warning("Staatsblad PDF exceeded %d bytes mid-stream: %s", MAX_PDF_BYTES, full_url)
                        return ""

            text_parts = []
            with pdfplumber.open(io.BytesIO(bytes(buf))) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)

            return "\n".join(text_parts)
    except Exception as e:
        logger.exception("Failed to download/parse Staatsblad PDF %s: %s", pdf_url, e)
        return ""


@router.post("/{cbe}/extract-admins")
async def extract_admins_from_staatsblad(cbe: str):
    """Surface administrator names from Staatsblad — Stage 3 rewrite.

    Phase 3b change: the endpoint no longer hits the LLM.  It reads
    pre-extracted rows from `staatsblad_event` (written by the nightly
    incremental + the backfill) and synthesises `administrator` rows
    from them.  Huge cost saver — zero LLM spend on profile views that
    used to re-run extraction.

    Back-compat: the response shape is unchanged (same `extracted`
    key).  If the company already has NBB admins we return 0 without
    touching the event store.  If the event store has no admin_event
    rows we also return 0 — the daily incremental will eventually fill
    them in.
    """
    cbe = clean_cbe(cbe)

    try:
        existing = fetch_one(
            "SELECT COUNT(*) AS cnt FROM administrator WHERE enterprise_number = %s",
            (cbe,),
        )
        if existing and existing["cnt"] > 0:
            return {"extracted": 0, "message": "Company already has administrator data"}

        if _admin_extract_cache_skip(cbe):
            return {"extracted": 0, "message": "Recently attempted with no result", "cached": True}

        # Read pre-extracted admin events from staatsblad_event.
        events = fetch_all("""
            SELECT pub_reference, pub_date, event_date, sub_type,
                   person_name, person_role, entity_name, summary
            FROM staatsblad_event
            WHERE enterprise_number = %s
              AND event_type = 'admin_event'
            ORDER BY pub_date ASC, id ASC
        """, (cbe,))

        if not events:
            _admin_extract_cache_record(cbe, 0)
            return {
                "extracted": 0,
                "message": "No structured admin events — try again after the next nightly run",
            }

        inserted = 0
        conn = get_connection()
        try:
            cur = conn.cursor()
            for ev in events:
                name = (ev.get("person_name") or ev.get("entity_name") or "").strip()
                if not name:
                    continue
                role = (ev.get("person_role") or "").strip()
                sub = (ev.get("sub_type") or "").lower()
                pub_date = str(ev.get("event_date") or ev.get("pub_date") or "")
                person_type = "natural" if ev.get("person_name") else "legal"
                deposit_key = f"sb_{ev.get('pub_reference') or pub_date}"
                if sub in ("appointment", "reappointment", "renewal"):
                    try:
                        cur.execute("""
                            INSERT INTO administrator
                                (enterprise_number, deposit_key, name, role,
                                 mandate_start, person_type)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT DO NOTHING
                        """, (cbe, deposit_key, name, role, pub_date, person_type))
                        if cur.rowcount > 0:
                            inserted += 1
                    except Exception:
                        pass
                elif sub in ("resignation", "end", "termination"):
                    try:
                        cur.execute("""
                            UPDATE administrator
                            SET mandate_end = %s
                            WHERE enterprise_number = %s
                              AND LOWER(name) = LOWER(%s)
                              AND mandate_end IS NULL
                        """, (pub_date, cbe, name))
                    except Exception:
                        pass
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.exception("Failed to project staatsblad events → administrator for %s", cbe)
            raise HTTPException(status_code=500, detail="Failed to store extracted administrators")
        finally:
            put_connection(conn)

        logger.info(
            "extract-admins (Stage 3) for %s: projected %d events as admins",
            cbe, inserted,
        )
        _admin_extract_cache_record(cbe, inserted)
        return {"extracted": inserted, "source": "staatsblad_event"}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("extract-admins failed for %s: %s", cbe, e)
        raise HTTPException(status_code=500, detail="Internal server error")
