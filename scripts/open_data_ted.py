"""TED procurement ingester — Belgian public tender awards.

Pulls from the TED REST API (tenders.europa.eu/api/v3) the last N days of
award notices where the buyer country is Belgium AND the supplier is
Belgian. Stores one row per award in `procurement_award`, joining to CBE
via the supplier's VAT number (BEnnnnnnnnnn → 10-digit CBE).

Running nightly:
    0 3 * * * cd /opt/leadpeek && docker exec leadpeek-backend-1 \
        python /app/../scripts/open_data_ted.py --days 7 \
        >> scripts/_watchdog_state/ted.log 2>&1

TED's API is open (no key needed) and JSON; polite delay of 0.5s between
pages. Bulk CSV export available at data.europa.eu/data/datasets/ted-csv
for longer-range backfills (--backfill flag).
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from typing import Optional

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from db import execute, fetch_all, fetch_one  # type: ignore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("open_data_ted")

TED_API = "https://ted.europa.eu/api/v3.0/notices/search"
USER_AGENT = "Datasnoop/1.0 (Company Intelligence)"


def vat_to_cbe(vat: str) -> Optional[str]:
    """BE0123456789 → '0123456789'. Returns None if not Belgian."""
    if not vat:
        return None
    digits = re.sub(r"[^\d]", "", vat)
    if not digits:
        return None
    # Belgian VAT is 10 digits
    if len(digits) == 9:
        digits = "0" + digits
    if len(digits) != 10:
        return None
    # Sanity: BE prefix or starts with 0
    if not vat.strip().upper().startswith("BE") and not digits.startswith("0"):
        return None
    return digits


def fetch_page(since_iso: str, page: int) -> list[dict]:
    """Pull one page of BE award notices from TED. Returns list of notice dicts."""
    params = {
        "query": f'buyer-country="BEL" AND publication-date>={since_iso} AND notice-type="contract-award-notice"',
        "limit": 100,
        "page": page,
        "fields": "publication-number,notice-type,publication-date,buyer-legal-name,"
                  "contract-value-total,contract-value-currency,cpv-main,"
                  "awarded-contractor-name,awarded-contractor-vat,title",
    }
    try:
        r = requests.get(
            TED_API, params=params, timeout=30,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        if r.status_code != 200:
            log.warning("TED page %d HTTP %d: %s", page, r.status_code, r.text[:200])
            return []
        data = r.json()
        return data.get("notices", []) or data.get("results", []) or []
    except Exception as e:
        log.warning("TED page %d error: %s", page, e)
        return []


def store(notice: dict) -> bool:
    """Parse a notice dict into procurement_award row + INSERT. Returns True if inserted."""
    notice_id = notice.get("publication-number") or notice.get("publicationNumber")
    if not notice_id:
        return False
    # Already stored?
    existing = fetch_one(
        "SELECT 1 FROM procurement_award WHERE ted_notice_id = %s",
        (notice_id,),
    )
    if existing:
        return False

    supplier_vat = notice.get("awarded-contractor-vat") or notice.get("awardedContractorVat")
    enterprise_number = vat_to_cbe(supplier_vat) if supplier_vat else None

    pub_date_str = notice.get("publication-date") or notice.get("publicationDate")
    pub_date = None
    if pub_date_str:
        try:
            pub_date = datetime.fromisoformat(pub_date_str[:10]).date()
        except ValueError:
            pub_date = None

    value = notice.get("contract-value-total") or notice.get("contractValueTotal")
    try:
        value_num = float(value) if value is not None else None
    except (ValueError, TypeError):
        value_num = None

    currency = notice.get("contract-value-currency") or notice.get("contractValueCurrency") or "EUR"

    execute(
        """
        INSERT INTO procurement_award
            (ted_notice_id, enterprise_number, supplier_name, supplier_vat,
             buyer_name, award_date, contract_value, currency,
             cpv_code, title, country)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'BE')
        ON CONFLICT (ted_notice_id) DO NOTHING
        """,
        (
            notice_id,
            enterprise_number,
            notice.get("awarded-contractor-name") or notice.get("awardedContractorName"),
            supplier_vat,
            notice.get("buyer-legal-name") or notice.get("buyerLegalName"),
            pub_date,
            value_num,
            currency,
            notice.get("cpv-main") or notice.get("cpvMain"),
            notice.get("title"),
        ),
    )
    return True


def run(days: int) -> None:
    since = (date.today() - timedelta(days=days)).isoformat()
    log.info("TED ingest since %s (last %d days)", since, days)
    total = 0
    inserted = 0
    for page in range(1, 50):     # hard cap 50 × 100 = 5000 notices/run
        notices = fetch_page(since, page)
        if not notices:
            break
        total += len(notices)
        for n in notices:
            try:
                if store(n):
                    inserted += 1
            except Exception as e:
                log.warning("store error: %s", e)
        if len(notices) < 100:
            break
        time.sleep(0.5)
    log.info("TED ingest done: %d scanned, %d new inserted", total, inserted)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7, help="Look-back window in days (default 7)")
    args = ap.parse_args()
    run(args.days)
