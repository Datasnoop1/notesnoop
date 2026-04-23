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
        # Keep the cached company_info code for speed, but resolve the label from
        # the versioned KBO code table so the description stays aligned with the
        # actual NACE version behind that code.
        header = fetch_one("""
            SELECT e.enterprise_number, e.status, e.start_date,
                   e.juridical_form AS "jf_label",
                   COALESCE(ci.name, d.denomination, e.enterprise_number) AS "name",
                   COALESCE(ci.city, a.municipality_nl) AS "city",
                   a.zipcode, a.street_nl AS "street", a.house_number,
                   COALESCE(ci.nace_code, act.nace_code) AS "nace_code",
                   COALESCE(
                       nace_nl.description,
                       nace_fr.description,
                       nace_en.description,
                       nl.description,
                       COALESCE(ci.nace_code, act.nace_code)
                   ) AS "nace_label",
                   (SELECT value FROM contact WHERE entity_number = e.enterprise_number AND contact_type = 'WEB' LIMIT 1) AS "website"
            FROM enterprise e
            LEFT JOIN company_info ci ON ci.enterprise_number = e.enterprise_number
            LEFT JOIN denomination d ON d.entity_number = e.enterprise_number
                 AND d.type_of_denomination = '001' AND d.language IN ('2','1')
            LEFT JOIN address a ON a.entity_number = e.enterprise_number AND a.type_of_address = 'REGO'
            LEFT JOIN LATERAL (
                SELECT act.nace_code, act.nace_version
                FROM activity act
                WHERE act.entity_number = e.enterprise_number
                  AND act.activity_group = '001'
                  AND act.classification = 'MAIN'
                  AND (ci.nace_code IS NULL OR act.nace_code = ci.nace_code)
                ORDER BY
                    CASE
                        WHEN ci.nace_code IS NOT NULL AND act.nace_code = ci.nace_code THEN 0
                        ELSE 1
                    END,
                    CASE act.nace_version
                        WHEN '2025' THEN 0
                        WHEN '2008' THEN 1
                        WHEN '2003' THEN 2
                        ELSE 3
                    END,
                    act.nace_code
                LIMIT 1
            ) act ON TRUE
            LEFT JOIN code nace_nl
                   ON nace_nl.category = ('Nace' || act.nace_version)
                  AND nace_nl.code = act.nace_code
                  AND nace_nl.language = 'NL'
            LEFT JOIN code nace_fr
                   ON nace_fr.category = ('Nace' || act.nace_version)
                  AND nace_fr.code = act.nace_code
                  AND nace_fr.language = 'FR'
            LEFT JOIN code nace_en
                   ON nace_en.category = ('Nace' || act.nace_version)
                  AND nace_en.code = act.nace_code
                  AND nace_en.language = 'EN'
            LEFT JOIN nace_lookup nl ON nl.nace_code = COALESCE(ci.nace_code, act.nace_code)
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
