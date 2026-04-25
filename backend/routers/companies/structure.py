"""Companies structure router — admins, shareholders, PIs, Staatsblad extraction."""

import logging
from collections import OrderedDict
from time import time as _time

import httpx
from fastapi import APIRouter, HTTPException

from db import fetch_all, fetch_one, get_conn, get_connection, put_connection
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


@router.get("/{cbe}/structure")
async def get_company_structure(cbe: str):
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

        return {
            "administrators": [_serialize_row(r) for r in admins_merged],
            "administrator_events": [_serialize_row(r) for r in admin_timeline],
            "participating_interests": [_serialize_row(r) for r in pis],
            "shareholders": [_serialize_row(r) for r in shareholders],
            "staatsblad_publications": [_serialize_row(r) for r in sb_pubs],
            "affiliations": [_serialize_row(r) for r in affiliations_dedup.values()],
        }
    except Exception as e:
        logger.exception("Company structure query failed")
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
