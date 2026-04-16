"""Seed Vlerick M&A Monitor multiples + NACE→Vlerick mapping.

Run standalone: python scripts/seed_vlerick.py
Idempotent: UPSERTs, safe to re-run.

Data source: 2025 M&A Monitor (Vlerick Business School, published May 2025),
covering 2024 Belgian transaction data. Report URL:
https://www.moore.be/sites/default/files/2025-05/2025%20MA%20Monitor.pdf
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from dotenv import load_dotenv
load_dotenv()
import psycopg2

DATABASE_URL = os.getenv("DATABASE_URL")

# Vlerick 2025 Monitor — transactions in calendar year 2024
VLERICK_YEAR = 2024

SIZE_MULTIPLES = [
    ("lt_5m",    5.0,  "<€5M deal size"),
    ("5_20m",    6.4,  "€5M-€20M deal size"),
    ("20_50m",   7.7,  "€20M-€50M deal size"),
    ("50_100m",  8.1,  "€50M-€100M deal size"),
    ("gt_100m", 10.5,  ">€100M deal size"),
    ("overall",  6.5,  "Belgian M&A market overall"),
]

SECTOR_MULTIPLES = [
    ("technology",           9.1),
    ("pharmaceutical",       8.5),
    ("healthcare",           8.0),
    ("energy_utilities",     7.2),
    ("business_services",    6.7),
    ("entertainment_media",  6.3),
    ("chemistry",            6.2),
    ("consumer_goods",       6.1),
    ("industrial_products",  5.7),
    ("real_estate",          5.7),
    ("retail",               5.6),
    ("transport_logistics",  5.5),
    ("construction",         4.8),
]

# NACE Rev 2 two-digit prefix → Vlerick sector.
# Best-effort mapping; AI override can refine ambiguous cases at the company level.
NACE_MAPPING = {
    # A — Agriculture, forestry, fishing (fallback to industrial)
    "01": "industrial_products", "02": "industrial_products", "03": "industrial_products",
    # B — Mining & quarrying
    "05": "industrial_products", "06": "industrial_products", "07": "industrial_products",
    "08": "industrial_products", "09": "industrial_products",
    # C — Manufacturing
    "10": "consumer_goods", "11": "consumer_goods", "12": "consumer_goods",
    "13": "consumer_goods", "14": "consumer_goods", "15": "consumer_goods",
    "16": "industrial_products", "17": "industrial_products", "18": "industrial_products",
    "19": "chemistry", "20": "chemistry", "21": "pharmaceutical",
    "22": "industrial_products", "23": "industrial_products", "24": "industrial_products",
    "25": "industrial_products", "26": "industrial_products", "27": "industrial_products",
    "28": "industrial_products", "29": "industrial_products", "30": "industrial_products",
    "31": "industrial_products", "32": "industrial_products", "33": "industrial_products",
    # D/E — Energy & utilities
    "35": "energy_utilities", "36": "energy_utilities", "37": "energy_utilities",
    "38": "energy_utilities", "39": "energy_utilities",
    # F — Construction
    "41": "construction", "42": "construction", "43": "construction",
    # G — Trade (retail/wholesale)
    "45": "retail", "46": "retail", "47": "retail",
    # H — Transport & logistics
    "49": "transport_logistics", "50": "transport_logistics", "51": "transport_logistics",
    "52": "transport_logistics", "53": "transport_logistics",
    # I — Accommodation & food service
    "55": "consumer_goods", "56": "consumer_goods",
    # J — Information & communication
    "58": "technology",           # publishing (incl. software publishing)
    "59": "entertainment_media",  # motion picture/video
    "60": "entertainment_media",  # broadcasting
    "61": "technology",           # telecoms
    "62": "technology", "63": "technology",
    # K — Financial & insurance → business_services (Vlerick has no financial sector bucket)
    "64": "business_services", "65": "business_services", "66": "business_services",
    # L — Real estate
    "68": "real_estate",
    # M — Professional, scientific, technical
    "69": "business_services", "70": "business_services", "71": "business_services",
    "72": "business_services",    # R&D — borderline tech, but Vlerick defines tech as software-heavy
    "73": "business_services", "74": "business_services", "75": "business_services",
    # N — Administrative & support
    "77": "business_services", "78": "business_services", "79": "business_services",
    "80": "business_services", "81": "business_services", "82": "business_services",
    # O — Public administration
    "84": "business_services",
    # P — Education
    "85": "business_services",
    # Q — Human health & social work
    "86": "healthcare", "87": "healthcare", "88": "healthcare",
    # R — Arts, entertainment, recreation
    "90": "entertainment_media", "91": "entertainment_media",
    "92": "entertainment_media", "93": "entertainment_media",
    # S — Other services
    "94": "consumer_goods", "95": "consumer_goods", "96": "consumer_goods",
    # T/U — Households / extraterritorial (rare, fallback)
    "97": "business_services", "98": "business_services", "99": "business_services",
}


def main():
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL not set in environment.", file=sys.stderr)
        sys.exit(1)

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # Ensure tables exist (idempotent — matches schema.sql)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vlerick_multiple (
            year INTEGER NOT NULL,
            bucket_type TEXT NOT NULL,
            bucket_key TEXT NOT NULL,
            multiple REAL NOT NULL,
            source_note TEXT,
            PRIMARY KEY (year, bucket_type, bucket_key)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS nace_vlerick_mapping (
            nace_prefix TEXT PRIMARY KEY,
            vlerick_sector TEXT NOT NULL
        )
    """)

    # Seed size multiples
    for key, mult, note in SIZE_MULTIPLES:
        cur.execute("""
            INSERT INTO vlerick_multiple (year, bucket_type, bucket_key, multiple, source_note)
            VALUES (%s, 'size', %s, %s, %s)
            ON CONFLICT (year, bucket_type, bucket_key)
            DO UPDATE SET multiple = EXCLUDED.multiple, source_note = EXCLUDED.source_note
        """, (VLERICK_YEAR, key, mult, note))

    # Seed sector multiples
    for key, mult in SECTOR_MULTIPLES:
        cur.execute("""
            INSERT INTO vlerick_multiple (year, bucket_type, bucket_key, multiple)
            VALUES (%s, 'sector', %s, %s)
            ON CONFLICT (year, bucket_type, bucket_key)
            DO UPDATE SET multiple = EXCLUDED.multiple
        """, (VLERICK_YEAR, key, mult))

    # Seed NACE mapping
    for prefix, sector in NACE_MAPPING.items():
        cur.execute("""
            INSERT INTO nace_vlerick_mapping (nace_prefix, vlerick_sector)
            VALUES (%s, %s)
            ON CONFLICT (nace_prefix)
            DO UPDATE SET vlerick_sector = EXCLUDED.vlerick_sector
        """, (prefix, sector))

    conn.commit()

    cur.execute("SELECT COUNT(*) FROM vlerick_multiple WHERE year = %s", (VLERICK_YEAR,))
    n_mult = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM nace_vlerick_mapping")
    n_map = cur.fetchone()[0]

    cur.close()
    conn.close()

    print(f"Seeded {n_mult} Vlerick multiples for year {VLERICK_YEAR}")
    print(f"Seeded {n_map} NACE prefix mappings")


if __name__ == "__main__":
    main()
