"""Companies routers — shared helpers, constants, and prompt templates."""

import logging
from typing import Optional

import psycopg2.extras

from db import fetch_one, get_conn
from utils import clean_cbe

logger = logging.getLogger(__name__)


ROLE_LABELS = {
    "fct:m10": "Director", "fct:m11": "Managing director",
    "fct:m12": "Chairman", "fct:m13": "Administrator",
    "fct:m14": "Secretary", "fct:m15": "Treasurer",
    "fct:m20": "Statutory auditor", "fct:m30": "Liquidator",
    "fct:m40": "Daily management",
}

MAX_NETWORK_NODES = 200

MAX_DEEP_NETWORK_NODES = 100

STAATSBLAD_BASE = "https://www.ejustice.just.fgov.be"

ADMIN_EXTRACTION_PROMPT = """Given this Belgian Staatsblad (Official Gazette) publication about board changes for company {name} (CBE {cbe}):

{pdf_text}

Extract all person names and their roles (e.g. Bestuurder, Zaakvoerder, Gedelegeerd bestuurder, Vaste vertegenwoordiger, etc).
Return JSON:
{{
  "appointments": [{{"name": "Full Name", "role": "Bestuurder"}}],
  "resignations": [{{"name": "Full Name", "role": "Bestuurder"}}]
}}
Return only the JSON, no markdown fences."""


def _clean_cbe(identifier) -> Optional[str]:
    """Strip dots/spaces from identifier, return 10-digit CBE or None."""
    if not identifier:
        return None
    c = clean_cbe(identifier)
    return c if c.isdigit() and len(c) == 10 else None


def _serialize_row(row: dict) -> dict:
    """Convert Decimal/date types to JSON-safe primitives."""
    import decimal
    import datetime
    out = {}
    for k, v in row.items():
        if isinstance(v, decimal.Decimal):
            out[k] = float(v)
        elif isinstance(v, (datetime.date, datetime.datetime)):
            out[k] = str(v)
        else:
            out[k] = v
    return out


def _resolve_nace_label(
    nace_code: Optional[str],
    preferred_version: Optional[str] = "2008",
) -> Optional[str]:
    """Resolve one NACE code to a display label.

    Prefer the requested KBO version when we know it, then fall back to the
    legacy static lookup so older rows still display something useful.
    """
    if not nace_code:
        return None

    preferred_category = f"Nace{preferred_version}" if preferred_version else None
    row = fetch_one(
        """
        SELECT COALESCE(
            preferred_nl.description,
            preferred_fr.description,
            preferred_en.description,
            legacy.description,
            q.nace_code
        ) AS description
        FROM (SELECT %s AS nace_code, %s AS preferred_category) q
        LEFT JOIN code preferred_nl
               ON preferred_nl.category = q.preferred_category
              AND preferred_nl.code = q.nace_code
              AND preferred_nl.language = 'NL'
        LEFT JOIN code preferred_fr
               ON preferred_fr.category = q.preferred_category
              AND preferred_fr.code = q.nace_code
              AND preferred_fr.language = 'FR'
        LEFT JOIN code preferred_en
               ON preferred_en.category = q.preferred_category
              AND preferred_en.code = q.nace_code
              AND preferred_en.language = 'EN'
        LEFT JOIN nace_lookup legacy ON legacy.nace_code = q.nace_code
        """,
        (nace_code, preferred_category),
    )
    return row["description"] if row else nace_code


def _fetch_connections(cbes: list) -> tuple:
    """Batch-fetch subsidiaries and shareholders for a set of CBEs.

    SQL extracted from app/pages/2_company.py fetch_connections().
    """
    if not cbes:
        return [], []
    with get_conn() as conn:
        ph = ",".join(["%s"] * len(cbes))
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            f"SELECT DISTINCT enterprise_number, name, identifier, ownership_pct, country "
            f"FROM participating_interest WHERE enterprise_number IN ({ph})",
            list(cbes),
        )
        subs = [dict(r) for r in cur.fetchall()]

        cur.execute(
            f"SELECT DISTINCT enterprise_number, name, identifier, ownership_pct, shareholder_type "
            f"FROM shareholder WHERE enterprise_number IN ({ph})",
            list(cbes),
        )
        shs = [dict(r) for r in cur.fetchall()]

        cur.close()
        conn.commit()
        return subs, shs


def _fetch_entity_names(cbes: list) -> dict:
    """Batch-resolve CBE numbers to company names.

    SQL extracted from app/pages/2_company.py fetch_entity_names().
    """
    if not cbes:
        return {}
    with get_conn() as conn:
        ph = ",".join(["%s"] * len(cbes))
        cur = conn.cursor()
        cur.execute(
            f"SELECT entity_number, denomination FROM denomination "
            f"WHERE entity_number IN ({ph}) AND type_of_denomination = '001' "
            f"GROUP BY entity_number, denomination",
            list(cbes),
        )
        rows = cur.fetchall()
        cur.close()
        conn.commit()
        return {r[0]: r[1] for r in rows}
