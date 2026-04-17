"""Staatsblad router — load publications on demand."""

import os
import re
import time
import logging
import uuid

import requests as http_requests
from fastapi import APIRouter, HTTPException, Depends

from db import fetch_all, execute
from auth import get_current_user, optional_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/staatsblad", tags=["staatsblad"])

BASE_URL = "https://www.ejustice.just.fgov.be"
LIST_URL = BASE_URL + "/cgi_tsv/list.pl"


def _fetch_publications(cbe: str):
    """Scrape Staatsblad publications for a CBE number."""
    params = {"language": "nl", "btw": cbe}
    # Identify ourselves to the Belgian government endpoint so they can
    # contact us before IP-banning. Faking a generic browser UA was the
    # previous behaviour and is bad netiquette toward a public service.
    headers = {"User-Agent": "Datasnoop/1.0 (Belgian Company Intelligence; +https://datasnoop.be)"}
    publications = []
    page = 1

    while page <= 5:  # Max 5 pages
        params["page"] = page
        try:
            resp = http_requests.get(LIST_URL, params=params, headers=headers, timeout=30)
            resp.raise_for_status()
        except Exception as e:
            logger.warning("Staatsblad HTTP error for %s: %s", cbe, e)
            break

        html = resp.text
        items = html.split('<div class="list-item">')
        if len(items) <= 1:
            break

        found = 0
        for item in items[1:]:
            pub = _parse_item(item, cbe)
            if pub:
                publications.append(pub)
                found += 1

        next_page = f"page={page + 1}"
        if next_page in html and found > 0:
            page += 1
            time.sleep(0.5)
        else:
            break

    return publications


def _parse_item(html: str, cbe: str):
    result = {"enterprise_number": cbe}

    name_match = re.search(r'<font color=blue>([^<]+)</font>', html)
    result["entity_name"] = name_match.group(1).strip() if name_match else None

    lines = re.findall(r'<br>\s*\n([^<\n]+)\n', html)
    pub_type = None
    for line in lines:
        line = line.strip()
        if line and re.match(r'^[A-Z][A-Z .&\-/,()]+$', line):
            pub_type = line
            break
    result["pub_type"] = pub_type

    date_match = re.search(r'(\d{4}-\d{2}-\d{2})\s*/\s*(\d+)', html)
    if date_match:
        result["pub_date"] = date_match.group(1)
        result["reference"] = date_match.group(2)
    else:
        return None

    pdf_match = re.search(r'href="(/tsv_pdf/[^"]+)"', html)
    result["pdf_url"] = pdf_match.group(1) if pdf_match else None

    return result


@router.post("/{cbe}/load")
async def load_publications(cbe: str, user=Depends(optional_user)):
    """Scrape and store Staatsblad publications for a company.

    Per-CBE cooldown: skips the outbound ejustice scrape if we already
    fetched this CBE within the last 24h. Without this guard, every
    profile reload re-scraped 5 pages from a Belgian gov server, which
    would risk an IP block and waste outbound bandwidth.
    """
    from db import fetch_one

    cbe = cbe.strip().replace(".", "").zfill(10)

    try:
        # Cooldown check: if any row for this CBE was loaded in the last
        # 24h, return the cached state instead of hitting ejustice again.
        # Postgres handles the date math so we don't have to deal with
        # TEXT-vs-TIMESTAMP timezone quirks in Python.
        recent = fetch_one(
            "SELECT COUNT(*) AS n FROM staatsblad_publication "
            "WHERE enterprise_number = %s "
            "  AND loaded_at::timestamptz >= NOW() - INTERVAL '24 hours'",
            (cbe,),
        )
        if recent and recent.get("n", 0) > 0:
            count_row = fetch_one(
                "SELECT COUNT(*) AS n FROM staatsblad_publication WHERE enterprise_number = %s",
                (cbe,),
            )
            return {
                "enterprise_number": cbe,
                "publications_found": count_row["n"] if count_row else 0,
                "publications_stored": 0,
                "cached": True,
            }

        pubs = _fetch_publications(cbe)

        stored = 0
        for pub in pubs:
            try:
                execute("""
                    INSERT INTO staatsblad_publication
                        (enterprise_number, pub_date, pub_type, reference, pdf_url, entity_name)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                """, (
                    pub["enterprise_number"], pub["pub_date"], pub.get("pub_type"),
                    pub.get("reference"), pub.get("pdf_url"), pub.get("entity_name"),
                ))
                stored += 1
            except Exception:
                pass

        return {
            "enterprise_number": cbe,
            "publications_found": len(pubs),
            "publications_stored": stored,
        }
    except Exception as e:
        logger.exception("Load publications failed for %s", cbe)
        raise HTTPException(status_code=500, detail="Internal server error")
