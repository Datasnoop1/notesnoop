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

@router.get("/{cbe}/structure")
async def get_company_structure(cbe: str):
    """Admins, shareholders, participating interests, and Staatsblad publications.

    SQL extracted from app/pages/2_company.py load_company_detail().
    """
    cbe = clean_cbe(cbe)

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
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(full_url, timeout=30, follow_redirects=True)
            if resp.status_code != 200:
                logger.warning("Staatsblad PDF download failed (%s): %s", resp.status_code, full_url)
                return ""

            text_parts = []
            with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
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
    """Extract administrator names from Staatsblad appointment/resignation PDFs.

    Only runs if the company has 0 administrators in the database.
    Downloads the most recent 3 ONTSLAGEN-BENOEMINGEN publications,
    extracts text via pdfplumber, then uses a cheap LLM to parse names/roles.
    """
    cbe = clean_cbe(cbe)

    try:
        # 1. Check if company already has administrators
        existing = fetch_one(
            "SELECT COUNT(*) AS cnt FROM administrator WHERE enterprise_number = %s",
            (cbe,),
        )
        if existing and existing["cnt"] > 0:
            return {"extracted": 0, "message": "Company already has administrator data"}

        # 1b. Skip if we recently tried this CBE and got nothing back. The
        #     frontend fires this passively whenever a company profile loads
        #     with zero admins; without the cache, we would hit the LLM on
        #     every such page view.
        if _admin_extract_cache_skip(cbe):
            return {"extracted": 0, "message": "Recently attempted with no result", "cached": True}

        # 2. Fetch company name for the LLM prompt
        company = fetch_one(
            "SELECT name FROM company_info WHERE enterprise_number = %s", (cbe,),
        )
        company_name = company["name"] if company else cbe

        # 3. Get the most recent 3 appointment/resignation publications
        pubs = fetch_all(
            """SELECT pub_date, reference, pdf_url
               FROM staatsblad_publication
               WHERE enterprise_number = %s
                 AND pub_type = 'ONTSLAGEN - BENOEMINGEN'
                 AND pdf_url IS NOT NULL
               ORDER BY pub_date DESC
               LIMIT 3""",
            (cbe,),
        )

        if not pubs:
            _admin_extract_cache_record(cbe, 0)
            return {"extracted": 0, "message": "No appointment/resignation publications found"}

        # 4. Process each publication
        all_appointments = []
        all_resignations = []

        for pub in pubs:
            pdf_text = await _download_pdf_text(pub["pdf_url"])
            if not pdf_text or len(pdf_text.strip()) < 20:
                logger.info("Skipping empty PDF for %s pub %s", cbe, pub["reference"])
                continue

            # Truncate very long texts to avoid wasting tokens
            if len(pdf_text) > 5000:
                pdf_text = pdf_text[:5000]

            prompt = ADMIN_EXTRACTION_PROMPT.format(
                name=company_name, cbe=cbe, pdf_text=pdf_text,
            )

            raw = await ai_complete(
                prompt=prompt,
                system="You are an expert at reading Belgian legal gazette publications. Extract names and roles accurately. Return only valid JSON.",
                model="openai/gpt-4o-mini",
                max_tokens=800,
            )

            if not raw:
                logger.warning("LLM returned empty for %s pub %s", cbe, pub["reference"])
                continue

            # Parse LLM response
            parsed = None
            cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`")
            try:
                parsed = json.loads(cleaned)
            except json.JSONDecodeError:
                match = re.search(r"\{.*\}", cleaned, re.DOTALL)
                if match:
                    try:
                        parsed = json.loads(match.group())
                    except json.JSONDecodeError:
                        pass

            if not parsed:
                logger.warning("Could not parse LLM JSON for %s pub %s", cbe, pub["reference"])
                continue

            pub_date = str(pub["pub_date"])
            for appt in parsed.get("appointments", []):
                name = appt.get("name", "").strip()
                role = appt.get("role", "").strip()
                if name:
                    all_appointments.append({
                        "name": name, "role": role, "pub_date": pub_date,
                    })

            for res in parsed.get("resignations", []):
                name = res.get("name", "").strip()
                role = res.get("role", "").strip()
                if name:
                    all_resignations.append({
                        "name": name, "role": role, "pub_date": pub_date,
                    })

        # 5. Insert appointments and handle resignations
        inserted = 0
        conn = get_connection()
        try:
            cur = conn.cursor()

            # Insert appointments
            for appt in all_appointments:
                deposit_key = f"sb_{appt['pub_date']}"
                try:
                    cur.execute("""
                        INSERT INTO administrator
                            (enterprise_number, deposit_key, name, role, mandate_start, person_type)
                        VALUES (%s, %s, %s, %s, %s, 'natural')
                        ON CONFLICT DO NOTHING
                    """, (cbe, deposit_key, appt["name"], appt["role"], appt["pub_date"]))
                    if cur.rowcount > 0:
                        inserted += 1
                except Exception:
                    pass

            # Handle resignations: set mandate_end on matching admins
            for res in all_resignations:
                try:
                    cur.execute("""
                        UPDATE administrator
                        SET mandate_end = %s
                        WHERE enterprise_number = %s
                          AND LOWER(name) = LOWER(%s)
                          AND mandate_end IS NULL
                    """, (res["pub_date"], cbe, res["name"]))
                except Exception:
                    pass

            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.exception("Failed to insert Staatsblad admins for %s: %s", cbe, e)
            raise HTTPException(status_code=500, detail="Failed to store extracted administrators")
        finally:
            put_connection(conn)

        logger.info(
            "Staatsblad admin extraction for %s: %d appointments inserted, %d resignations processed",
            cbe, inserted, len(all_resignations),
        )
        _admin_extract_cache_record(cbe, inserted)
        return {"extracted": inserted}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("extract-admins failed for %s: %s", cbe, e)
        raise HTTPException(status_code=500, detail="Internal server error")
