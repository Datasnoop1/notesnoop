"""Regsol insolvency ingester — Belgian bankruptcy + judicial reorg register.

Uses Zenrows (same proxy we use for company websites) to scrape
regsol.be case lookups by enterprise number. For each CBE we have in
`enterprise`, checks if Regsol has a matching case; if yes, stores a row
in `insolvency_case`.

Because Regsol has no official public API and scraping all 1.9M CBEs is
not feasible, this script only runs against:
  - companies with recent staatsblad "bankruptcy" / "judicial reorg" hits
  - companies whose juridical_situation is in the Belgian distress codes

That narrows to a few thousand candidates at most.

Running nightly:
    0 3 * * * cd /opt/leadpeek && docker exec leadpeek-backend-1 \
        python /app/../scripts/open_data_regsol.py --batch 200 \
        >> scripts/_watchdog_state/regsol.log 2>&1

This script is scaffolding — it runs Zenrows requests against Regsol's
public search form and extracts what it can. Real production accuracy
needs iteration against Regsol's markup (which changes). The extractor
is intentionally conservative: stores the raw last_scraped_at + case_type
and leaves more detail (curator, dates) to be filled on confirmation.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import time
from typing import Optional

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from db import execute, fetch_all, fetch_one  # type: ignore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("open_data_regsol")

ZENROWS_KEY = os.getenv("ZENROWS_API_KEY", "")
ZENROWS_URL = "https://api.zenrows.com/v1/"
# Distress juridical_situation codes from Belgian KBO.
DISTRESS_CODES = ("019", "020", "021", "022", "023", "024", "025", "026")


def candidates(batch: int) -> list[str]:
    """Companies worth scraping Regsol for — distress JS codes OR recent
    staatsblad distress pub_type — that we haven't scraped in 30 days."""
    sql = """
        SELECT DISTINCT e.enterprise_number
        FROM enterprise e
        LEFT JOIN insolvency_case ic
            ON ic.enterprise_number = e.enterprise_number
        WHERE (
            e.juridical_situation IN %s
            OR EXISTS (
                SELECT 1 FROM staatsblad_publication sp
                WHERE sp.enterprise_number = e.enterprise_number
                  AND sp.pub_date::date >= (CURRENT_DATE - INTERVAL '90 days')
                  AND (
                    sp.pub_type ILIKE %s OR sp.pub_type ILIKE %s
                  )
            )
        )
        AND (ic.last_scraped_at IS NULL
             OR ic.last_scraped_at < (NOW() - INTERVAL '30 days'))
        ORDER BY e.enterprise_number
        LIMIT %s
    """
    rows = fetch_all(sql, (DISTRESS_CODES, "%faillissement%", "%reorganisatie%", batch))
    return [r["enterprise_number"] for r in rows]


def scrape_regsol(cbe: str) -> Optional[dict]:
    """Return {docket_number, case_type, court, opened_at, status, curator_name}
    or None if no case found / error.

    Regsol's public search is a JavaScript SPA — we use Zenrows with
    js_render=true. Extraction heuristics are best-effort.
    """
    if not ZENROWS_KEY:
        log.debug("no ZENROWS_API_KEY — skipping regsol scrape")
        return None
    target = f"https://www.regsol.be/public/search?q={cbe}"
    params = {
        "url": target,
        "apikey": ZENROWS_KEY,
        "js_render": "true",
        "premium_proxy": "true",
        "proxy_country": "be",
    }
    try:
        r = requests.get(ZENROWS_URL, params=params, timeout=45)
    except Exception as e:
        log.warning("zenrows error for %s: %s", cbe, e)
        return None
    if r.status_code != 200:
        log.warning("zenrows %s HTTP %d", cbe, r.status_code)
        return None

    html = r.text
    if "geen resultaten" in html.lower() or "no results" in html.lower():
        return None

    out: dict = {}
    m = re.search(r"dossier[^\d]{0,12}(\d{2}/[A-Z]/[\d./-]+)", html, re.IGNORECASE)
    if m:
        out["docket_number"] = m.group(1)
    if re.search(r"faillissement", html, re.IGNORECASE):
        out["case_type"] = "bankruptcy"
    elif re.search(r"gerechtelijke reorganisatie|reorganisation judiciaire", html, re.IGNORECASE):
        out["case_type"] = "reorganisation"
    elif re.search(r"sluiting", html, re.IGNORECASE):
        out["case_type"] = "closure"

    m = re.search(r"ondernemingsrechtbank[^\n<]{0,80}", html, re.IGNORECASE)
    if m:
        out["court"] = m.group(0).strip()[:200]

    m = re.search(r"(\d{2}[/-]\d{2}[/-]\d{2,4})", html)
    if m:
        raw = m.group(1)
        for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y"):
            try:
                from datetime import datetime
                out["opened_at"] = datetime.strptime(raw, fmt).date().isoformat()
                break
            except ValueError:
                continue
    if re.search(r"afgesloten|closed|geëindigd", html, re.IGNORECASE):
        out["status"] = "closed"
    else:
        out["status"] = "open"
    return out if out.get("case_type") else None


def upsert_case(cbe: str, case: dict) -> None:
    execute(
        """
        INSERT INTO insolvency_case
            (enterprise_number, docket_number, case_type, court,
             opened_at, status, curator_name, last_scraped_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (docket_number) DO UPDATE SET
            enterprise_number = EXCLUDED.enterprise_number,
            case_type = EXCLUDED.case_type,
            court = EXCLUDED.court,
            opened_at = EXCLUDED.opened_at,
            status = EXCLUDED.status,
            curator_name = EXCLUDED.curator_name,
            last_scraped_at = NOW()
        """,
        (
            cbe,
            case.get("docket_number") or f"auto-{cbe}-{int(time.time())}",
            case.get("case_type"),
            case.get("court"),
            case.get("opened_at"),
            case.get("status"),
            case.get("curator_name"),
        ),
    )


def run(batch: int) -> None:
    if not ZENROWS_KEY:
        log.error("ZENROWS_API_KEY not set — aborting")
        sys.exit(2)
    cbes = candidates(batch)
    log.info("Regsol scrape: %d candidates", len(cbes))
    hits = 0
    for cbe in cbes:
        try:
            case = scrape_regsol(cbe)
            if case:
                upsert_case(cbe, case)
                hits += 1
                log.info("%s → %s", cbe, case.get("case_type"))
            else:
                # Record that we checked so the 30-day throttle engages.
                # Use a sentinel "no-case-<cbe>" docket_number so the INSERT
                # succeeds even when no row existed for this CBE before.
                execute(
                    """INSERT INTO insolvency_case
                           (enterprise_number, docket_number, case_type,
                            status, last_scraped_at)
                       VALUES (%s, %s, 'no_match', 'clean', NOW())
                       ON CONFLICT (docket_number) DO UPDATE SET
                           last_scraped_at = NOW()""",
                    (cbe, f"no-case-{cbe}"),
                )
        except Exception as e:
            log.warning("scrape error for %s: %s", cbe, e)
        time.sleep(1.0)
    log.info("Regsol ingest done: %d hits", hits)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=200,
                    help="Max candidates to scrape per run (default 200)")
    args = ap.parse_args()
    run(args.batch)
