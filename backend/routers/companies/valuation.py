"""Companies valuation router — EV/EBITDA-based valuation using Vlerick M&A Monitor multiples.

Reference: Vlerick Business School, M&A Monitor 2025 (covering 2024 Belgian M&A deals).
"""

import json
import logging
import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ai_client import ai_complete
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
    # Vlerick's Centre for M&A — official home of the annual M&A Monitor.
    # Used with Vlerick's explicit permission (granted 2026-04).
    "https://www.vlerick.com/en/for-companies/research-for-your-company/centre-for-mergers-acquisitions-and-buyouts/"
)

# Reference data year — all three sources publish for calendar year 2024 data.
_DATA_YEAR = 2024

# ── Vlerick 2025 M&A Monitor — Belgian transactions in 2024 ──────────────────
_VLERICK_SIZE = [
    ("lt_5m",    5.0,  "<5M EUR deal size"),
    ("5_20m",    6.4,  "5M-20M EUR deal size"),
    ("20_50m",   7.7,  "20M-50M EUR deal size"),
    ("50_100m",  8.1,  "50M-100M EUR deal size"),
    ("gt_100m", 10.5,  ">100M EUR deal size"),
    ("overall",  6.5,  "Belgian M&A market overall"),
]
_VLERICK_SECTOR = [
    ("technology", 9.1), ("pharmaceutical", 8.5), ("healthcare", 8.0),
    ("energy_utilities", 7.2), ("business_services", 6.7),
    ("entertainment_media", 6.3), ("chemistry", 6.2), ("consumer_goods", 6.1),
    ("industrial_products", 5.7), ("real_estate", 5.7), ("retail", 5.6),
    ("transport_logistics", 5.5), ("construction", 4.8),
]

_ALL_SEEDS = [
    ("vlerick", _VLERICK_SIZE, _VLERICK_SECTOR),
]

_SOURCE_META = {
    "vlerick": {
        "label": "Vlerick M&A Monitor",
        "publisher": "Vlerick Business School — Centre for Mergers, Acquisitions and Buyouts",
        "url": "https://www.vlerick.com/en/for-companies/research-for-your-company/centre-for-mergers-acquisitions-and-buyouts/",
        "kind": "transaction",
        "scope": "Belgian M&A transactions",
        "note": "Belgian mid-market transaction medians. Multiples applied to each reported year so evolution reflects EBITDA growth.",
        "has_size": True,
        "has_sector": True,
    },
}

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
    """Create tables and seed all multiple sources. Runs once per process."""
    global _INITIALIZED
    if _INITIALIZED:
        return

    conn = get_connection()
    try:
        cur = conn.cursor()
        # Base table (name kept for backward compat; now multi-source).
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
        # Add 'source' column, default 'vlerick' so existing rows are tagged.
        cur.execute("""
            ALTER TABLE vlerick_multiple
            ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'vlerick'
        """)
        # Drop the old single-source PK and install a multi-source one
        # (idempotent: only proceeds if the new constraint isn't already there).
        cur.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'vlerick_multiple_multi_pkey'
                      AND conrelid = 'vlerick_multiple'::regclass
                ) THEN
                    ALTER TABLE vlerick_multiple DROP CONSTRAINT IF EXISTS vlerick_multiple_pkey;
                    ALTER TABLE vlerick_multiple ADD CONSTRAINT vlerick_multiple_multi_pkey
                        PRIMARY KEY (source, year, bucket_type, bucket_key);
                END IF;
            END $$
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nace_vlerick_mapping (
                nace_prefix TEXT PRIMARY KEY,
                vlerick_sector TEXT NOT NULL
            )
        """)

        # Seed each source if not present for _DATA_YEAR
        for src_key, size_rows, sector_rows in _ALL_SEEDS:
            cur.execute(
                "SELECT COUNT(*) FROM vlerick_multiple WHERE year = %s AND source = %s",
                (_DATA_YEAR, src_key),
            )
            if cur.fetchone()[0] > 0:
                continue
            for key, mult, *note in size_rows:
                cur.execute("""
                    INSERT INTO vlerick_multiple (source, year, bucket_type, bucket_key, multiple, source_note)
                    VALUES (%s, %s, 'size', %s, %s, %s)
                    ON CONFLICT (source, year, bucket_type, bucket_key) DO NOTHING
                """, (src_key, _DATA_YEAR, key, mult, note[0] if note else None))
            for row in sector_rows:
                key, mult = row[0], row[1]
                cur.execute("""
                    INSERT INTO vlerick_multiple (source, year, bucket_type, bucket_key, multiple)
                    VALUES (%s, %s, 'sector', %s, %s)
                    ON CONFLICT (source, year, bucket_type, bucket_key) DO NOTHING
                """, (src_key, _DATA_YEAR, key, mult))

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
        logger.info("Valuation tables ensured and seeded (vlerick + damodaran + argos)")
    except Exception:
        conn.rollback()
        logger.exception("Failed to initialize valuation tables")
        raise
    finally:
        put_connection(conn)


_SECTOR_CLASSIFY_PROMPT = """You are a sector classifier for Belgian M&A deals. Pick exactly one label from the closed list. Return ONLY JSON.

Company facts:
- Name: {name}
- NACE: {nace_code} — {nace_desc}
{facts}

Closed list (pick exactly one key):
technology | pharmaceutical | healthcare | energy_utilities |
business_services | entertainment_media | chemistry | consumer_goods |
industrial_products | real_estate | retail | transport_logistics | construction

Disambiguation rules:
- retail = B2C sales to end-consumers. Wholesale/B2B distribution = consumer_goods or industrial_products depending on what is sold.
- Holding companies with no own operations: classify by the dominant operating activity of the group. If diversified, use business_services.
- Software/SaaS/IT services = technology. R&D services (non-software) = business_services.
- Restaurants, hotels, food producers = consumer_goods. Food retail stores = retail.
- Pharma manufacturing = pharmaceutical. Hospitals/clinics/elderly care = healthcare.

Return ONLY: {{"sector": "<key from closed list>", "confidence": "high|medium|low", "reasoning": "<one sentence>"}}"""


def _ensure_sector_columns():
    """Add vlerick_sector cache columns to company_enrichment if missing (idempotent)."""
    try:
        execute("""
            CREATE TABLE IF NOT EXISTS company_enrichment (
                enterprise_number VARCHAR(10) PRIMARY KEY,
                summary TEXT,
                generated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        for col, typ in [
            ("vlerick_sector", "TEXT"),
            ("vlerick_sector_confidence", "TEXT"),
            ("vlerick_sector_reasoning", "TEXT"),
            ("vlerick_sector_generated_at", "TIMESTAMP"),
        ]:
            try:
                execute(f"ALTER TABLE company_enrichment ADD COLUMN IF NOT EXISTS {col} {typ}")
            except Exception:
                pass
    except Exception:
        logger.exception("Failed ensuring sector columns")


def _build_classification_facts(cbe: str) -> str:
    """Pull high-signal fields from company_enrichment to feed the classifier.

    Returns a formatted fact-bullet string, or "" if no enrichment exists.
    """
    try:
        enr = fetch_one("""
            SELECT summary, website_summary, linkedin_summary, ai_insights
            FROM company_enrichment
            WHERE enterprise_number = %s
        """, (cbe,))
    except Exception:
        return ""
    if not enr:
        return ""

    parts: list[str] = []

    # ai_insights: richest structured source
    raw = enr.get("ai_insights")
    if raw:
        try:
            insights = json.loads(raw) if isinstance(raw, str) else raw
            for key, label in [
                ("business_description", "Business description"),
                ("products", "Products/services"),
                ("customers", "Customers"),
                ("market_position", "Market position"),
                ("group_context", "Group context"),
            ]:
                v = insights.get(key)
                if isinstance(v, list):
                    v = "; ".join(str(x) for x in v if x)
                if v:
                    parts.append(f"{label}: {v}")
        except Exception:
            pass

    # LinkedIn: industry + specialties are very high signal
    raw = enr.get("linkedin_summary")
    if raw:
        try:
            ls = json.loads(raw) if isinstance(raw, str) else raw
            if ls.get("industry"):
                parts.append(f"LinkedIn industry: {ls['industry']}")
            if ls.get("specialties"):
                parts.append(f"LinkedIn specialties: {ls['specialties']}")
        except Exception:
            pass

    # Website summary: what they actually sell, in their own words
    raw = enr.get("website_summary")
    if raw:
        try:
            ws = json.loads(raw) if isinstance(raw, str) else raw
            if ws.get("summary"):
                parts.append(f"Website summary: {ws['summary']}")
            if ws.get("products"):
                parts.append(f"Products (website): {ws['products']}")
        except Exception:
            pass

    # Fallback short summary
    if not parts and enr.get("summary"):
        parts.append(f"Short summary: {enr['summary']}")

    return "\n".join(f"- {p}" for p in parts)


async def _classify_sector_via_ai(
    cbe: str, name: str, nace_code: str, nace_desc: str, valid_sectors: set[str]
) -> Optional[dict]:
    """Ask OpenRouter (gemini-2.5-flash) to pick one of the 13 Vlerick sectors.

    If no enrichment data exists for the company, first triggers the light
    enrichment path (NACE + financials-based summary, no scraping) so the
    classifier has at least something to work with. Returns
    {"sector", "confidence", "reasoning"} or None on any failure.
    """
    facts = _build_classification_facts(cbe)
    if not facts:
        # No cached enrichment — run the light summary path to seed something.
        try:
            from .enrichment import generate_light_summary
            summary = await generate_light_summary(cbe)
            if summary:
                facts = _build_classification_facts(cbe)
        except Exception:
            logger.exception("Light summary generation failed for %s", cbe)
    if not facts:
        return None  # Still nothing — fall back to NACE mapping

    prompt = _SECTOR_CLASSIFY_PROMPT.format(
        name=name or "Unknown",
        nace_code=nace_code or "—",
        nace_desc=nace_desc or "—",
        facts=facts,
    )

    try:
        response = await ai_complete(prompt, model="google/gemini-2.5-flash", max_tokens=150)
    except Exception:
        logger.exception("AI sector classification call failed for %s", cbe)
        return None
    if not response:
        return None

    # Parse JSON out of the response (model may wrap in markdown)
    try:
        m = re.search(r"\{.*\}", response, re.DOTALL)
        if not m:
            return None
        parsed = json.loads(m.group())
        sector = str(parsed.get("sector", "")).strip().lower()
        if sector not in valid_sectors:
            logger.info("AI returned invalid sector '%s' for %s", sector, cbe)
            return None
        confidence = str(parsed.get("confidence", "medium")).strip().lower()
        if confidence not in {"high", "medium", "low"}:
            confidence = "medium"
        reasoning = str(parsed.get("reasoning", "")).strip()[:400]
        return {"sector": sector, "confidence": confidence, "reasoning": reasoning}
    except Exception:
        logger.exception("Failed to parse sector classification response for %s", cbe)
        return None


def _save_ai_sector(cbe: str, sector: str, confidence: str, reasoning: str):
    """Upsert the AI-classified sector into company_enrichment."""
    try:
        execute("""
            INSERT INTO company_enrichment (enterprise_number, vlerick_sector,
                vlerick_sector_confidence, vlerick_sector_reasoning, vlerick_sector_generated_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (enterprise_number)
            DO UPDATE SET
                vlerick_sector = EXCLUDED.vlerick_sector,
                vlerick_sector_confidence = EXCLUDED.vlerick_sector_confidence,
                vlerick_sector_reasoning = EXCLUDED.vlerick_sector_reasoning,
                vlerick_sector_generated_at = EXCLUDED.vlerick_sector_generated_at
        """, (cbe, sector, confidence, reasoning))
    except Exception:
        logger.exception("Failed to save AI sector for %s", cbe)


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


def _parse_include_cbes(raw: Optional[str], primary: str) -> list[str]:
    """Parse a comma-separated ``include`` query param into a clean list of
    CBEs. Drops blanks, the primary itself, and duplicates. Capped at 9 so
    the consolidated payload stays bounded."""
    if not raw:
        return []
    out: list[str] = []
    seen = {primary}
    for raw_cbe in raw.split(","):
        c = clean_cbe(raw_cbe)
        if not c or c in seen:
            continue
        seen.add(c)
        out.append(c)
        if len(out) >= 9:
            break
    return out


def _group_label(primary_name: str, n_extra: int) -> str:
    return primary_name if n_extra == 0 else f"{primary_name} (+ {n_extra} group cos.)"


@router.get("/{cbe}/valuation")
async def get_company_valuation(
    cbe: str,
    sector: Optional[str] = Query(None, description="Override Vlerick sector key"),
    source: Optional[str] = Query("vlerick", description="Multiple source: vlerick | damodaran | argos"),
    include: Optional[str] = Query(None, description="Comma-separated CBEs to consolidate as a group (max 9)"),
):
    """Return 3-year EV/EBITDA-based valuation ladder using Vlerick M&A Monitor.

    - Applies the LATEST Vlerick multiples to all reported years (so EBITDA
      drives the year-over-year delta, not market-multiple shifts).
    - Returns two parallel computations: by size bracket and by sector.
    - `sector` query param overrides auto-detected sector (from NACE mapping).
    - `include` consolidates the primary CBE with one or more group companies:
      EBITDA / debt / cash are summed per fiscal year, and the multiple lookup
      uses the primary's profile (NACE, AI sector). Years where the primary
      has no data are dropped; years where some included companies lack data
      are still returned with a `partial_years` warning so the user can judge
      coverage.
    """
    cbe = clean_cbe(cbe)
    include_cbes = _parse_include_cbes(include, cbe)

    try:
        _ensure_tables_and_seed()
        _ensure_sector_columns()

        # Validate source
        active_source = (source or "vlerick").lower()
        if active_source not in _SOURCE_META:
            active_source = "vlerick"
        src_meta = _SOURCE_META[active_source]

        # Latest year in the chosen source
        year_row = fetch_one(
            "SELECT MAX(year) AS max_year FROM vlerick_multiple WHERE source = %s",
            (active_source,),
        )
        if not year_row or year_row.get("max_year") is None:
            raise HTTPException(
                status_code=503,
                detail=f"Reference data not seeded for source '{active_source}'.",
            )
        data_year = int(year_row["max_year"])

        # Fetch size + sector multiples for that year+source in one pass
        mults = fetch_all(
            "SELECT bucket_type, bucket_key, multiple FROM vlerick_multiple WHERE year = %s AND source = %s",
            (data_year, active_source),
        )
        size_mults = {m["bucket_key"]: float(m["multiple"]) for m in mults if m["bucket_type"] == "size"}
        sector_mults = {m["bucket_key"]: float(m["multiple"]) for m in mults if m["bucket_type"] == "sector"}
        # 'overall' multiple: prefer size-overall; else fall back to the mean of the sector multiples
        overall_mult = size_mults.get("overall")
        if overall_mult is None and sector_mults:
            overall_mult = sum(sector_mults.values()) / len(sector_mults)
        overall_mult = overall_mult or 6.5

        # Last 3 fiscal years of financials. `financial_summary` can have
        # multiple rows per fiscal year (one per filing / amendment), so
        # de-dup via ROW_NUMBER keeping the latest deposit_key per year —
        # same pattern used in financials.py and the NBB pipeline.
        hist_primary = fetch_all("""
            SELECT enterprise_number, fiscal_year, ebitda,
                   lt_financial_debt, st_financial_debt,
                   cash, current_investments
            FROM (
                SELECT *,
                       ROW_NUMBER() OVER (
                           PARTITION BY fiscal_year
                           ORDER BY deposit_key DESC
                       ) AS rn
                FROM financial_summary
                WHERE enterprise_number = %s
            ) sub
            WHERE rn = 1
            ORDER BY fiscal_year DESC
            LIMIT 3
        """, (cbe,))

        # Group consolidation: for each year the primary reports, sum the same
        # year across the included companies. Companies that don't report for
        # that year are skipped (counted under ``partial_years``).
        partial_years: list[int] = []
        included_meta: list[dict] = []
        if include_cbes and hist_primary:
            primary_years = [int(r["fiscal_year"]) for r in hist_primary if r.get("fiscal_year") is not None]
            ph = ",".join(["%s"] * len(include_cbes))
            year_ph = ",".join(["%s"] * len(primary_years)) if primary_years else "NULL"
            extra_rows = fetch_all(
                f"""
                SELECT enterprise_number, fiscal_year, ebitda,
                       lt_financial_debt, st_financial_debt,
                       cash, current_investments
                FROM (
                    SELECT *,
                           ROW_NUMBER() OVER (
                               PARTITION BY enterprise_number, fiscal_year
                               ORDER BY deposit_key DESC
                           ) AS rn
                    FROM financial_summary
                    WHERE enterprise_number IN ({ph})
                      AND fiscal_year IN ({year_ph})
                ) sub
                WHERE rn = 1
                """,
                include_cbes + primary_years,
            )
            extra_by_year: dict[int, list[dict]] = {}
            for row in extra_rows:
                fy = int(row["fiscal_year"])
                extra_by_year.setdefault(fy, []).append(row)

            # Build list of group company display names for the response
            name_rows = fetch_all(
                f"SELECT enterprise_number, name FROM company_info WHERE enterprise_number IN ({ph})",
                include_cbes,
            )
            name_map = {r["enterprise_number"]: r.get("name") for r in name_rows}
            for c in include_cbes:
                included_meta.append({
                    "cbe": c,
                    "name": name_map.get(c) or c,
                })

            # Aggregate per primary year
            agg: list[dict] = []
            for primary_row in hist_primary:
                fy = int(primary_row["fiscal_year"]) if primary_row.get("fiscal_year") is not None else None
                if fy is None:
                    continue
                ebitda = float(primary_row.get("ebitda") or 0)
                lt_d = float(primary_row.get("lt_financial_debt") or 0)
                st_d = float(primary_row.get("st_financial_debt") or 0)
                cash = float(primary_row.get("cash") or 0)
                inv = float(primary_row.get("current_investments") or 0)
                contributors = 1
                for extra in extra_by_year.get(fy, []):
                    ebitda += float(extra.get("ebitda") or 0)
                    lt_d += float(extra.get("lt_financial_debt") or 0)
                    st_d += float(extra.get("st_financial_debt") or 0)
                    cash += float(extra.get("cash") or 0)
                    inv += float(extra.get("current_investments") or 0)
                    contributors += 1
                if contributors < 1 + len(include_cbes):
                    partial_years.append(fy)
                agg.append({
                    "fiscal_year": fy,
                    "ebitda": ebitda,
                    "lt_financial_debt": lt_d,
                    "st_financial_debt": st_d,
                    "cash": cash,
                    "current_investments": inv,
                })
            hist = agg
        else:
            hist = hist_primary

        if not hist:
            return {
                "status": "no_financial_data",
                "years": [],
                "source": {
                    "key": active_source,
                    "label": src_meta["label"],
                    "publisher": src_meta["publisher"],
                    "url": src_meta["url"],
                    "kind": src_meta["kind"],
                    "has_size": src_meta["has_size"],
                    "has_sector": src_meta["has_sector"],
                    "data_year": data_year,
                },
                "available_sources": [
                    {"key": k, "label": v["label"], "has_size": v["has_size"], "has_sector": v["has_sector"]}
                    for k, v in _SOURCE_META.items()
                ],
                "vlerick_reference": {
                    "data_year": data_year,
                    "report": f"Vlerick M&A Monitor {data_year + 1}",
                    "url": VLERICK_SOURCE_URL,
                },
            }

        # Resolve NACE code → auto-detected Vlerick sector (baseline)
        company = fetch_one(
            "SELECT ci.nace_code, ci.name, nl.description AS nace_desc "
            "FROM company_info ci "
            "LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code "
            "WHERE ci.enterprise_number = %s",
            (cbe,),
        )
        nace_code = company.get("nace_code") if company else None
        company_name = company.get("name") if company else ""
        nace_desc = company.get("nace_desc") if company else ""
        nace_sector = None
        if nace_code:
            prefix = nace_code[:2]
            row = fetch_one(
                "SELECT vlerick_sector FROM nace_vlerick_mapping WHERE nace_prefix = %s",
                (prefix,),
            )
            if row:
                nace_sector = row["vlerick_sector"]

        # AI-classified sector (cached in company_enrichment.vlerick_sector).
        # Only used when the user hasn't explicitly overridden via ?sector=.
        ai_sector: Optional[str] = None
        ai_confidence: Optional[str] = None
        ai_reasoning: Optional[str] = None
        if not sector:
            try:
                cached = fetch_one("""
                    SELECT vlerick_sector, vlerick_sector_confidence, vlerick_sector_reasoning
                    FROM company_enrichment
                    WHERE enterprise_number = %s AND vlerick_sector IS NOT NULL
                """, (cbe,))
            except Exception:
                cached = None
            if cached and cached.get("vlerick_sector") in sector_mults:
                ai_sector = cached["vlerick_sector"]
                ai_confidence = cached.get("vlerick_sector_confidence")
                ai_reasoning = cached.get("vlerick_sector_reasoning")
            else:
                # Try to classify live — only succeeds if enrichment data already exists
                result = await _classify_sector_via_ai(
                    cbe, company_name, nace_code or "", nace_desc or "",
                    valid_sectors=set(sector_mults.keys()),
                )
                if result:
                    ai_sector = result["sector"]
                    ai_confidence = result["confidence"]
                    ai_reasoning = result["reasoning"]
                    _save_ai_sector(cbe, ai_sector, ai_confidence, ai_reasoning)

        # Precedence: user param > AI classification > NACE mapping > fallback
        if sector and sector in sector_mults:
            active_sector = sector
            sector_source = "user_override"
        elif ai_sector and ai_sector in sector_mults:
            active_sector = ai_sector
            sector_source = "ai_classification"
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
                "ai_sector_confidence": ai_confidence,
                "ai_sector_reasoning": ai_reasoning,
                "sector_multiple": sector_multiple,
                "available_sectors": available_sectors,
            },
            "group": {
                "primary_cbe": cbe,
                "primary_name": company_name,
                "included": included_meta,
                "label": _group_label(company_name or cbe, len(include_cbes)),
                "partial_years": sorted(set(partial_years), reverse=True),
            } if include_cbes else None,
            "years": years,
            "source": {
                "key": active_source,
                "label": src_meta["label"],
                "publisher": src_meta["publisher"],
                "url": src_meta["url"],
                "kind": src_meta["kind"],
                "scope": src_meta["scope"],
                "note": src_meta["note"],
                "has_size": src_meta["has_size"],
                "has_sector": src_meta["has_sector"],
                "data_year": data_year,
            },
            "available_sources": [
                {"key": k, "label": v["label"], "has_size": v["has_size"], "has_sector": v["has_sector"]}
                for k, v in _SOURCE_META.items()
            ],
            "vlerick_reference": {
                "data_year": data_year,
                "report": f"{src_meta['label']} ({data_year} data)",
                "publisher": src_meta["publisher"],
                "url": src_meta["url"],
                "note": src_meta["note"],
            },
            "pro_memoria_note": PRO_MEMORIA_NOTE,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Valuation query failed for %s", cbe)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# POST /api/companies/{cbe}/valuation/ai-commentary
# ---------------------------------------------------------------------------


def _format_eur(v: Optional[float]) -> str:
    if v is None:
        return "n/a"
    if abs(v) >= 1_000_000:
        return f"\u20AC{v / 1_000_000:.1f}M"
    if abs(v) >= 1_000:
        return f"\u20AC{v / 1_000:.0f}k"
    return f"\u20AC{v:,.0f}"


def _build_valuation_prompt(payload: dict, company_name: str | None = None) -> str:
    """Format the valuation result into a compact prompt for the LLM.

    The LLM is given numbers + sector + multiple, but no instructions on
    direction so it can call out anything noteworthy: trend, sector vs
    size disagreement, group-aggregation caveats, etc. The sector source
    (`user_override` / `ai_classification` / `nace_mapping` / `fallback`)
    plus AI sector reasoning are passed through so the commentary can
    explain WHY a given Vlerick sector is the right comp for this
    company instead of just stating the number.
    """
    profile = payload.get("profile") or {}
    years = payload.get("years") or []
    src = payload.get("source") or {}
    group = payload.get("group")

    sector_source_human = {
        "user_override": "user manually selected this sector",
        "ai_classification": "AI-classified from the company description",
        "nace_mapping": f"derived from NACE prefix {profile.get('nace_code') or '?'}",
        "fallback": "default fallback (no NACE / no AI signal)",
    }.get(profile.get("vlerick_sector_source") or "", "unspecified")

    lines = [
        f"Company: {company_name or payload.get('company_name') or profile.get('company_name') or 'Belgian company'}",
        f"NACE: {profile.get('nace_code') or '\u2014'}",
        f"Vlerick sector: {profile.get('vlerick_sector_label')} (multiple {profile.get('sector_multiple'):.1f}x)",
        f"Sector chosen because: {sector_source_human}",
    ]
    if profile.get("ai_sector_reasoning"):
        lines.append(f"AI sector reasoning: {profile['ai_sector_reasoning']}")
    if profile.get("ai_sector_confidence"):
        lines.append(f"AI sector confidence: {profile['ai_sector_confidence']}")
    lines.extend([
        f"Size bracket: {profile.get('size_bracket_label')} (multiple {profile.get('size_multiple'):.1f}x)",
        f"Multiple source: {src.get('label')} ({src.get('data_year')})",
    ])
    if group:
        lines.append(
            f"Consolidated group: {group.get('label')} "
            f"({1 + len(group.get('included') or [])} cos.)"
        )
        if group.get("partial_years"):
            lines.append(
                "Partial-coverage years (one or more group cos. did not file): "
                + ", ".join(str(y) for y in group["partial_years"])
            )
    lines.append("\nPer-year EV (EBITDA \u00d7 multiple), most-recent last:")
    for y in years:
        lines.append(
            f"- FY{y.get('fiscal_year')}: EBITDA {_format_eur(y.get('ebitda'))}, "
            f"net debt {_format_eur(y.get('net_debt'))}, "
            f"EV(size) {_format_eur((y.get('by_size') or {}).get('enterprise_value'))}, "
            f"EV(sector) {_format_eur((y.get('by_sector') or {}).get('enterprise_value'))}"
        )
    return "\n".join(lines)


async def _generate_and_cache_valuation_commentary(
    cbe: str,
    sector: Optional[str] = None,
    source: Optional[str] = "vlerick",
    include: Optional[str] = None,
    lang: Optional[str] = None,
) -> dict:
    """Plain-Python worker — callable from the route AND from scheduled
    scripts. FastAPI's Query(None) defaults can't be used when calling the
    route handler directly from a script (Query objects aren't None), so
    the business logic lives here and the route is a thin wrapper."""
    cbe = clean_cbe(cbe)

    try:
        valuation = await get_company_valuation(cbe, sector=sector, source=source, include=include)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Underlying valuation call failed for %s", cbe)
        raise HTTPException(status_code=500, detail="Could not compute valuation")

    if isinstance(valuation, dict) and valuation.get("status") != "ok":
        return {"commentary": None, "reason": "no_data"}

    # Pull a friendly company name to anchor the commentary.
    company_name = (valuation.get("group") or {}).get("primary_name") or ""
    if not company_name:
        try:
            row = fetch_one("SELECT name FROM company_info WHERE enterprise_number = %s", (cbe,))
            company_name = (row or {}).get("name") or ""
        except Exception:
            pass

    prompt = _build_valuation_prompt(valuation, company_name=company_name)
    system = (
        "You are a private-equity analyst commenting on a Belgian company's "
        "EV/EBITDA-based valuation. Reply with STRICT JSON only (no prose, no "
        "code fences) with EXACTLY these two keys:\n"
        '  "sector_rationale": 2\u20133 sentences on WHY the chosen Vlerick '
        "sector is the right comparable for this company \u2014 reference the "
        "AI sector reasoning if provided, otherwise the NACE code / activity, "
        "business model, and typical growth / margin profile of the sector. "
        "This is about the SECTOR, not about the company's own numbers.\n"
        '  "valuation_remarks": 2\u20133 sentences of company-specific '
        "observations \u2014 EBITDA trend, sector-vs-size-bracket spread, "
        "net-debt position, one-off items, group-consolidation caveats, "
        "loss-making years. Refer to actual figures from the input.\n"
        "Both fields are plain strings. Never invent numbers \u2014 only use "
        "values present in the input. Do not wrap the response in an array."
    )

    try:
        text = await ai_complete(prompt, system=system, max_tokens=700, lang=lang)
    except Exception:
        logger.exception("AI valuation commentary failed for %s", cbe)
        raise HTTPException(status_code=503, detail="AI service unavailable")

    if not text:
        raise HTTPException(status_code=503, detail="AI service unavailable")

    # Parse the JSON response. Fall back to treating the whole reply as
    # valuation_remarks if the LLM didn't produce valid JSON — keeps the
    # feature working through any prompt-instability teething issues.
    sector_rationale: Optional[str] = None
    valuation_remarks: Optional[str] = None
    raw = text.strip()
    # Strip accidental markdown code-fence wrappers.
    if raw.startswith("```"):
        raw = raw.strip("`")
        # Remove language tag like "json" on the first line.
        if "\n" in raw:
            first, rest = raw.split("\n", 1)
            if first.strip().lower() in ("json", "js", ""):
                raw = rest
        raw = raw.strip().strip("`").strip()
    try:
        import json as _json
        parsed = _json.loads(raw)
        if isinstance(parsed, list) and parsed:
            parsed = parsed[0]
        if isinstance(parsed, dict):
            sr = parsed.get("sector_rationale")
            vr = parsed.get("valuation_remarks")
            if isinstance(sr, str):
                sector_rationale = sr.strip() or None
            if isinstance(vr, str):
                valuation_remarks = vr.strip() or None
    except Exception:
        pass

    if sector_rationale is None and valuation_remarks is None:
        # Legacy-style single-paragraph response \u2014 surface the whole
        # reply under valuation_remarks so the user still sees something.
        valuation_remarks = raw

    # Cache as JSON so PDF primer + subsequent views can pull both sections.
    import json as _json2
    cache_payload = _json2.dumps({
        "sector_rationale": sector_rationale,
        "valuation_remarks": valuation_remarks,
    })
    try:
        from db import execute as _exec
        _exec(
            """INSERT INTO valuation_commentary_cache
                   (enterprise_number, commentary, sector_used, source_used, lang, generated_at)
               VALUES (%s, %s, %s, %s, %s, NOW())
               ON CONFLICT (enterprise_number) DO UPDATE SET
                   commentary   = EXCLUDED.commentary,
                   sector_used  = EXCLUDED.sector_used,
                   source_used  = EXCLUDED.source_used,
                   lang         = EXCLUDED.lang,
                   generated_at = NOW()""",
            (cbe, cache_payload, sector, source, (lang or "en")[:2]),
        )
    except Exception:
        logger.exception("valuation commentary cache write failed (non-fatal)")

    # Return both structured fields AND the legacy `commentary` field
    # (concatenation of the two) so older clients still work through the
    # transition.
    legacy = "\n\n".join(p for p in (sector_rationale, valuation_remarks) if p)
    return {
        "sector_rationale": sector_rationale,
        "valuation_remarks": valuation_remarks,
        "commentary": legacy or None,
    }


@router.post("/{cbe}/valuation/ai-commentary")
async def valuation_ai_commentary(
    cbe: str,
    sector: Optional[str] = Query(None),
    source: Optional[str] = Query("vlerick"),
    include: Optional[str] = Query(None),
    lang: Optional[str] = Query(None),
):
    """Thin wrapper around _generate_and_cache_valuation_commentary so the
    FastAPI Query defaults only apply in the HTTP path. Scripts call the
    worker directly."""
    return await _generate_and_cache_valuation_commentary(
        cbe=cbe, sector=sector, source=source, include=include, lang=lang,
    )
