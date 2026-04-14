"""Staatsblad scraper for Hetzner — scrapes publications for companies without data.

Runs as a batch job: finds companies without staatsblad data, scrapes ejustice.be.
Run on Hetzner: python3 staatsblad_hetzner.py [--limit 100]
"""

import os
import re
import sys
import time
import logging
import argparse
from datetime import datetime

import requests
import psycopg2
import psycopg2.extras

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    raise RuntimeError("DATABASE_URL environment variable not set")
BASE_URL = "https://www.ejustice.just.fgov.be"
LIST_URL = BASE_URL + "/cgi_tsv/list.pl"


def get_companies_without_staatsblad(conn, limit=100):
    """Find companies with financials but no staatsblad data."""
    cur = conn.cursor()
    cur.execute("""
        SELECT ci.enterprise_number
        FROM company_info ci
        LEFT JOIN staatsblad_publication sp ON sp.enterprise_number = ci.enterprise_number
        WHERE sp.enterprise_number IS NULL
        ORDER BY RANDOM()
        LIMIT %s
    """, (limit,))
    return [r[0] for r in cur.fetchall()]


def fetch_publications(cbe):
    """Fetch all Staatsblad publications for a CBE number."""
    cbe = str(cbe).replace(".", "")
    params = {"language": "nl", "btw": cbe}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    publications = []
    page = 1

    while True:
        params["page"] = page
        try:
            resp = requests.get(LIST_URL, params=params, headers=headers, timeout=30)
            resp.raise_for_status()
        except Exception as e:
            logger.warning("HTTP error for %s: %s", cbe, e)
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
            time.sleep(1)
        else:
            break

    return publications


def _parse_item(html, cbe):
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


def store_publications(conn, publications):
    """Insert publications into the database."""
    if not publications:
        return 0
    cur = conn.cursor()
    count = 0
    for pub in publications:
        try:
            cur.execute("""
                INSERT INTO staatsblad_publication
                    (enterprise_number, pub_date, pub_type, reference, pdf_url, entity_name)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """, (
                pub["enterprise_number"], pub["pub_date"], pub.get("pub_type"),
                pub.get("reference"), pub.get("pdf_url"), pub.get("entity_name"),
            ))
            count += 1
        except Exception:
            conn.rollback()
    conn.commit()
    return count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100, help="Companies to scrape")
    args = parser.parse_args()

    conn = psycopg2.connect(DB_URL)
    companies = get_companies_without_staatsblad(conn, limit=args.limit)
    logger.info("Found %d companies to scrape", len(companies))

    total_pubs = 0
    for i, cbe in enumerate(companies):
        pubs = fetch_publications(cbe)
        if pubs:
            stored = store_publications(conn, pubs)
            total_pubs += stored
            logger.info("[%d/%d] %s: %d publications", i + 1, len(companies), cbe, stored)
        else:
            # Mark as checked with a dummy entry
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO staatsblad_publication (enterprise_number, pub_date, reference)
                VALUES (%s, '1970-01-01', 'NO_DATA') ON CONFLICT DO NOTHING
            """, (cbe,))
            conn.commit()

        time.sleep(2)  # Be respectful

        if (i + 1) % 50 == 0:
            logger.info("Progress: %d/%d, total publications: %d", i + 1, len(companies), total_pubs)

    logger.info("Done. Scraped %d companies, %d publications stored", len(companies), total_pubs)
    conn.close()


if __name__ == "__main__":
    main()
