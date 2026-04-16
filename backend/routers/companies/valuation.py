"""Companies valuation router — EV/EBITDA-based valuation using Vlerick M&A Monitor multiples.

Reference: Vlerick Business School, M&A Monitor 2025 (covering 2024 Belgian M&A deals).
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from db import execute, fetch_all, fetch_one, get_connection, put_connection
from utils import clean_cbe

logger = logging.getLogger(__name__)
router = APIRouter()

_INITIALIZED = False  # lazy init guard (per process)


SECTOR_LABELS = {
    "technology":          "Technology",
    "pharmaceutical":      "Pharmaceutical",
    "healthcare":          "Healthcare",
    "energy_utilities":    "Energy & utilities",
    "business_services":   "Business services",
    "entertainment_media": "Entertainment & media",
    "chemistry":           "Chemistry",
    "consumer_goods":      "Consumer goods",
    "industrial_products": "Industrial products",
    "real_estate":         "Real estate",
    "retail":              "Retail",
    "transport_logistics": "Transport & logistics",
    "construction":        "Construction",
}

SIZE_LABELS = {
    "lt_5m":    "<€5M",
    "5_20m":    "€5M–€20M",
    "20_50m":   "€20M–€50M",
    "50_100m":  "€50M–€100M",
    "gt_100m":  ">€100M",
}

PRO_MEMORIA_NOTE = (
    "In a real transaction, certain items are often requalified as debt-like "
    "or cash-like adjustments to net debt — e.g. provisions, deferred tax "
    "liabilities, earnouts, factoring, off-balance-sheet lease commitments, "
    "subordinated shareholder loans, or excess cash. These are negotiated during "
    "due diligence. The net-debt figure shown here is the clean accounting "
    "figure — the actual deal figure typically differs."
)

VLERICK_SOURCE_URL = (
    "https://www.moore.be/sites/default/files/2025-05/2025%20MA%20Monitor.pdf"
)

# Vlerick 2025 Monitor — Belgian M&A transactions in calendar year 2024.
# See scripts/seed_vlerick.py for the canonical seed; duplicated here so the
# router can self-initialize on fresh Postgres (matches the pattern used by
# tier_config and company_enrichment).
_VLERICK_YEAR = 2024

_SIZE_MULTIPLES = [
    ("lt_5m",    5.0,  "<5M EUR deal size"),
    ("5_20m",    6.4,  "5M-20M EUR deal size"),
    ("20_50m",   7.7,  "20M-50M EUR deal size"),
    ("50_100m",  8.1,  "50M-100M EUR deal size"),
    ("gt_100m", 10.5,  ">100M EUR deal size"),
    ("overall",  6.5,  "Belgian M&A market overall"),
]

_SECTOR_MULTIPLES = [
    ("technology", 9.1), ("pharmaceutical", 8.5), ("healthcare", 8.0),
    ("energy_utilities", 7.2), ("business_services", 6.7),
    ("entertainment_media", 6.3), ("chemistry", 6.2), ("consumer_goods", 6.1),
    ("industrial_products", 5.7), ("real_estate", 5.7), ("retail", 5.6),
    ("transport_logistics", 5.5), ("construction", 4.8),
]

_NACE_MAPPING = {
    "01": "industrial_products", "02": "industrial_products", "03": "industrial_products",
    "05": "industrial_products", "06": "industrial_products", "07": "industrial_products",
    "08": "industrial_products", "09": "industrial_products",
    "10": "consumer_goods", "11": "consumer_goods", "12": "consumer_goods",
    "13": "consumer_goods", "14": "consumer_goods", "15": "consumer_goods",
    "16": "industrial_products", "17": "industrial_products", "18": "industrial_products",
    "19": "chemistry", "20": "chemistry", "21": "pharmaceutical",
    "22": "industrial_products", "23": "industrial_products", "24": "industrial_products",
    "25": "industrial_products", "26": "industrial_products", "27": "industrial_products",
    "28": "industrial_products", "29": "industrial_products", "30": "industrial_products",
    "31": "industrial_products", "32": "industrial_products", "33": "industrial_products",
    "35": "energy_utilities", "36": "energy_utilities", "37": "energy_utilities",
    "38": "energy_utilities", "39": "energy_utilities",
    "41": "construction", "42": "construction", "43": "construction",
    "45": "retail", "46": "retail", "47": "retail",
    "49": "transport_logistics", "50": "transport_logistics", "51": "transport_logistics",
    "52": "transport_logistics", "53": "transport_logistics",
    "55": "consumer_goods", "56": "consumer_goods",
    "58": "technology", "59": "entertainment_media", "60": "entertainment_media",
    "61": "technology", "62": "technology", "63": "technology",
    "64": "business_services", "65": "business_services", "66": "business_services",
    "68": "real_estate",
    "69": "business_services", "70": "business_services", "71": "business_services",
    "72": "business_services", "73": "business_services", "74": "business_services",
    "75": "business_services",
    "77": "business_services", "78": "business_services", "79": "business_services",
    "80": "business_services", "81": "business_services", "82": "business_services",
    "84": "business_services", "85": "business_services",
    "86": "healthcare", "87": "healthcare", "88": "healthcare",
    "90": "entertainment_media", "91": "entertainment_media",
    "92": "entertainment_media", "93": "entertainment_media",
    "94": "consumer_goods", "95": "consumer_goods", "96": "consumer_goods",
    "97": "business_services", "98": "business_services", "99": "business_services",
}


def _ensure_tables_and_seed():
    """Create tables and seed Vlerick data if empty. Runs once per process."""
    global _INITIALIZED
    if _INITIALIZED:
        return

    conn = get_connection()
    try:
        cur = conn.cursor()
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

        cur.execute("SELECT COUNT(*) FROM vlerick_multiple WHERE year = %s", (_VLERICK_YEAR,))
        if cur.fetchone()[0] == 0:
            for key, mult, note in _SIZE_MULTIPLES:
                cur.execute("""
                    INSERT INTO vlerick_multiple (year, bucket_type, bucket_key, multiple, source_note)
                    VALUES (%s, 'size', %s, %s, %s)
                    ON CONFLICT (year, bucket_type, bucket_key) DO NOTHING
                """, (_VLERICK_YEAR, key, mult, note))
            for key, mult in _SECTOR_MULTIPLES:
                cur.execute("""
                    INSERT INTO vlerick_multiple (year, bucket_type, bucket_key, multiple)
                    VALUES (%s, 'sector', %s, %s)
                    ON CONFLICT (year, bucket_type, bucket_key) DO NOTHING
                """, (_VLERICK_YEAR, key, mult))

        cur.execute("SELECT COUNT(*) FROM nace_vlerick_mapping")
        if cur.fetchone()[0] == 0:
            for prefix, sector in _NACE_MAPPING.items():
                cur.execute("""
                    INSERT INTO nace_vlerick_mapping (nace_prefix, vlerick_sector)
                    VALUES (%s, %s)
                    ON CONFLICT (nace_prefix) DO NOTHING
                """, (prefix, sector))

        conn.commit()
        cur.close()
        _INITIALIZED = True
        logger.info("Vlerick valuation tables ensured and seeded")
    except Exception:
        conn.rollback()
        logger.exception("Failed to initialize Vlerick tables")
        raise
    finally:
        put_connection(conn)


def _ebitda_to_size_bracket(ebitda: Optional[float], overall_multiple: float) -> str:
    """Map EBITDA to a Vlerick EV-size bracket using the overall multiple as proxy.

    Vlerick's size brackets are EV-based. We estimate EV ≈ EBITDA × overall
    multiple, then find the matching bracket. Simple, stable, good enough for
    bucket assignment (the actual multiple used per bucket differs anyway).
    """
    if not ebitda or ebitda <= 0:
        return "lt_5m"
    proxy_ev = ebitda * overall_multiple
    if proxy_ev < 5_000_000:
        return "lt_5m"
    if proxy_ev < 20_000_000:
        return "5_20m"
    if proxy_ev < 50_000_000:
        return "20_50m"
    if proxy_ev < 100_000_000:
        return "50_100m"
    return "gt_100m"


@router.get("/{cbe}/valuation")
async def get_company_valuation(
    cbe: str,
    sector: Optional[str] = Query(None, description="Override Vlerick sector key"),
):
    """Return 3-year EV/EBITDA-based valuation ladder using Vlerick M&A Monitor.

    - Applies the LATEST Vlerick multiples to all reported years (so EBITDA
      drives the year-over-year delta, not market-multiple shifts).
    - Returns two parallel computations: by size bracket and by sector.
    - `sector` query param overrides auto-detected sector (from NACE mapping).
    """
    cbe = clean_cbe(cbe)

    try:
        _ensure_tables_and_seed()

        # Latest year in our Vlerick data (currently 2024)
        year_row = fetch_one("SELECT MAX(year) AS max_year FROM vlerick_multiple")
        if not year_row or year_row.get("max_year") is None:
            raise HTTPException(
                status_code=503,
                detail="Vlerick reference data not seeded. Run scripts/seed_vlerick.py.",
            )
        data_year = int(year_row["max_year"])

        # Fetch size + sector multiples for that year in one pass
        mults = fetch_all(
            "SELECT bucket_type, bucket_key, multiple FROM vlerick_multiple WHERE year = %s",
            (data_year,),
        )
        size_mults = {m["bucket_key"]: float(m["multiple"]) for m in mults if m["bucket_type"] == "size"}
        sector_mults = {m["bucket_key"]: float(m["multiple"]) for m in mults if m["bucket_type"] == "sector"}
        overall_mult = size_mults.get("overall", 6.5)

        # Last 3 fiscal years of financials
        hist = fetch_all("""
            SELECT fiscal_year, ebitda,
                   lt_financial_debt, st_financial_debt,
                   cash, current_investments
            FROM financial_summary
            WHERE enterprise_number = %s
            ORDER BY fiscal_year DESC
            LIMIT 3
        """, (cbe,))

        if not hist:
            return {
                "status": "no_financial_data",
                "years": [],
                "vlerick_reference": {
                    "data_year": data_year,
                    "report": f"Vlerick M&A Monitor {data_year + 1}",
                    "url": VLERICK_SOURCE_URL,
                },
            }

        # Resolve NACE code → auto-detected Vlerick sector
        company = fetch_one(
            "SELECT nace_code FROM company_info WHERE enterprise_number = %s",
            (cbe,),
        )
        nace_code = company.get("nace_code") if company else None
        nace_sector = None
        if nace_code:
            prefix = nace_code[:2]
            row = fetch_one(
                "SELECT vlerick_sector FROM nace_vlerick_mapping WHERE nace_prefix = %s",
                (prefix,),
            )
            if row:
                nace_sector = row["vlerick_sector"]

        # Apply override or fall back: user param > NACE mapping > business_services
        if sector and sector in sector_mults:
            active_sector = sector
            sector_source = "user_override"
        elif nace_sector and nace_sector in sector_mults:
            active_sector = nace_sector
            sector_source = "nace_mapping"
        else:
            active_sector = "business_services"
            sector_source = "fallback"

        # Determine size bracket from latest available EBITDA
        latest_ebitda = hist[0].get("ebitda") or 0
        size_bracket = _ebitda_to_size_bracket(latest_ebitda, overall_mult)

        size_multiple = size_mults.get(size_bracket, overall_mult)
        sector_multiple = sector_mults.get(active_sector, overall_mult)

        # Build per-year ladder
        years = []
        for row in hist:
            ebitda = row.get("ebitda") or 0
            lt_d = row.get("lt_financial_debt") or 0
            st_d = row.get("st_financial_debt") or 0
            cash = row.get("cash") or 0
            inv = row.get("current_investments") or 0

            financial_debt = float(lt_d + st_d)
            cash_and_eq = float(cash + inv)
            net_debt = financial_debt - cash_and_eq

            ev_size = float(ebitda) * size_multiple if ebitda and ebitda > 0 else 0.0
            ev_sector = float(ebitda) * sector_multiple if ebitda and ebitda > 0 else 0.0

            years.append({
                "fiscal_year": int(row["fiscal_year"]) if row.get("fiscal_year") else None,
                "ebitda": float(ebitda) if ebitda is not None else None,
                "financial_debt": financial_debt,
                "cash_and_equivalents": cash_and_eq,
                "net_debt": net_debt,
                "by_size": {
                    "enterprise_value": ev_size,
                    "equity_value": ev_size - net_debt if ebitda and ebitda > 0 else None,
                },
                "by_sector": {
                    "enterprise_value": ev_sector,
                    "equity_value": ev_sector - net_debt if ebitda and ebitda > 0 else None,
                },
            })

        # Chronological order (oldest → newest) for display
        years.reverse()

        # Dropdown choices for the sector-override UI: names only, no multiples.
        # We intentionally do NOT expose the full Vlerick multiple table to the
        # client — we return only the single multiple applicable to this company,
        # to respect Vlerick's IP (the table is the protected asset; one fact
        # attributed to the source is normal editorial use).
        available_sectors = [
            {"key": k, "label": SECTOR_LABELS.get(k, k)}
            for k in sorted(sector_mults.keys(), key=lambda k: SECTOR_LABELS.get(k, k))
        ]

        return {
            "status": "ok",
            "profile": {
                "nace_code": nace_code,
                "size_bracket": size_bracket,
                "size_bracket_label": SIZE_LABELS.get(size_bracket, size_bracket),
                "size_multiple": size_multiple,
                "vlerick_sector": active_sector,
                "vlerick_sector_label": SECTOR_LABELS.get(active_sector, active_sector),
                "vlerick_sector_source": sector_source,
                "sector_multiple": sector_multiple,
                "available_sectors": available_sectors,
            },
            "years": years,
            "vlerick_reference": {
                "data_year": data_year,
                "report": f"Vlerick M&A Monitor {data_year + 1}",
                "publisher": "Vlerick Business School — Centre for Mergers, Acquisitions and Buyouts",
                "url": VLERICK_SOURCE_URL,
                "note": (
                    f"Multiples shown are Vlerick medians for {data_year} Belgian transactions. "
                    "Applied to each reported year so evolution reflects EBITDA growth, not market-multiple drift."
                ),
            },
            "pro_memoria_note": PRO_MEMORIA_NOTE,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Valuation query failed for %s", cbe)
        raise HTTPException(status_code=500, detail="Internal server error")
