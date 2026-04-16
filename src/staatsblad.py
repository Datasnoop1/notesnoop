"""Scrape Staatsblad (Belgian Official Gazette) publications for a company.

Fetches from the ejustice.just.fgov.be CGI endpoint and parses the HTML
to extract publication date, type, reference number, and PDF link.

Usage:
    python src/staatsblad.py 0403101811              # scrape & print
    python src/staatsblad.py 0403101811 --store      # scrape & save to DB
"""

import argparse
import os
import re
import sqlite3
import time
from datetime import datetime

import requests

BASE_URL = "https://www.ejustice.just.fgov.be"
LIST_URL = BASE_URL + "/cgi_tsv/list.pl"

DEFAULT_DB = os.path.join(os.path.dirname(__file__), "..", "db", "belgian_companies.db")


def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def fetch_publications(cbe, language="nl"):
    """Fetch all Staatsblad publications for a CBE number.

    Args:
        cbe: 10-digit enterprise number (dots stripped).
        language: 'nl' or 'fr'.

    Returns:
        List of dicts: {pub_date, pub_type, reference, pdf_url, entity_name}
    """
    cbe = str(cbe).replace(".", "")
    params = {"language": language, "btw": cbe}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    publications = []
    page = 1

    while True:
        params["page"] = page
        resp = requests.get(LIST_URL, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        html = resp.text

        items = html.split('<div class="list-item">')
        if len(items) <= 1:
            break

        found_on_page = 0
        for item in items[1:]:
            pub = _parse_item(item, cbe)
            if pub:
                publications.append(pub)
                found_on_page += 1

        # Check for next page
        next_page = f"page={page + 1}"
        if next_page in html and found_on_page > 0:
            page += 1
            time.sleep(1)
        else:
            break

    return publications


def _parse_item(html, cbe):
    """Parse a single list-item div into a publication dict."""
    result = {"enterprise_number": cbe}

    # Entity name from <font color=blue>NAME</font>
    name_match = re.search(r'<font color=blue>([^<]+)</font>\s*&nbsp;\s*(\S+)', html)
    if name_match:
        result["entity_name"] = f"{name_match.group(1).strip()} {name_match.group(2).strip()}"
    else:
        name_match2 = re.search(r'<font color=blue>([^<]+)</font>', html)
        result["entity_name"] = name_match2.group(1).strip() if name_match2 else None

    # Publication type: line between <br> tags, all uppercase
    # Pattern: after the CBE number line, before the date line
    lines = re.findall(r'<br>\s*\n([^<\n]+)\n', html)
    pub_type = None
    for line in lines:
        line = line.strip()
        # Publication types are uppercase, may contain spaces, dashes, dots
        if line and re.match(r'^[A-Z][A-Z .&\-/,()]+$', line):
            pub_type = line
            break
    result["pub_type"] = pub_type

    # Date and reference: pattern YYYY-MM-DD / NNNNNNN
    date_match = re.search(r'(\d{4}-\d{2}-\d{2})\s*/\s*(\d+)', html)
    if date_match:
        result["pub_date"] = date_match.group(1)
        result["reference"] = date_match.group(2)
    else:
        return None  # Can't identify without a date

    # PDF URL
    pdf_match = re.search(r'href="(/tsv_pdf/[^"]+)"', html)
    result["pdf_url"] = pdf_match.group(1) if pdf_match else None

    return result


def store_publications(conn, publications):
    """Insert publications into the database, skipping duplicates."""
    if not publications:
        return 0
    for pub in publications:
        conn.execute(
            """INSERT OR IGNORE INTO staatsblad_publication
               (enterprise_number, pub_date, pub_type, reference, pdf_url, entity_name, loaded_at)
               VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
            (pub["enterprise_number"], pub["pub_date"], pub.get("pub_type"),
             pub.get("reference"), pub.get("pdf_url"), pub.get("entity_name")),
        )
    conn.commit()
    return len(publications)


def load_staatsblad(conn, cbe, language="nl"):
    """Fetch and store publications for a company. Returns count."""
    cbe = str(cbe).replace(".", "")
    pubs = fetch_publications(cbe, language)
    if pubs:
        store_publications(conn, pubs)
    return len(pubs)


def main():
    parser = argparse.ArgumentParser(description="Fetch Staatsblad publications")
    parser.add_argument("cbe", help="CBE number (10 digits)")
    parser.add_argument("--store", action="store_true", help="Save to database")
    parser.add_argument("--db", default=DEFAULT_DB, help="SQLite database path")
    parser.add_argument("--lang", default="nl", choices=["nl", "fr"])
    args = parser.parse_args()

    cbe = args.cbe.replace(".", "")
    log(f"Fetching Staatsblad publications for {cbe}")

    pubs = fetch_publications(cbe, args.lang)
    log(f"Found {len(pubs)} publication(s)")

    for pub in pubs:
        pdf = pub.get("pdf_url", "")
        ptype = pub.get("pub_type") or "?"
        print(f"  {pub['pub_date']}  {ptype:<35}  {pub.get('reference','')}  {pdf}")

    if args.store and pubs:
        conn = sqlite3.connect(os.path.abspath(args.db))
        store_publications(conn, pubs)
        conn.close()
        log(f"Stored {len(pubs)} publications in DB")


if __name__ == "__main__":
    main()
