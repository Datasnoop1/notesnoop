"""Companies structure router — admins, shareholders, PIs, Staatsblad extraction."""

import json
import logging
import re
from collections import OrderedDict
from time import time as _time

import httpx
from fastapi import APIRouter, HTTPException

from db import fetch_all, fetch_one, get_connection, put_connection
from ai_client import ai_complete
from utils import clean_cbe
from ._helpers import (
    _serialize_row,
    ROLE_LABELS,
    STAATSBLAD_BASE,
    ADMIN_EXTRACTION_PROMPT,
)

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


# ---------------------------------------------------------------------------
# GET /api/companies/{cbe}/structure
# ---------------------------------------------------------------------------

def _normalize_name(raw: str | None) -> str:
    """Normalise a person/entity name for cross-source matching.

    Strips diacritics, lowercases, collapses whitespace, removes
    punctuation and common title prefixes. Does NOT expand initials
    (so 'J. De Smet' ≠ 'Jean De Smet' under this scheme) — initials
    matching is a known-imperfect gap we accept for now; the NBB
    snapshot usually uses full names like Staatsblad.
    """
    if not raw:
        return ""
    import re
    import unicodedata
    s = unicodedata.normalize("NFKD", raw)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[.,()/'\"’`]", " ", s)
    # Drop common Dutch/French honorifics
    s = re.sub(r"\b(?:mr|mrs|mme|m|mister|madame|monsieur|dhr|mevr|mevrouw|de heer)\b", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _merge_admins_with_staatsblad(
    cbe: str,
    nbb_rows: list[dict],
    staatsblad_events: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Merge the NBB snapshot with chronological Staatsblad admin events.

    Returns (current_state, timeline):
      - current_state: the list of people/entities currently on the board,
        each row annotated with `source` ('nbb' | 'staatsblad' | 'merged')
        and `as_of` (date of the latest Staatsblad event touching that
        person, or the NBB fiscal_year otherwise).
      - timeline: every staatsblad admin_event as-is, for UI rendering.

    Merge logic:
      1. Seed with the NBB snapshot (latest deposit per company). `as_of` =
         the NBB fiscal year + '-12-31' (snapshot-date best guess).
      2. Apply Staatsblad events in chronological order. An appointment
         adds a person (dedup by normalised name). A resignation drops
         the matching person from current_state, or annotates them as
         `ended_at = <event.pub_date>` if they have other mandates.
      3. Staatsblad-sourced entries keep `source='staatsblad'`; NBB
         entries that were NOT superseded stay `source='nbb'`; NBB
         entries refreshed by a later Staatsblad event become
         `source='merged'`.
    """
    current: dict[str, dict] = {}

    # Seed from NBB snapshot — role_label derived from NBB code.
    for row in nbb_rows:
        key = (_normalize_name(row.get("name") or ""), row.get("role") or "")
        k = "|".join(key)
        if not k.strip("|"):
            continue
        fiscal = row.get("fiscal_year") or ""
        as_of = None
        if isinstance(fiscal, str) and len(fiscal) >= 4 and fiscal[:4].isdigit():
            as_of = f"{fiscal[:4]}-12-31"
        enriched = {
            **row,
            "role_label": ROLE_LABELS.get(row.get("role") or "", row.get("role") or ""),
            "source": "nbb",
            "as_of": as_of,
        }
        current[k] = enriched

    # Sort Staatsblad events chronologically (oldest first) so the
    # last-write-wins naturally produces the current state.
    ordered_events = sorted(
        staatsblad_events,
        key=lambda e: (str(e.get("pub_date") or ""), int(e.get("id") or 0)),
    )

    for ev in ordered_events:
        # Only admin_event rows are relevant to the merge.
        if ev.get("event_type") != "admin_event":
            continue
        sub = (ev.get("sub_type") or "").lower()
        name = ev.get("person_name") or ev.get("entity_name") or ""
        role = ev.get("person_role") or ""
        nk = _normalize_name(name)
        if not nk:
            continue
        # Match against any NBB role if Staatsblad doesn't have an NBB code.
        # (Staatsblad roles are free-text like "Bestuurder" — we don't map
        # them to fct:* codes here.)  Use (normalised_name, role) as the
        # dedup key; if the NBB seed had a different role string we'll end
        # up with two rows, which is fine — they represent distinct mandates.
        k = "|".join((nk, role))

        if sub in ("appointment", "reappointment", "renewal"):
            existing = current.get(k)
            if existing is None:
                current[k] = {
                    "name": name,
                    "role": role,
                    "role_label": role,
                    "person_type": "natural" if ev.get("person_name") else "legal",
                    "identifier": None,
                    "mandate_start": str(ev.get("event_date") or ev.get("pub_date") or ""),
                    "mandate_end": None,
                    "representative_name": None,
                    "fiscal_year": None,
                    "deposit_key": f"sb_{ev.get('pub_reference')}",
                    "source": "staatsblad",
                    "as_of": str(ev.get("pub_date") or ""),
                    "pub_reference": ev.get("pub_reference"),
                    "summary": ev.get("summary"),
                }
            else:
                # Merge into the NBB-seeded (or earlier) row, preserving
                # fields only the NBB snapshot carries (identifier,
                # representative_name). Overlay freshness markers.
                existing.update({
                    "mandate_start": str(ev.get("event_date") or ev.get("pub_date") or existing.get("mandate_start") or ""),
                    "mandate_end": None,
                    "deposit_key": f"sb_{ev.get('pub_reference')}",
                    "source": "merged",
                    "as_of": str(ev.get("pub_date") or ""),
                    "pub_reference": ev.get("pub_reference"),
                    "summary": ev.get("summary"),
                })
        elif sub in ("resignation", "end", "termination"):
            # Match-by-name across any role, since resignations often omit
            # role in filings. Mark all mandates for this normalised name
            # as ended.
            resigned = False
            for existing_k in list(current.keys()):
                existing_name = existing_k.split("|", 1)[0]
                if existing_name == nk:
                    current[existing_k]["mandate_end"] = str(ev.get("event_date") or ev.get("pub_date") or "")
                    current[existing_k]["as_of"] = str(ev.get("pub_date") or "")
                    current[existing_k]["source"] = "merged" if current[existing_k].get("source") == "nbb" else "staatsblad"
                    resigned = True
            # If the resignation doesn't match any existing mandate, still
            # emit a resignation row so the timeline stays consistent —
            # but do NOT insert into current_state.
            if not resigned:
                continue

    # Drop entries whose mandate_end is set AND older than today — they're
    # historical, not "current".
    today = None
    import datetime as _dt
    today = _dt.date.today().isoformat()
    current_state = []
    for row in current.values():
        end = row.get("mandate_end")
        if end and end <= today:
            continue
        current_state.append(row)
    current_state.sort(key=lambda r: (r.get("name") or "", r.get("role") or ""))

    # Build the timeline from the chronologically-ordered events, newest first.
    timeline = []
    for ev in reversed(ordered_events):
        if ev.get("event_type") != "admin_event":
            continue
        timeline.append({
            "pub_date": str(ev.get("pub_date") or ""),
            "pub_reference": ev.get("pub_reference"),
            "sub_type": ev.get("sub_type"),
            "event_date": str(ev.get("event_date") or "") if ev.get("event_date") else None,
            "person_name": ev.get("person_name"),
            "person_role": ev.get("person_role"),
            "entity_name": ev.get("entity_name"),
            "summary": ev.get("summary"),
        })
    return current_state, timeline


@router.get("/{cbe}/structure")
async def get_company_structure(cbe: str):
    """Admins, shareholders, participating interests, and Staatsblad publications.

    Phase 3b change: the `administrators` list is now a merged view
    combining the NBB annual-filing snapshot with Staatsblad-sourced
    appointment / resignation events. Each row is annotated with:
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
        nbb_admins = fetch_all(r"""
            WITH latest AS (
                SELECT MAX(deposit_key) AS dk
                FROM administrator
                WHERE enterprise_number = %s
                  AND deposit_key NOT LIKE 'sb\_%%' ESCAPE '\'
            )
            SELECT DISTINCT ON (name, role) name, role, person_type, identifier,
                   mandate_start, mandate_end, representative_name, fiscal_year, deposit_key
            FROM administrator a
            JOIN latest l ON a.deposit_key = l.dk
            WHERE a.enterprise_number = %s
              AND a.deposit_key NOT LIKE 'sb\_%%' ESCAPE '\'
            ORDER BY name, role
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

        admins_merged, admin_timeline = _merge_admins_with_staatsblad(
            cbe, nbb_admins, staatsblad_admin_events,
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

        return {
            "administrators": [_serialize_row(r) for r in admins_merged],
            "administrator_events": [_serialize_row(r) for r in admin_timeline],
            "participating_interests": [_serialize_row(r) for r in pis],
            "shareholders": [_serialize_row(r) for r in shareholders],
            "staatsblad_publications": [_serialize_row(r) for r in sb_pubs],
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
