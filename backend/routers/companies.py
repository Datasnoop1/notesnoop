"""Companies router — search, detail, financials, structure, and network graph."""

import logging
from collections import deque
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from db import fetch_all, fetch_one, get_connection

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/companies", tags=["companies"])

ROLE_LABELS = {
    "fct:m10": "Director", "fct:m11": "Managing director",
    "fct:m12": "Chairman", "fct:m13": "Administrator",
    "fct:m14": "Secretary", "fct:m15": "Treasurer",
    "fct:m20": "Statutory auditor", "fct:m30": "Liquidator",
    "fct:m40": "Daily management",
}

MAX_NETWORK_NODES = 200


def _clean_cbe(identifier) -> Optional[str]:
    """Strip dots/spaces from identifier, return 10-digit CBE or None."""
    if not identifier:
        return None
    c = str(identifier).replace(".", "").replace(" ", "").strip()
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


# ---------------------------------------------------------------------------
# GET /api/companies/search?q=...
# ---------------------------------------------------------------------------

@router.get("/search")
async def search_companies(q: str = Query(..., min_length=1)):
    """Search companies by name or CBE number.

    SQL extracted from app/pages/2_company.py search_companies().
    """
    query = q.strip()
    cbe_clean = query.replace(".", "").replace(" ", "")

    try:
        if cbe_clean.isdigit():
            # CBE prefix search on enterprise (fast, indexed)
            rows = fetch_all("""
                SELECT e.enterprise_number, COALESCE(ci.name, e.enterprise_number) AS "name",
                       e.status, e.juridical_form AS "jf_label", ci.city,
                       COALESCE(nl.description, ci.nace_code) AS "sector", e.start_date,
                       fl.revenue, fl.ebitda,
                       CASE WHEN fl.revenue > 0 THEN ROUND((fl.ebitda / fl.revenue * 100)::numeric, 1) END AS "ebitda_margin_pct",
                       fl.fte_total, fl.fiscal_year
                FROM enterprise e
                LEFT JOIN company_info ci ON ci.enterprise_number = e.enterprise_number
                LEFT JOIN financial_latest fl ON fl.enterprise_number = e.enterprise_number
                LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
                WHERE e.enterprise_number LIKE %s
                LIMIT 20
            """, (f"{cbe_clean}%",))
        else:
            # First: search company_info (170K, fast, has financials)
            rows = fetch_all("""
                SELECT ci.enterprise_number, ci.name,
                       e.status, e.juridical_form AS "jf_label", ci.city,
                       COALESCE(nl.description, ci.nace_code) AS "sector", e.start_date,
                       fl.revenue, fl.ebitda,
                       CASE WHEN fl.revenue > 0 THEN ROUND((fl.ebitda / fl.revenue * 100)::numeric, 1) END AS "ebitda_margin_pct",
                       fl.fte_total, fl.fiscal_year
                FROM company_info ci
                JOIN enterprise e ON e.enterprise_number = ci.enterprise_number
                LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
                LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
                WHERE ci.name ILIKE %s
                ORDER BY ci.name
                LIMIT 20
            """, (f"%{query}%",))

            # If not enough results, also search denomination table
            if len(rows) < 20:
                remaining = 20 - len(rows)
                existing_cbes = {r["enterprise_number"] for r in rows}
                extra = fetch_all("""
                    SELECT e.enterprise_number, d.denomination AS "name",
                           e.status, e.juridical_form AS "jf_label",
                           a.municipality_nl AS "city",
                           NULL AS "sector", e.start_date,
                           NULL::real AS "revenue", NULL::real AS "ebitda",
                           NULL::numeric AS "ebitda_margin_pct",
                           NULL::real AS "fte_total", NULL::integer AS "fiscal_year"
                    FROM denomination d
                    JOIN enterprise e ON e.enterprise_number = d.entity_number
                    LEFT JOIN address a ON a.entity_number = e.enterprise_number AND a.type_of_address = 'REGO'
                    WHERE d.denomination ILIKE %s
                      AND d.type_of_denomination = '001'
                      AND d.language IN ('2','1')
                    ORDER BY d.denomination
                    LIMIT %s
                """, (f"%{query}%", remaining + 10))
                for r in extra:
                    if r["enterprise_number"] not in existing_cbes:
                        rows.append(r)
                        existing_cbes.add(r["enterprise_number"])
                        if len(rows) >= 20:
                            break

            # If no results, try alternative/fuzzy matches
            if not rows:
                words = query.split()
                if len(words) > 1:
                    # Try matching any word
                    conditions = " OR ".join(["ci.name ILIKE %s"] * len(words))
                    params = tuple(f"%{w}%" for w in words)
                    rows = fetch_all(f"""
                        SELECT ci.enterprise_number, ci.name,
                               e.status, e.juridical_form AS "jf_label", ci.city,
                               COALESCE(nl.description, ci.nace_code) AS "sector", e.start_date,
                               fl.revenue, fl.ebitda,
                               CASE WHEN fl.revenue > 0 THEN ROUND((fl.ebitda / fl.revenue * 100)::numeric, 1) END AS "ebitda_margin_pct",
                               fl.fte_total, fl.fiscal_year
                        FROM company_info ci
                        JOIN enterprise e ON e.enterprise_number = ci.enterprise_number
                        LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
                        LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
                        WHERE {conditions}
                        ORDER BY ci.name LIMIT 20
                    """, params)
                elif len(query) >= 3:
                    # Try prefix match
                    rows = fetch_all("""
                        SELECT ci.enterprise_number, ci.name,
                               e.status, e.juridical_form AS "jf_label", ci.city,
                               COALESCE(nl.description, ci.nace_code) AS "sector", e.start_date,
                               fl.revenue, fl.ebitda,
                               CASE WHEN fl.revenue > 0 THEN ROUND((fl.ebitda / fl.revenue * 100)::numeric, 1) END AS "ebitda_margin_pct",
                               fl.fte_total, fl.fiscal_year
                        FROM company_info ci
                        JOIN enterprise e ON e.enterprise_number = ci.enterprise_number
                        LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
                        LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
                        WHERE ci.name ILIKE %s
                        ORDER BY ci.name LIMIT 20
                    """, (f"{query}%",))

        return [_serialize_row(r) for r in rows]
    except Exception as e:
        logger.exception("Company search failed")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# GET /api/companies/{cbe}
# ---------------------------------------------------------------------------

@router.get("/{cbe}")
async def get_company_detail(cbe: str):
    """Full company header detail.

    SQL extracted from app/pages/2_company.py load_company_detail() header query.
    """
    cbe = cbe.strip().replace(".", "")

    try:
        # Fast path: try company_info first (170K rows, indexed)
        header = fetch_one("""
            SELECT e.enterprise_number, e.status, e.start_date,
                   e.juridical_form AS "jf_label",
                   COALESCE(ci.name, d.denomination, e.enterprise_number) AS "name",
                   COALESCE(ci.city, a.municipality_nl) AS "city",
                   a.zipcode, a.street_nl AS "street", a.house_number,
                   ci.nace_code,
                   COALESCE(nl.description, ci.nace_code) AS "nace_label"
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
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# GET /api/companies/{cbe}/financials
# ---------------------------------------------------------------------------

@router.get("/{cbe}/financials")
async def get_company_financials(cbe: str):
    """Financial history from financial_summary.

    SQL extracted from app/pages/2_company.py load_company_detail() hist query.
    """
    cbe = cbe.strip().replace(".", "")

    try:
        hist = fetch_all("""
            SELECT fiscal_year, deposit_key, filing_model,
                   revenue, ebit, da, ebitda, net_profit,
                   equity, lt_financial_debt, st_financial_debt, cash, total_assets,
                   fixed_assets, inventories, trade_receivables, trade_payables,
                   financial_charges, fte_total, personnel_costs,
                   CASE WHEN revenue > 0
                        THEN ROUND((ebitda / revenue * 100)::numeric, 1)
                   END AS "ebitda_margin_pct"
            FROM financial_summary
            WHERE enterprise_number = %s
            ORDER BY fiscal_year
        """, (cbe,))

        if not hist:
            return {"summary": [], "pnl": {}}

        # P&L rubric data
        pnl_codes = [
            "70", "74", "70/76A", "60", "61", "62", "630", "631/4", "635/8",
            "640/8", "60/66A", "9901", "75", "65", "9902", "76", "66",
            "9903", "67/77", "9904",
        ]
        bs_codes = [
            "20/28", "21", "22", "28", "29/58", "3", "41", "54/58",
            "20/58", "10/15", "16", "17", "43", "44", "10/49",
        ]
        all_codes = list(dict.fromkeys(pnl_codes + bs_codes))
        placeholders = ",".join(["%s"] * len(all_codes))

        rubric_rows = fetch_all(f"""
            SELECT fiscal_year, rubric_code, value
            FROM financial_data
            WHERE enterprise_number = %s
              AND period = 'N'
              AND rubric_code IN ({placeholders})
        """, [cbe] + all_codes)

        # Pivot rubric data: {rubric_code: {fiscal_year: value}}
        rubric_pivot = {}
        for row in rubric_rows:
            code = row["rubric_code"]
            fy = row["fiscal_year"]
            val = row["value"]
            if code not in rubric_pivot:
                rubric_pivot[code] = {}
            rubric_pivot[code][str(fy)] = float(val) if val is not None else None

        return {
            "summary": [_serialize_row(r) for r in hist],
            "rubric_data": rubric_pivot,
        }
    except Exception as e:
        logger.exception("Company financials query failed")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# GET /api/companies/{cbe}/structure
# ---------------------------------------------------------------------------

@router.get("/{cbe}/structure")
async def get_company_structure(cbe: str):
    """Admins, shareholders, participating interests, and Staatsblad publications.

    SQL extracted from app/pages/2_company.py load_company_detail().
    """
    cbe = cbe.strip().replace(".", "")

    try:
        admins = fetch_all(
            "SELECT * FROM administrator WHERE enterprise_number = %s ORDER BY mandate_start DESC",
            (cbe,),
        )
        pis = fetch_all(
            "SELECT * FROM participating_interest WHERE enterprise_number = %s ORDER BY name",
            (cbe,),
        )
        shareholders = fetch_all(
            "SELECT * FROM shareholder WHERE enterprise_number = %s ORDER BY name",
            (cbe,),
        )
        sb_pubs = fetch_all(
            "SELECT pub_date, pub_type, reference, pdf_url FROM staatsblad_publication "
            "WHERE enterprise_number = %s ORDER BY pub_date DESC",
            (cbe,),
        )

        # Enrich admin rows with role labels
        for admin in admins:
            admin["role_label"] = ROLE_LABELS.get(admin.get("role", ""), admin.get("role", ""))

        return {
            "administrators": [_serialize_row(r) for r in admins],
            "participating_interests": [_serialize_row(r) for r in pis],
            "shareholders": [_serialize_row(r) for r in shareholders],
            "staatsblad_publications": [_serialize_row(r) for r in sb_pubs],
        }
    except Exception as e:
        logger.exception("Company structure query failed")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# GET /api/companies/{cbe}/network
# ---------------------------------------------------------------------------

def _fetch_connections(cbes: list) -> tuple:
    """Batch-fetch subsidiaries and shareholders for a set of CBEs.

    SQL extracted from app/pages/2_company.py fetch_connections().
    """
    if not cbes:
        return [], []
    conn = get_connection()
    try:
        import psycopg2.extras
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
        return subs, shs
    finally:
        conn.close()


def _fetch_entity_names(cbes: list) -> dict:
    """Batch-resolve CBE numbers to company names.

    SQL extracted from app/pages/2_company.py fetch_entity_names().
    """
    if not cbes:
        return {}
    conn = get_connection()
    try:
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
        return {r[0]: r[1] for r in rows}
    finally:
        conn.close()


@router.get("/{cbe}/network")
async def get_company_network(cbe: str, max_depth: int = Query(1, ge=1, le=3)):
    """BFS network graph data for the corporate spider-web.

    Logic extracted from app/pages/2_company.py bfs_build_graph().
    Returns nodes and edges in a JSON-friendly format for frontend rendering.
    """
    cbe = cbe.strip().replace(".", "")

    try:
        # Get central company name
        header = fetch_one("""
            SELECT d.denomination AS "name"
            FROM denomination d
            WHERE d.entity_number = %s AND d.type_of_denomination = '001'
            LIMIT 1
        """, (cbe,))
        central_name = header["name"] if header else cbe

        # Get direct relationships
        admins = fetch_all(
            "SELECT * FROM administrator WHERE enterprise_number = %s",
            (cbe,),
        )
        shareholders_rows = fetch_all(
            "SELECT * FROM shareholder WHERE enterprise_number = %s",
            (cbe,),
        )
        pis_rows = fetch_all(
            "SELECT * FROM participating_interest WHERE enterprise_number = %s",
            (cbe,),
        )

        # Build graph via BFS
        nodes = []
        edges = []
        visited = {cbe}
        nav_options = {}
        truncated = False

        # Central node
        nodes.append({
            "id": cbe,
            "label": central_name,
            "type": "central",
            "size": 35,
            "color": "#6366f1",
            "cbe": cbe,
            "depth": 0,
        })

        frontier = set()

        # Shareholders at depth 0
        seen_sh_names = set()
        for i, sh in enumerate(shareholders_rows):
            sname = sh.get("name") or "Unknown"
            if sname in seen_sh_names:
                continue
            seen_sh_names.add(sname)

            cbe_clean = _clean_cbe(sh.get("identifier"))
            is_indiv = sh.get("shareholder_type") == "individual"
            pct = sh.get("ownership_pct")
            nid = cbe_clean if cbe_clean else f"sh_{i}"

            node_size = max(14, min(28, int(18 + (float(pct) if pct else 0) / 10))) if not is_indiv else 14

            nodes.append({
                "id": nid,
                "label": sname,
                "type": "shareholder",
                "subtype": "individual" if is_indiv else "company",
                "size": node_size,
                "color": "#86efac" if is_indiv else "#22c55e",
                "cbe": cbe_clean,
                "depth": 1,
                "ownership_pct": float(pct) if pct else None,
            })
            edges.append({
                "source": nid,
                "target": cbe,
                "type": "shareholder",
                "label": f"{pct:.0f}%" if pct else "",
                "color": "#22c55e",
                "dash": "dash",
            })

            if cbe_clean and cbe_clean not in visited:
                frontier.add(cbe_clean)
                nav_options[cbe_clean] = sname

        # Subsidiaries at depth 0
        seen_pi_names = set()
        for i, pi in enumerate(pis_rows):
            pname = pi.get("name") or "Unknown"
            if pname in seen_pi_names:
                continue
            seen_pi_names.add(pname)

            cbe_clean = _clean_cbe(pi.get("identifier"))
            pct = pi.get("ownership_pct")
            country = pi.get("country") or ""
            nid = cbe_clean if cbe_clean else f"pi_{i}"

            node_size = max(14, min(28, int(18 + (float(pct) if pct else 0) / 10)))

            nodes.append({
                "id": nid,
                "label": pname,
                "type": "subsidiary",
                "size": node_size,
                "color": "#f97316",
                "cbe": cbe_clean,
                "depth": 1,
                "ownership_pct": float(pct) if pct else None,
                "country": country,
            })
            edges.append({
                "source": cbe,
                "target": nid,
                "type": "subsidiary",
                "label": f"{pct:.0f}%" if pct else "",
                "color": "#f97316",
                "dash": "solid",
            })

            if cbe_clean and cbe_clean not in visited:
                frontier.add(cbe_clean)
                nav_options[cbe_clean] = pname

        # Admins at depth 0
        seen_admin_names = set()
        for i, ad in enumerate(admins):
            aname = ad.get("name") or "Unknown"
            role_key = ad.get("role", "")
            name_role = f"{aname}_{role_key}"
            if name_role in seen_admin_names:
                continue
            seen_admin_names.add(name_role)

            role = ROLE_LABELS.get(role_key, role_key or "Administrator")
            cbe_clean = _clean_cbe(ad.get("identifier"))
            is_legal = ad.get("person_type") == "legal"
            nid = cbe_clean if cbe_clean else f"ad_{i}"

            existing = [n for n in nodes if n["id"] == nid]
            if not existing:
                nodes.append({
                    "id": nid,
                    "label": aname,
                    "type": "admin",
                    "subtype": "legal" if is_legal else "natural",
                    "size": 14 if is_legal else 12,
                    "color": "#06b6d4" if is_legal else "#94a3b8",
                    "cbe": cbe_clean,
                    "depth": 1,
                })
            edges.append({
                "source": nid,
                "target": cbe,
                "type": "admin",
                "label": role,
                "color": "#94a3b8",
                "dash": "dot",
            })

            if cbe_clean:
                nav_options[cbe_clean] = aname

        visited.update(frontier)

        # BFS expansion for deeper levels
        queue = deque(frontier)
        current_depth = 1

        while queue and current_depth < max_depth:
            batch_cbes = set()
            while queue:
                batch_cbes.add(queue.popleft())

            if not batch_cbes or len(nodes) >= MAX_NETWORK_NODES:
                if len(nodes) >= MAX_NETWORK_NODES:
                    truncated = True
                break

            sub_recs, sh_recs = _fetch_connections(list(sorted(batch_cbes)))

            new_cbes = set()
            for rec in sub_recs + sh_recs:
                c = _clean_cbe(rec.get("identifier"))
                if c and c not in {n["id"] for n in nodes}:
                    new_cbes.add(c)
            name_map = _fetch_entity_names(list(sorted(new_cbes))) if new_cbes else {}

            d = current_depth + 1
            next_frontier = set()

            # Shareholders of expanded entities
            seen_edges = set()
            for rec in sh_recs:
                source_cbe = rec["enterprise_number"]
                target_cbe = _clean_cbe(rec.get("identifier"))
                sname = rec.get("name") or "Unknown"
                pct = rec.get("ownership_pct")

                nid = target_cbe if target_cbe else f"sh_d{d}_{sname[:10]}"
                edge_key = (nid, source_cbe)
                if edge_key in seen_edges:
                    continue
                seen_edges.add(edge_key)

                if len(nodes) >= MAX_NETWORK_NODES:
                    truncated = True
                    break

                existing = [n for n in nodes if n["id"] == nid]
                if not existing:
                    label = name_map.get(target_cbe, sname) if target_cbe else sname
                    nodes.append({
                        "id": nid,
                        "label": label,
                        "type": "shareholder",
                        "size": max(8, 14 - d * 3),
                        "color": "#bbf7d0",
                        "cbe": target_cbe,
                        "depth": d,
                        "ownership_pct": float(pct) if pct else None,
                    })
                    if target_cbe:
                        nav_options[target_cbe] = label

                edges.append({
                    "source": nid,
                    "target": source_cbe,
                    "type": "shareholder",
                    "label": f"{pct:.0f}%" if pct else "",
                    "color": "#bbf7d0",
                    "dash": "dash",
                })

                if target_cbe and target_cbe not in visited:
                    next_frontier.add(target_cbe)

            # Subsidiaries of expanded entities
            seen_edges = set()
            for rec in sub_recs:
                source_cbe = rec["enterprise_number"]
                target_cbe = _clean_cbe(rec.get("identifier"))
                pname = rec.get("name") or "Unknown"
                pct = rec.get("ownership_pct")
                country = rec.get("country") or ""

                nid = target_cbe if target_cbe else f"pi_d{d}_{pname[:10]}"
                edge_key = (source_cbe, nid)
                if edge_key in seen_edges:
                    continue
                seen_edges.add(edge_key)

                if len(nodes) >= MAX_NETWORK_NODES:
                    truncated = True
                    break

                existing = [n for n in nodes if n["id"] == nid]
                if not existing:
                    label = name_map.get(target_cbe, pname) if target_cbe else pname
                    nodes.append({
                        "id": nid,
                        "label": label,
                        "type": "subsidiary",
                        "size": max(8, 14 - d * 3),
                        "color": "#fed7aa",
                        "cbe": target_cbe,
                        "depth": d,
                        "ownership_pct": float(pct) if pct else None,
                        "country": country,
                    })
                    if target_cbe:
                        nav_options[target_cbe] = label

                edges.append({
                    "source": source_cbe,
                    "target": nid,
                    "type": "subsidiary",
                    "label": f"{pct:.0f}%" if pct else "",
                    "color": "#fed7aa",
                    "dash": "solid",
                })

                if target_cbe and target_cbe not in visited:
                    next_frontier.add(target_cbe)

            visited.update(next_frontier)
            for c in next_frontier:
                queue.append(c)
            current_depth += 1

        return {
            "nodes": nodes,
            "edges": edges,
            "nav_options": nav_options,
            "truncated": truncated,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Company network query failed")
        raise HTTPException(status_code=500, detail=str(e))
