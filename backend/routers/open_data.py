"""Open-data surfacing — TED procurement awards + Regsol insolvency +
structured Staatsblad events, exposed per-company for the profile page
and aggregated for the screener.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from db import fetch_all, fetch_one
from serializers import serialize_row as _serialize

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/open-data", tags=["open-data"])


@router.get("/companies/{cbe}/procurement")
async def company_procurement(cbe: str, limit: int = Query(20, ge=1, le=200)):
    """TED awards won by this company. Ordered most recent first."""
    if not cbe.isdigit() or len(cbe) != 10:
        raise HTTPException(400, "CBE must be 10 digits")
    try:
        rows = fetch_all(
            """SELECT ted_notice_id, buyer_name, award_date, contract_value,
                      currency, cpv_code, title
               FROM procurement_award
               WHERE enterprise_number = %s
               ORDER BY award_date DESC NULLS LAST
               LIMIT %s""",
            (cbe, limit),
        )
        total = fetch_one(
            """SELECT SUM(contract_value) AS total_value,
                      COUNT(*) AS n
               FROM procurement_award
               WHERE enterprise_number = %s
                 AND award_date > CURRENT_DATE - INTERVAL '3 years'""",
            (cbe,),
        )
        return {
            "awards": [_serialize(r) for r in rows],
            "total_3y_eur": float(total["total_value"] or 0) if total else 0,
            "count_3y": (total["n"] if total else 0) or 0,
        }
    except Exception as e:
        logger.exception("company_procurement failed")
        raise HTTPException(500, "Internal server error")


@router.get("/companies/{cbe}/insolvency")
async def company_insolvency(cbe: str):
    """Regsol insolvency case(s) for this company, if any."""
    if not cbe.isdigit() or len(cbe) != 10:
        raise HTTPException(400, "CBE must be 10 digits")
    try:
        rows = fetch_all(
            """SELECT docket_number, case_type, court, opened_at,
                      closed_at, status, curator_name, last_scraped_at
               FROM insolvency_case
               WHERE enterprise_number = %s
               ORDER BY opened_at DESC NULLS LAST""",
            (cbe,),
        )
        return {"cases": [_serialize(r) for r in rows]}
    except Exception as e:
        logger.exception("company_insolvency failed")
        raise HTTPException(500, "Internal server error")


@router.get("/companies/{cbe}/radar")
async def company_radar(cbe: str):
    """Radar-chart scores for a company vs NACE-2 sector, 0..100 each axis:
    Growth, Profitability, Efficiency, Leverage (inverted — low debt = high
    score), Liquidity, Scale. Pulled from sector_percentiles + financial_latest.
    """
    if not cbe.isdigit() or len(cbe) != 10:
        raise HTTPException(400, "CBE must be 10 digits")
    try:
        row = fetch_one(
            """
            SELECT fl.revenue, fl.ebitda, fl.ebit, fl.net_profit, fl.fte_total,
                   fl.total_assets, fl.equity, fl.cash,
                   fl.lt_financial_debt, fl.st_financial_debt,
                   sp.rev_rank, sp.ebitda_rank, sp.margin_rank,
                   sp.fte_rank, sp.peer_count
            FROM financial_latest fl
            LEFT JOIN sector_percentiles sp
              ON sp.enterprise_number = fl.enterprise_number
            WHERE fl.enterprise_number = %s
            """,
            (cbe,),
        )
        if not row:
            return {"scores": None, "peer_count": 0}

        # percent_rank is 0..1 (0 worst, 1 best). Return 0..100.
        def pct(v):
            return round(float(v) * 100, 1) if v is not None else None

        # Derived leverage score: inverted netDebt/EBITDA.
        # score = 100 * clamp(1 - min(ndE, 5)/5, 0..1)
        # financial_latest has no current_investments column — use cash only.
        nd = (float(row.get("lt_financial_debt") or 0)
              + float(row.get("st_financial_debt") or 0)
              - float(row.get("cash") or 0))
        ebitda = float(row.get("ebitda") or 0)
        if ebitda > 0:
            lev_ratio = max(0, nd / ebitda)
            leverage_score = round(100 * max(0, 1 - min(lev_ratio, 5) / 5), 1)
        else:
            leverage_score = None

        # Liquidity proxy: cash / ST debt (capped at 2×).
        stdebt = float(row.get("st_financial_debt") or 0)
        liq_cash = float(row.get("cash") or 0)
        if stdebt > 0:
            ratio = liq_cash / stdebt
            liquidity_score = round(100 * min(ratio, 2) / 2, 1)
        elif liq_cash > 0:
            liquidity_score = 100.0
        else:
            liquidity_score = None

        return {
            "scores": {
                "Scale":         pct(row.get("rev_rank")),
                "Profitability": pct(row.get("margin_rank")),
                "Efficiency":    pct(row.get("fte_rank")),
                "Leverage":      leverage_score,
                "Liquidity":     liquidity_score,
                "Growth":        pct(row.get("ebitda_rank")),
            },
            "peer_count": row.get("peer_count") or 0,
        }
    except Exception as e:
        logger.exception("company_radar failed")
        raise HTTPException(500, "Internal server error")


@router.get("/companies/{cbe}/events")
async def company_events(cbe: str, limit: int = Query(50, ge=1, le=500)):
    """Structured governance events — from staatsblad_event."""
    if not cbe.isdigit() or len(cbe) != 10:
        raise HTTPException(400, "CBE must be 10 digits")
    try:
        rows = fetch_all(
            """SELECT reference, pub_date, event_type, subject_name, raw_title
               FROM staatsblad_event
               WHERE enterprise_number = %s
               ORDER BY pub_date DESC NULLS LAST
               LIMIT %s""",
            (cbe, limit),
        )
        return {"events": [_serialize(r) for r in rows]}
    except Exception as e:
        logger.exception("company_events failed")
        raise HTTPException(500, "Internal server error")
