"""Companies detail router — single-company header endpoint."""

import logging

from fastapi import APIRouter, HTTPException, Response

from db import fetch_one
from utils import clean_cbe
from ._helpers import _resolve_nace_label, _serialize_row

logger = logging.getLogger(__name__)
router = APIRouter()


# Compact form abbreviation derived from the long NL label. The KBO
# label conventions are stable ("Besloten vennootschap", "Naamloze
# vennootschap", etc.) so a small lookup beats trying to infer from
# the numeric code (which already varies between historical, 2019
# WVV, and special-purpose forms).
_FORM_SHORT_FROM_LABEL: dict[str, str] = {
    "Besloten vennootschap": "BV",
    "Naamloze vennootschap": "NV",
    "Commanditaire vennootschap": "CommV",
    "Vennootschap onder firma": "VOF",
    "Coöperatieve vennootschap": "CV",
    "Coöperatieve vennootschap met beperkte aansprakelijkheid": "CVBA",
    "Coöperatieve vennootschap met onbeperkte aansprakelijkheid": "CVOA",
    "Vereniging zonder winstoogmerk": "VZW",
    "Internationale vereniging zonder winstoogmerk": "IVZW",
    "Stichting": "SO",
    "Stichting van openbaar nut": "SON",
    "Eenmanszaak": "EZ",
    "Maatschap": "Maatschap",
    "Europese vennootschap": "SE",
    "Europese Coöperatieve Vennootschap": "SCE",
    "Europees economisch samenwerkingsverband": "EESV",
    "Economisch samenwerkingsverband": "ESV",
}


def _juridical_form_short(label_nl: str | None, code: str | None) -> str | None:
    """Map a long NL juridical-form label to its common Belgian abbreviation.

    Returns the abbreviation for the well-known forms, the trimmed long
    label otherwise, or the raw code as a last resort. Never returns an
    empty string — the caller treats falsy as "hide the chip".
    """
    if label_nl:
        # Exact match wins. Otherwise try the prefix in case the label
        # carries a parenthetical clarifier we haven't enumerated.
        if label_nl in _FORM_SHORT_FROM_LABEL:
            return _FORM_SHORT_FROM_LABEL[label_nl]
        for key, short in _FORM_SHORT_FROM_LABEL.items():
            if label_nl.startswith(key):
                return short
        # Long label with no short — let the UI render it but keep it tight.
        return label_nl
    return (code or None)


# ---------------------------------------------------------------------------
# GET /api/companies/{cbe}
# ---------------------------------------------------------------------------

@router.get("/{cbe}")
async def get_company_detail(cbe: str, response: Response):
    """Full company header detail.

    SQL extracted from app/pages/2_company.py load_company_detail() header query.
    """
    cbe = clean_cbe(cbe)
    # KBO header data updates daily at most. A 5 min browser cache plus a
    # long stale-while-revalidate window means back-button nav and tab
    # switches re-render instantly while the next idle fetch refreshes
    # the data in the background.
    response.headers["Cache-Control"] = "private, max-age=300, stale-while-revalidate=86400"

    try:
        # company_info.nace_code is refreshed from the 2008 KBO activities table.
        # Only fall back to a live activity row when company_info has no code.
        # Latest staatsblad liquidation_event powers the status assessment
        # below — sub_type=liquidation_open ⇒ in liquidation,
        # sub_type=liquidation_close ⇒ dissolved.
        header = fetch_one("""
            SELECT e.enterprise_number, e.status, e.start_date,
                   e.juridical_form AS "jf_code",
                   jfc.label_nl    AS "jf_label_nl",
                   jfc.label_fr    AS "jf_label_fr",
                   jfc.category    AS "jf_category",
                   COALESCE(ci.name, d.denomination, e.enterprise_number) AS "name",
                   COALESCE(ci.city, a.municipality_nl) AS "city",
                   a.zipcode, a.street_nl AS "street", a.house_number,
                   COALESCE(ci.nace_code, act.nace_code) AS "nace_code",
                   CASE
                       WHEN ci.nace_code IS NOT NULL THEN '2008'
                       ELSE act.nace_version
                   END AS "_nace_version",
                   liq.sub_type     AS "_liq_sub",
                   liq.pub_date     AS "_liq_date",
                   (SELECT value FROM contact WHERE entity_number = e.enterprise_number AND contact_type = 'WEB' LIMIT 1) AS "website"
            FROM enterprise e
            LEFT JOIN company_info ci ON ci.enterprise_number = e.enterprise_number
            LEFT JOIN denomination d ON d.entity_number = e.enterprise_number
                 AND d.type_of_denomination = '001' AND d.language IN ('2','1')
            LEFT JOIN address a ON a.entity_number = e.enterprise_number AND a.type_of_address = 'REGO'
            LEFT JOIN juridical_form_category jfc ON jfc.code = e.juridical_form
            LEFT JOIN LATERAL (
                SELECT act.nace_code, act.nace_version
                FROM activity act
                WHERE act.entity_number = e.enterprise_number
                  AND act.activity_group = '001'
                  AND act.classification = 'MAIN'
                ORDER BY
                    CASE act.nace_version
                        WHEN '2025' THEN 0
                        WHEN '2008' THEN 1
                        WHEN '2003' THEN 2
                        ELSE 3
                    END,
                    act.nace_code
                LIMIT 1
            ) act ON ci.nace_code IS NULL
            LEFT JOIN LATERAL (
                -- Restrict to true liquidation milestones. The
                -- liquidation_event family also produces
                -- 'bankruptcy' / 'judicial_reorganisation' sub_types
                -- (handled separately by the insolvency badge); without
                -- this filter their pub_date would leak a misleading
                -- "Since <date>" tooltip onto an otherwise-Active chip.
                SELECT sb.sub_type, sb.pub_date
                FROM staatsblad_event sb
                WHERE sb.enterprise_number = e.enterprise_number
                  AND sb.event_type = 'liquidation_event'
                  AND sb.sub_type IN ('liquidation_open', 'liquidation_close')
                ORDER BY sb.pub_date DESC NULLS LAST
                LIMIT 1
            ) liq ON TRUE
            WHERE e.enterprise_number = %s LIMIT 1
        """, (cbe,))

        if not header:
            raise HTTPException(status_code=404, detail=f"Company {cbe} not found")

        preferred_version = header.pop("_nace_version", None)
        header["nace_label"] = _resolve_nace_label(
            header.get("nace_code"),
            preferred_version,
        )

        # Backwards-compatible jf_label: prefer the human-readable NL label
        # over the raw KBO code, falling back to FR then code so the
        # profile header never shows a bare numeric like "017".
        jf_code = header.get("jf_code")
        jf_label_nl = header.get("jf_label_nl")
        jf_label_fr = header.get("jf_label_fr")
        header["jf_label"] = jf_label_nl or jf_label_fr or jf_code

        # Short form (e.g. "BV", "NV", "CommV"). Derived from the NL label
        # so the profile chip stays compact next to the company name.
        # Falls back to the code when no readable label is available.
        header["jf_short"] = _juridical_form_short(jf_label_nl, jf_code)

        # Status assessment — surface bankrupt/dissolved at the profile
        # header. KBO's `enterprise.status` is "AC" for ~all rows in our
        # current ingest, so the strongest signals come from the
        # Staatsblad liquidation_event feed. Open Regsol insolvency is
        # already shown by the existing CompanyInsolvencyBadge on the
        # summary tab, so we don't re-surface it here.
        liq_sub = header.pop("_liq_sub", None)
        liq_date = header.pop("_liq_date", None)
        kbo_status = header.get("status")
        if liq_sub == "liquidation_close":
            assessment_code = "dissolved"
        elif liq_sub == "liquidation_open":
            assessment_code = "in_liquidation"
        elif kbo_status and kbo_status != "AC":
            assessment_code = "stopped"
        else:
            assessment_code = "active"
        header["status_assessment"] = {
            "code": assessment_code,
            "since": liq_date.isoformat() if liq_date else None,
        }

        return _serialize_row(header)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Company detail query failed")
        raise HTTPException(status_code=500, detail="Internal server error")
