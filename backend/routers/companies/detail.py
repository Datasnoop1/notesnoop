"""Companies detail router — single-company header endpoint."""

import logging

from fastapi import APIRouter, HTTPException

from db import fetch_one
from utils import clean_cbe
from ._helpers import _serialize_row

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# GET /api/companies/{cbe}
# ---------------------------------------------------------------------------

@router.get("/{cbe}")
async def get_company_detail(cbe: str):
    """Full company header detail.

    SQL extracted from app/pages/2_company.py load_company_detail() header query.
    """
    cbe = clean_cbe(cbe)

    try:
        # Fast path: try company_info first (170K rows, indexed)
        header = fetch_one("""
            SELECT e.enterprise_number, e.status, e.start_date,
                   e.juridical_form AS "jf_label",
                   COALESCE(ci.name, d.denomination, e.enterprise_number) AS "name",
                   COALESCE(ci.city, a.municipality_nl) AS "city",
                   a.zipcode, a.street_nl AS "street", a.house_number,
                   ci.nace_code,
                   COALESCE(nl.description, ci.nace_code) AS "nace_label",
                   (SELECT value FROM contact WHERE entity_number = e.enterprise_number AND contact_type = 'WEB' LIMIT 1) AS "website"
            FROM enterprise e
            LEFT JOIN company_info ci ON ci.enterprise_number = e.enterprise_number
            LEFT JOIN denomination d ON d.entity_number = e.enterprise_number
                 AND d.type_of_denomination = '001' AND d.language IN ('2','1')
            LEFT JOIN address a ON a.entity_number = e.enterprise_number AND a.type_of_address = 'REGO'
            LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
            WHERE e.enterprise_number = %s LIMIT 1
        """, (cbe,))

        if not header:
            raise HTTPException(status_code=404, detail=f"Company {cbe} not found")

        return _serialize_row(header)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Company detail query failed")
        raise HTTPException(status_code=500, detail="Internal server error")
