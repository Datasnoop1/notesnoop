"""Company corporate-events timeline.

Aggregates founding date, NBB filings, Staatsblad publications, and
administrator mandate changes into a single chronological event list
keyed on a CBE. Frontend renders it as a vertical timeline on the
company profile.

Cheap to compute (small per-company cardinality) but kept off the main
detail endpoint so the load time of the profile page stays predictable.
"""

import logging
from typing import List

from fastapi import APIRouter, HTTPException

from db import fetch_all, fetch_one

logger = logging.getLogger(__name__)
router = APIRouter()


def _clean_cbe(cbe: str) -> str:
    return "".join(c for c in (cbe or "") if c.isdigit()).zfill(10)[:10]


def _short_pub_label(pub_type: str | None) -> str:
    if not pub_type:
        return "Publicatie"
    s = pub_type.strip().split("-")[0].strip().title()
    return s[:80]


@router.get("/{cbe}/timeline")
async def company_timeline(cbe: str, limit: int = 200):
    """Return a chronological list of corporate events for a CBE.

    Each event: ``{date, kind, label, ref}``.
    ``kind`` ∈ {founding, filing, publication, mandate_start, mandate_end}.
    Capped at ``limit`` to keep the response light. Newest first.
    """
    cbe = _clean_cbe(cbe)
    if not cbe:
        raise HTTPException(status_code=400, detail="Invalid CBE")

    events: list[dict] = []

    try:
        # Founding date — single row from enterprise.
        ent = fetch_one(
            "SELECT start_date FROM enterprise WHERE enterprise_number = %s",
            (cbe,),
        )
        if ent and ent.get("start_date"):
            events.append({
                "date": str(ent["start_date"]),
                "kind": "founding",
                "label": "Company founded",
                "ref": None,
            })

        # NBB annual filings via deposit_date in financial_summary.
        fil_rows = fetch_all(
            """
            SELECT DISTINCT fiscal_year, deposit_date, filing_model
            FROM financial_summary
            WHERE enterprise_number = %s
              AND deposit_date IS NOT NULL
            ORDER BY deposit_date DESC
            LIMIT 50
            """,
            (cbe,),
        )
        for r in fil_rows or []:
            fm = r.get("filing_model")
            label = f"NBB filing FY{r['fiscal_year']}"
            if fm:
                label = f"{label} ({fm})"
            events.append({
                "date": str(r["deposit_date"]),
                "kind": "filing",
                "label": label,
                "ref": None,
            })

        # Staatsblad publications.
        pub_rows = fetch_all(
            """
            SELECT pub_date, pub_type, reference, pdf_url
            FROM staatsblad_publication
            WHERE enterprise_number = %s
            ORDER BY pub_date DESC
            LIMIT 100
            """,
            (cbe,),
        )
        for r in pub_rows or []:
            events.append({
                "date": str(r["pub_date"]),
                "kind": "publication",
                "label": _short_pub_label(r.get("pub_type")),
                "ref": r.get("pdf_url"),
            })

        # Administrator mandate starts and ends.
        adm_rows = fetch_all(
            """
            SELECT DISTINCT name, mandate_start, mandate_end, role
            FROM administrator_fact
            WHERE enterprise_number = %s
              AND name IS NOT NULL
            ORDER BY mandate_start DESC NULLS LAST
            LIMIT 100
            """,
            (cbe,),
        )
        for r in adm_rows or []:
            ms = r.get("mandate_start")
            me = r.get("mandate_end")
            role = r.get("role") or "Administrator"
            name = r.get("name")
            if ms:
                try:
                    events.append({
                        "date": str(ms)[:10],
                        "kind": "mandate_start",
                        "label": f"{name} appointed ({role})",
                        "ref": None,
                    })
                except Exception:
                    pass
            if me:
                try:
                    events.append({
                        "date": str(me)[:10],
                        "kind": "mandate_end",
                        "label": f"{name} departed ({role})",
                        "ref": None,
                    })
                except Exception:
                    pass

        # Sort newest first; clamp.
        events = [e for e in events if e["date"] and e["date"][:1].isdigit()]
        events.sort(key=lambda e: e["date"], reverse=True)
        return {"events": events[:limit]}
    except Exception:
        logger.exception("Timeline build failed for %s", cbe)
        raise HTTPException(status_code=500, detail="Timeline failed")
