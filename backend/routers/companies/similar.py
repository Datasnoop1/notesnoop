"""Companies similar router — sector benchmarks, similar companies, AI re-ranking, embeddings."""

import json
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Query

from db import fetch_all, fetch_one, execute
from auth import get_current_user
from ai_client import ai_complete
from utils import clean_cbe
from ._helpers import _serialize_row

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Sector Benchmarking ──────────────────────────────────────────

@router.get("/{cbe}/sector-benchmark")
async def sector_benchmark(cbe: str):
    """Return percentile rankings for a company within its NACE sector (single batched query)."""
    cbe = clean_cbe(cbe)

    try:
        info = fetch_one(
            "SELECT nace_code FROM company_info WHERE enterprise_number = %s", (cbe,),
        )
        if not info or not info.get("nace_code"):
            return {"error": "no_nace", "benchmarks": []}

        nace = info["nace_code"]

        # Single query: get company values + all percentiles in one shot
        row = fetch_one("""
            WITH company AS (
                SELECT revenue, ebitda, net_profit, equity, total_assets, fte_total, fiscal_year,
                       CASE WHEN revenue > 0 THEN ebitda / revenue * 100 END AS ebitda_margin,
                       CASE WHEN total_assets > 0 THEN equity / total_assets * 100 END AS equity_ratio
                FROM financial_latest WHERE enterprise_number = %s
            ),
            peers AS (
                SELECT fl.*,
                       CASE WHEN fl.revenue > 0 THEN fl.ebitda / fl.revenue * 100 END AS ebitda_margin,
                       CASE WHEN fl.total_assets > 0 THEN fl.equity / fl.total_assets * 100 END AS equity_ratio
                FROM financial_latest fl
                JOIN company_info ci ON ci.enterprise_number = fl.enterprise_number
                WHERE ci.nace_code = %s
            )
            SELECT
                (SELECT COUNT(*) FROM peers WHERE revenue IS NOT NULL) AS peer_count,
                c.fiscal_year, c.revenue, c.ebitda, c.net_profit, c.equity, c.total_assets, c.fte_total,
                c.ebitda_margin, c.equity_ratio,
                -- Revenue
                (SELECT COUNT(*) FROM peers WHERE revenue < c.revenue AND revenue IS NOT NULL) AS rev_below,
                (SELECT COUNT(*) FROM peers WHERE revenue IS NOT NULL) AS rev_total,
                (SELECT PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY revenue) FROM peers WHERE revenue IS NOT NULL) AS rev_p25,
                (SELECT PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY revenue) FROM peers WHERE revenue IS NOT NULL) AS rev_med,
                (SELECT PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY revenue) FROM peers WHERE revenue IS NOT NULL) AS rev_p75,
                -- EBITDA
                (SELECT COUNT(*) FROM peers WHERE ebitda < c.ebitda AND ebitda IS NOT NULL) AS ebitda_below,
                (SELECT COUNT(*) FROM peers WHERE ebitda IS NOT NULL) AS ebitda_total,
                (SELECT PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY ebitda) FROM peers WHERE ebitda IS NOT NULL) AS ebitda_p25,
                (SELECT PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY ebitda) FROM peers WHERE ebitda IS NOT NULL) AS ebitda_med,
                (SELECT PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY ebitda) FROM peers WHERE ebitda IS NOT NULL) AS ebitda_p75,
                -- Net Profit
                (SELECT COUNT(*) FROM peers WHERE net_profit < c.net_profit AND net_profit IS NOT NULL) AS np_below,
                (SELECT COUNT(*) FROM peers WHERE net_profit IS NOT NULL) AS np_total,
                (SELECT PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY net_profit) FROM peers WHERE net_profit IS NOT NULL) AS np_med,
                -- FTE
                (SELECT COUNT(*) FROM peers WHERE fte_total < c.fte_total AND fte_total IS NOT NULL) AS fte_below,
                (SELECT COUNT(*) FROM peers WHERE fte_total IS NOT NULL) AS fte_total_cnt,
                (SELECT PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY fte_total) FROM peers WHERE fte_total IS NOT NULL) AS fte_med,
                -- Total Assets
                (SELECT COUNT(*) FROM peers WHERE total_assets < c.total_assets AND total_assets IS NOT NULL) AS ta_below,
                (SELECT COUNT(*) FROM peers WHERE total_assets IS NOT NULL) AS ta_total,
                (SELECT PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY total_assets) FROM peers WHERE total_assets IS NOT NULL) AS ta_med,
                -- EBITDA Margin
                (SELECT COUNT(*) FROM peers WHERE ebitda_margin < c.ebitda_margin AND ebitda_margin IS NOT NULL) AS em_below,
                (SELECT COUNT(*) FROM peers WHERE ebitda_margin IS NOT NULL) AS em_total,
                (SELECT PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY ebitda_margin) FROM peers WHERE ebitda_margin IS NOT NULL) AS em_med,
                -- Equity Ratio
                (SELECT COUNT(*) FROM peers WHERE equity_ratio < c.equity_ratio AND equity_ratio IS NOT NULL) AS er_below,
                (SELECT COUNT(*) FROM peers WHERE equity_ratio IS NOT NULL) AS er_total,
                (SELECT PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY equity_ratio) FROM peers WHERE equity_ratio IS NOT NULL) AS er_med
            FROM company c
        """, (cbe, nace))

        if not row or not row.get("fiscal_year"):
            return {"error": "no_financials", "benchmarks": []}

        nace_label = fetch_one("SELECT description FROM nace_lookup WHERE nace_code = %s", (nace,))

        def pct(below, total):
            return round((below / total) * 100, 1) if total and total > 0 else None

        def fv(v):
            return float(v) if v is not None else None

        benchmarks = []
        defs = [
            ("Revenue", "eur", "revenue", "rev_below", "rev_total", "rev_p25", "rev_med", "rev_p75"),
            ("EBITDA", "eur", "ebitda", "ebitda_below", "ebitda_total", "ebitda_p25", "ebitda_med", "ebitda_p75"),
            ("Net Profit", "eur", "net_profit", "np_below", "np_total", None, "np_med", None),
            ("FTE", "num", "fte_total", "fte_below", "fte_total_cnt", None, "fte_med", None),
            ("Total Assets", "eur", "total_assets", "ta_below", "ta_total", None, "ta_med", None),
            ("EBITDA Margin", "pct", "ebitda_margin", "em_below", "em_total", None, "em_med", None),
            ("Equity Ratio", "pct", "equity_ratio", "er_below", "er_total", None, "er_med", None),
        ]
        for label, fmt, val_key, below_key, total_key, p25_key, med_key, p75_key in defs:
            val = row.get(val_key)
            total = row.get(total_key)
            if val is None or not total:
                continue
            benchmarks.append({
                "metric": label, "format": fmt,
                "value": fv(val),
                "percentile": pct(row.get(below_key, 0), total),
                "p25": fv(row.get(p25_key)) if p25_key else None,
                "median": fv(row.get(med_key)) if med_key else None,
                "p75": fv(row.get(p75_key)) if p75_key else None,
                "peer_count": total,
            })

        return {
            "nace_code": nace,
            "nace_label": nace_label["description"] if nace_label else nace,
            "fiscal_year": row["fiscal_year"],
            "peer_count": row.get("peer_count", 0),
            "benchmarks": benchmarks,
        }
    except Exception as e:
        logger.exception("Sector benchmark failed for %s", cbe)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/companies/{cbe}/similar
# ---------------------------------------------------------------------------

@router.get("/{cbe}/similar")
async def get_similar_companies(cbe: str):
    """Find up to 10 companies in the same NACE sector with closest revenue."""
    cbe = clean_cbe(cbe)

    try:
        # Get the target company's NACE code and latest revenue
        target = fetch_one("""
            SELECT ci.nace_code, fl.revenue
            FROM company_info ci
            LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
            WHERE ci.enterprise_number = %s
        """, (cbe,))

        if not target:
            raise HTTPException(status_code=404, detail=f"Company {cbe} not found")

        nace = target.get("nace_code")
        revenue = target.get("revenue")

        if not nace:
            return []

        if revenue and revenue > 0:
            # Find companies in same sector with revenue within 0.1x to 10x
            rev_min = float(revenue) * 0.1
            rev_max = float(revenue) * 10.0
            rows = fetch_all("""
                SELECT ci.enterprise_number, ci.name, ci.city,
                       fl.revenue, fl.ebitda, fl.fte_total, fl.fiscal_year,
                       fl.ebit, fl.net_profit, fl.equity,
                       fl.total_assets, fl.personnel_costs
                FROM company_info ci
                JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
                WHERE ci.nace_code = %s
                  AND ci.enterprise_number != %s
                  AND fl.revenue IS NOT NULL
                  AND fl.revenue BETWEEN %s AND %s
                ORDER BY ABS(fl.revenue - %s)
                LIMIT 100
            """, (nace, cbe, rev_min, rev_max, float(revenue)))
        else:
            # No revenue data — just return companies in the same sector
            rows = fetch_all("""
                SELECT ci.enterprise_number, ci.name, ci.city,
                       fl.revenue, fl.ebitda, fl.fte_total, fl.fiscal_year,
                       fl.ebit, fl.net_profit, fl.equity,
                       fl.total_assets, fl.personnel_costs
                FROM company_info ci
                LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
                WHERE ci.nace_code = %s
                  AND ci.enterprise_number != %s
                ORDER BY fl.revenue DESC NULLS LAST
                LIMIT 100
            """, (nace, cbe))

        return [_serialize_row(r) for r in rows]
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Similar companies failed for %s", cbe)
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/companies/{cbe}/similar/ai — AI-enhanced similarity
# ---------------------------------------------------------------------------

@router.get("/{cbe}/similar/ai")
async def get_similar_companies_ai(cbe: str, user=Depends(get_current_user)):
    """Re-rank similar companies using LLM for true business similarity."""
    cbe = clean_cbe(cbe)

    # Ensure cache table exists
    try:
        execute("""
            CREATE TABLE IF NOT EXISTS ai_similar_cache (
                enterprise_number VARCHAR(10) PRIMARY KEY,
                ranked_cbes TEXT,
                reasons TEXT,
                generated_at TIMESTAMP DEFAULT NOW()
            )
        """)
    except Exception:
        pass

    # Check cache (30-day TTL)
    cached = fetch_one(
        "SELECT ranked_cbes, reasons FROM ai_similar_cache "
        "WHERE enterprise_number = %s AND generated_at > NOW() - INTERVAL '30 days'",
        (cbe,),
    )
    if cached and cached.get("ranked_cbes"):
        try:
            ranked_cbes = json.loads(cached["ranked_cbes"])
            reasons = json.loads(cached["reasons"])
            # Fetch full company data for ranked CBEs
            if ranked_cbes:
                placeholders = ",".join(["%s"] * len(ranked_cbes))
                rows = fetch_all(f"""
                    SELECT ci.enterprise_number, ci.name, ci.city,
                           fl.revenue, fl.ebitda, fl.fte_total, fl.fiscal_year,
                           fl.ebit, fl.net_profit, fl.equity, fl.total_assets, fl.personnel_costs
                    FROM company_info ci
                    LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
                    WHERE ci.enterprise_number IN ({placeholders})
                """, tuple(ranked_cbes))
                row_map = {r["enterprise_number"]: _serialize_row(r) for r in rows}
                result = []
                for i, c in enumerate(ranked_cbes):
                    if c in row_map:
                        entry = row_map[c]
                        entry["ai_reason"] = reasons[i] if i < len(reasons) else ""
                        result.append(entry)
                return result
        except Exception:
            pass

    # Get target company info
    target = fetch_one("""
        SELECT ci.name, ci.nace_code, ci.city, fl.revenue, fl.ebitda, fl.fte_total
        FROM company_info ci
        LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
        WHERE ci.enterprise_number = %s
    """, (cbe,))
    if not target:
        raise HTTPException(status_code=404, detail="Company not found")

    # Fetch all NACE peers with financials — no revenue filter, AI ranks for relevance
    nace = target.get("nace_code") or ""
    if not nace:
        return []

    candidates = fetch_all("""
        SELECT ci.enterprise_number, ci.name, ci.city,
               fl.revenue, fl.ebitda, fl.fte_total, fl.fiscal_year,
               COALESCE(nl.description, ci.nace_code) AS nace_desc
        FROM company_info ci
        JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
        LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
        WHERE ci.nace_code = %s AND ci.enterprise_number != %s
        ORDER BY fl.revenue DESC NULLS LAST
        LIMIT 50
    """, (nace, cbe))

    # If <10 in exact NACE, broaden to 2-digit prefix
    if len(candidates) < 10:
        existing = {c["enterprise_number"] for c in candidates}
        broader = fetch_all("""
            SELECT ci.enterprise_number, ci.name, ci.city,
                   fl.revenue, fl.ebitda, fl.fte_total, fl.fiscal_year,
                   COALESCE(nl.description, ci.nace_code) AS nace_desc
            FROM company_info ci
            JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
            LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
            WHERE ci.nace_code LIKE %s AND ci.enterprise_number != %s
            ORDER BY fl.revenue DESC NULLS LAST
            LIMIT 50
        """, (f"{nace[:2]}%", cbe))
        for b in broader:
            if b["enterprise_number"] not in existing and len(candidates) < 50:
                candidates.append(b)
                existing.add(b["enterprise_number"])

    if not candidates:
        return []

    # Build LLM prompt for re-ranking
    target_desc = f"{target['name']} ({target.get('city', '?')}) — Revenue: {target.get('revenue', '?')}, EBITDA: {target.get('ebitda', '?')}, FTE: {target.get('fte_total', '?')}"
    cand_lines = []
    for i, c in enumerate(candidates[:20]):
        cand_lines.append(
            f"{i+1}. {c['name']} ({c.get('city','?')}) — Rev: {c.get('revenue','?')}, EBITDA: {c.get('ebitda','?')}, FTE: {c.get('fte_total','?')}, Sector: {c.get('nace_desc','?')}"
        )

    prompt = (
        f"You are a Belgian company analyst. Rank the candidates by how similar their ACTIVITY is to the target company.\n\n"
        f"Ranking criteria (in order of importance):\n"
        f"1. ACTIVITY MATCH: How identical is the core business activity? Same products/services/trade = highest rank.\n"
        f"2. REVENUE SIZE: Among activity matches, prefer companies with similar revenue or EBITDA.\n"
        f"Do NOT eliminate companies for being too large or too small — size is secondary to activity match.\n\n"
        f"TARGET: {target_desc}\n\nCANDIDATES:\n" + "\n".join(cand_lines) +
        f"\n\nReturn ONLY a JSON array of 10 objects with 'rank' (original number from list) and 'reason' (one sentence explaining the activity similarity). "
        f"Example: [{{'rank': 3, 'reason': 'Same core activity: wholesale of industrial cleaning products'}}]"
    )

    try:
        raw = await ai_complete(prompt, max_tokens=500, model="google/gemini-2.5-flash")
        # Parse JSON from response
        json_match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not json_match:
            return [_serialize_row(r) for r in candidates[:10]]
        rankings = json.loads(json_match.group())
    except Exception as e:
        logger.error("AI similar ranking failed for %s: %s", cbe, e)
        return [_serialize_row(r) for r in candidates[:10]]

    # Build result in ranked order
    result = []
    ranked_cbes = []
    reasons_list = []
    for entry in rankings[:10]:
        idx = entry.get("rank", 0) - 1
        if 0 <= idx < len(candidates):
            row = _serialize_row(candidates[idx])
            row["ai_reason"] = entry.get("reason", "")
            result.append(row)
            ranked_cbes.append(candidates[idx]["enterprise_number"])
            reasons_list.append(entry.get("reason", ""))

    # Cache
    try:
        execute(
            "INSERT INTO ai_similar_cache (enterprise_number, ranked_cbes, reasons) VALUES (%s, %s, %s) "
            "ON CONFLICT (enterprise_number) DO UPDATE SET ranked_cbes = EXCLUDED.ranked_cbes, reasons = EXCLUDED.reasons, generated_at = NOW()",
            (cbe, json.dumps(ranked_cbes), json.dumps(reasons_list)),
        )
    except Exception as e:
        logger.error("Failed to cache AI similar for %s: %s", cbe, e)

    return result


# ---------------------------------------------------------------------------
# GET /api/companies/{cbe}/semantic-similar
# ---------------------------------------------------------------------------

@router.get("/{cbe}/semantic-similar")
async def semantic_similar_companies(cbe: str, limit: int = Query(20, ge=1, le=50)):
    """Find companies with similar business descriptions using vector embeddings."""
    from embeddings import find_similar_by_embedding, ensure_embedding_table
    ensure_embedding_table()
    cbe = clean_cbe(cbe)

    results = await find_similar_by_embedding(cbe, limit=limit)
    if not results:
        return []

    # Enrich with financial data
    cbes = [r["enterprise_number"] for r in results]
    if cbes:
        placeholders = ",".join(["%s"] * len(cbes))
        financials = fetch_all(f"""
            SELECT enterprise_number, revenue, ebitda, fte_total, fiscal_year
            FROM financial_latest
            WHERE enterprise_number IN ({placeholders})
        """, tuple(cbes))
        fin_map = {r["enterprise_number"]: r for r in financials}

        for r in results:
            fin = fin_map.get(r["enterprise_number"], {})
            r["revenue"] = float(fin["revenue"]) if fin.get("revenue") else None
            r["ebitda"] = float(fin["ebitda"]) if fin.get("ebitda") else None
            r["fte_total"] = float(fin["fte_total"]) if fin.get("fte_total") else None
            r["fiscal_year"] = fin.get("fiscal_year")
            r["similarity"] = round(float(r.get("similarity", 0)), 4)

    return results
