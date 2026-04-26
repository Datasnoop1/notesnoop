"""Companies network router — corporate spider-web BFS graph."""

import logging
from collections import deque
from datetime import date

from fastapi import APIRouter, HTTPException, Query

from db import fetch_all, fetch_one
from utils import clean_cbe
from ._helpers import (
    _clean_cbe,
    _fetch_connections,
    _fetch_entity_names,
    ROLE_LABELS,
    MAX_NETWORK_NODES,
    MAX_DEEP_NETWORK_NODES,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# GET /api/companies/{cbe}/network
# ---------------------------------------------------------------------------

@router.get("/{cbe}/network")
async def get_company_network(
    cbe: str,
    max_depth: int = Query(1, ge=1, le=3),
    include_historical: bool = Query(
        False,
        description="If true, include past directorships and prior-filing "
                    "shareholders/participations. Default keeps only present-day "
                    "links so the spider web isn't cluttered with stale ties.",
    ),
):
    """BFS network graph data for the corporate spider-web.

    Logic extracted from app/pages/2_company.py bfs_build_graph().
    Returns nodes and edges in a JSON-friendly format for frontend rendering.
    """
    cbe = clean_cbe(cbe)

    try:
        # Get central company name
        header = fetch_one("""
            SELECT d.denomination AS "name"
            FROM denomination d
            WHERE d.entity_number = %s AND d.type_of_denomination = '001'
            LIMIT 1
        """, (cbe,))
        central_name = header["name"] if header else cbe

        # Direct relationships. By default we keep only "current" links:
        #  - admins with no mandate_end OR an end date in the future,
        #  - shareholders / participating_interests from each enterprise's
        #    most recent fiscal_year (older filings are past snapshots).
        # The `include_historical=true` flag drops these filters so the
        # frontend toggle can reveal prior ties.
        today_str = date.today().isoformat()
        if include_historical:
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
        else:
            # NBB stores the *scheduled* mandate end (often years out per
            # statutory term). A real-world resignation lands first in the
            # Staatsblad as an admin_event with sub_type=resignation/end/
            # termination. Exclude any NBB row whose name (case- and
            # punctuation-tolerant compare) has a Staatsblad resignation
            # published AFTER the recorded mandate_start — that's how the
            # admins-tab reconciles the two sources, see
            # backend/routers/companies/structure_merge.py.
            admins = fetch_all(
                "SELECT * FROM administrator a "
                "WHERE a.enterprise_number = %s "
                "  AND (a.mandate_end IS NULL OR a.mandate_end >= %s) "
                "  AND NOT EXISTS ("
                "    SELECT 1 FROM staatsblad_event se "
                "    WHERE se.enterprise_number = a.enterprise_number "
                "      AND se.event_type = 'admin_event' "
                "      AND LOWER(se.sub_type) IN ('resignation','end','termination') "
                "      AND LOWER(REGEXP_REPLACE(COALESCE(se.person_name, se.entity_name), '[.,]', '', 'g')) "
                "          = LOWER(REGEXP_REPLACE(a.name, '[.,]', '', 'g')) "
                "      AND (a.mandate_start IS NULL "
                "           OR se.pub_date > a.mandate_start::date)"
                "  )",
                (cbe, today_str),
            )
            shareholders_rows = fetch_all(
                "SELECT * FROM shareholder "
                "WHERE enterprise_number = %s "
                "  AND fiscal_year = ("
                "    SELECT MAX(fiscal_year) FROM shareholder "
                "    WHERE enterprise_number = %s"
                "  )",
                (cbe, cbe),
            )
            pis_rows = fetch_all(
                "SELECT * FROM participating_interest "
                "WHERE enterprise_number = %s "
                "  AND fiscal_year = ("
                "    SELECT MAX(fiscal_year) FROM participating_interest "
                "    WHERE enterprise_number = %s"
                "  )",
                (cbe, cbe),
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

        # Staatsblad-sourced admin events at depth 0 — augment the NBB
        # snapshot with freshly-filed appointments that haven't landed
        # in an NBB annual yet. Dedupe by (name, role) so a person
        # already in the NBB list doesn't get a duplicate node.
        sb_admins = fetch_all("""
            SELECT DISTINCT ON (COALESCE(person_name, entity_name), COALESCE(person_role, ''))
                   person_name, entity_name, person_role, sub_type, pub_date,
                   pub_reference
            FROM staatsblad_event
            WHERE enterprise_number = %s
              AND event_type = 'admin_event'
              AND COALESCE(sub_type, '') NOT IN ('resignation', 'end', 'termination')
            ORDER BY COALESCE(person_name, entity_name), COALESCE(person_role, ''),
                     pub_date DESC, id DESC
        """, (cbe,))
        for ev in sb_admins:
            aname = ev.get("person_name") or ev.get("entity_name") or "Unknown"
            role_key = ev.get("person_role") or ""
            name_role = f"{aname}_{role_key}"
            if name_role in seen_admin_names:
                continue
            seen_admin_names.add(name_role)

            role = role_key or "Administrator"
            is_legal = bool(ev.get("entity_name") and not ev.get("person_name"))
            # Stable + collision-safe id via SHA-1 of (name, role).  Avoids
            # breaking graph libraries on names with spaces/punctuation and
            # long-prefix collisions from the previous `sb_{aname[:20]}_...`
            # scheme.
            import hashlib as _hashlib
            _nid_digest = _hashlib.sha1(
                f"{aname}|{role_key}".encode("utf-8"), usedforsecurity=False
            ).hexdigest()[:16]
            nid = f"sb_{_nid_digest}"

            if not any(n["id"] == nid for n in nodes):
                nodes.append({
                    "id": nid,
                    "label": aname,
                    "type": "admin",
                    "subtype": "legal" if is_legal else "natural",
                    "size": 14 if is_legal else 12,
                    # Staatsblad-sourced admins get a brighter emerald
                    # tint so the UI can distinguish "fresh" edges.
                    "color": "#10b981" if is_legal else "#34d399",
                    "cbe": None,
                    "depth": 1,
                    "source": "staatsblad",
                    "as_of": str(ev.get("pub_date") or ""),
                })
            edges.append({
                "source": nid,
                "target": cbe,
                "type": "admin",
                "label": role,
                "color": "#10b981",
                # `solid` line for Staatsblad edges (vs `dot` for NBB),
                # signalling freshness.
                "dash": "solid",
                "source_data": "staatsblad",
            })

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

            sub_recs, sh_recs = _fetch_connections(
                list(sorted(batch_cbes)),
                include_historical=include_historical,
            )

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
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/companies/{cbe}/deep-network?depth=3
# ---------------------------------------------------------------------------

@router.get("/{cbe}/deep-network")
async def get_deep_network(
    cbe: str,
    depth: int = Query(3, ge=1, le=4),
    include_historical: bool = Query(
        False,
        description="If true, include past directorships and prior-filing "
                    "shareholders/participations in the BFS expansion. "
                    "Default keeps only present-day links.",
    ),
):
    """Deep corporate network graph — traverse administrator, shareholder,
    and participating_interest links up to 4 hops to find hidden connections.

    Uses BFS with batched queries at each depth level.  Nodes are companies
    and people; edges carry the relationship type and a human-readable label.
    Total nodes are capped at MAX_DEEP_NETWORK_NODES to prevent explosion.
    """
    raw_center = (cbe or "").strip()
    is_person_center = raw_center.startswith("person:")
    person_name = raw_center.split(":", 1)[1].strip() if is_person_center else None
    if not is_person_center:
        cbe = clean_cbe(cbe)

    try:
        nodes: list[dict] = []
        edges: list[dict] = []
        node_ids: set[str] = set()
        truncated = False

        def _add_node(nid: str, name: str, ntype: str, d: int) -> bool:
            """Add a node if not already present. Returns True if added."""
            nonlocal truncated
            if nid in node_ids:
                return False
            if len(nodes) >= MAX_DEEP_NETWORK_NODES:
                truncated = True
                return False
            node_ids.add(nid)
            nodes.append({"id": nid, "name": name, "type": ntype, "depth": d})
            return True

        def _add_edge(src: str, tgt: str, rel: str, label: str):
            """Add an edge (duplicates possible between same pair via different rels)."""
            edges.append({
                "source": src, "target": tgt,
                "relationship": rel, "label": label,
            })

        # Reference date for active-mandate classification.
        today_str = date.today().isoformat()

        # Seed node + first frontier
        if is_person_center:
            if not person_name:
                raise HTTPException(status_code=404, detail="Person not found")

            root_id = f"person:{person_name}"
            _add_node(root_id, person_name, "person", 0)

            # Person seed: only show companies where this person currently
            # serves. Past mandates produce dead spider-web edges.
            if include_historical:
                seed_admin_rows = fetch_all(
                    "SELECT enterprise_number, role "
                    "FROM administrator "
                    "WHERE name = %s "
                    "GROUP BY enterprise_number, role",
                    [person_name],
                )
                seed_sh_rows = fetch_all(
                    "SELECT DISTINCT enterprise_number, ownership_pct "
                    "FROM shareholder WHERE name = %s",
                    (person_name,),
                )
            else:
                # See get_company_network — NBB mandate_end is the scheduled
                # term, not the real-world end date; combine with Staatsblad
                # resignations to filter out people who have left the board.
                seed_admin_rows = fetch_all(
                    "SELECT a.enterprise_number, a.role "
                    "FROM administrator a "
                    "WHERE a.name = %s "
                    "  AND (a.mandate_end IS NULL OR a.mandate_end >= %s) "
                    "  AND NOT EXISTS ("
                    "    SELECT 1 FROM staatsblad_event se "
                    "    WHERE se.enterprise_number = a.enterprise_number "
                    "      AND se.event_type = 'admin_event' "
                    "      AND LOWER(se.sub_type) IN ('resignation','end','termination') "
                    "      AND LOWER(REGEXP_REPLACE(COALESCE(se.person_name, se.entity_name), '[.,]', '', 'g')) "
                    "          = LOWER(REGEXP_REPLACE(a.name, '[.,]', '', 'g')) "
                    "      AND (a.mandate_start IS NULL "
                    "           OR se.pub_date > a.mandate_start::date)"
                    "  ) "
                    "GROUP BY a.enterprise_number, a.role",
                    [person_name, today_str],
                )
                # Person-as-shareholder restricted to each company's most
                # recent fiscal_year so a 2018 ownership stake the person
                # has since exited doesn't seed a stale spider web.
                seed_sh_rows = fetch_all(
                    "SELECT DISTINCT s.enterprise_number, s.ownership_pct "
                    "FROM shareholder s "
                    "WHERE s.name = %s "
                    "  AND s.fiscal_year = ("
                    "    SELECT MAX(fiscal_year) FROM shareholder "
                    "    WHERE enterprise_number = s.enterprise_number"
                    "  )",
                    (person_name,),
                )

            seed_company_ids = sorted(
                {
                    row.get("enterprise_number")
                    for row in (seed_admin_rows + seed_sh_rows)
                    if row.get("enterprise_number")
                }
            )
            if not seed_company_ids:
                raise HTTPException(
                    status_code=404,
                    detail=f"Person {person_name} has no current company links",
                )

            seed_name_map = _fetch_entity_names(seed_company_ids)
            frontier: set[str] = set()

            seen_seed_admin = set()
            for row in seed_admin_rows:
                ent = row["enterprise_number"]
                role_key = row.get("role") or ""
                edge_key = (root_id, ent, "administrator", role_key)
                if edge_key in seen_seed_admin:
                    continue
                seen_seed_admin.add(edge_key)

                role_label = ROLE_LABELS.get(role_key, role_key or "Administrator")
                _add_node(ent, seed_name_map.get(ent, ent), "company", 1)
                _add_edge(root_id, ent, "administrator", role_label)
                frontier.add(ent)

            seen_seed_sh = set()
            for row in seed_sh_rows:
                ent = row["enterprise_number"]
                edge_key = (root_id, ent, "shareholder")
                if edge_key in seen_seed_sh:
                    continue
                seen_seed_sh.add(edge_key)

                pct = row.get("ownership_pct")
                pct_label = f"{pct:.0f}%" if pct else ""
                _add_node(ent, seed_name_map.get(ent, ent), "company", 1)
                _add_edge(root_id, ent, "shareholder", pct_label)
                frontier.add(ent)

            start_depth = 2
        else:
            # Resolve the starting company name
            header = fetch_one(
                "SELECT denomination AS name FROM denomination "
                "WHERE entity_number = %s AND type_of_denomination = '001' LIMIT 1",
                (cbe,),
            )
            if not header:
                raise HTTPException(status_code=404, detail=f"Company {cbe} not found")

            _add_node(cbe, header["name"], "company", 0)
            frontier = {cbe}
            start_depth = 1

        for current_depth in range(start_depth, depth + 1):
            if not frontier or len(nodes) >= MAX_DEEP_NETWORK_NODES:
                break

            batch = list(sorted(frontier))
            frontier = set()

            # ── Fetch all relationships for the current batch ──────────
            ph = ",".join(["%s"] * len(batch))

            # Administrator queries. By default we want only currently-
            # serving directors. NBB stores the *scheduled* mandate end
            # (often years out), so a real-world resignation only shows
            # up in the staatsblad_event log. The NOT EXISTS clause drops
            # rows whose name matches a Staatsblad resignation event
            # published after the recorded mandate_start. Same name-match
            # convention as backend/routers/companies/structure_merge.py.
            # `include_historical=True` skips both filters for the
            # archival spider-web view.
            if include_historical:
                admin_filter_sql = ""
                admin_filter_args: list = []
            else:
                admin_filter_sql = (
                    "  AND (a.mandate_end IS NULL OR a.mandate_end >= %s) "
                    "  AND NOT EXISTS ("
                    "    SELECT 1 FROM staatsblad_event se "
                    "    WHERE se.enterprise_number = a.enterprise_number "
                    "      AND se.event_type = 'admin_event' "
                    "      AND LOWER(se.sub_type) IN ('resignation','end','termination') "
                    "      AND LOWER(REGEXP_REPLACE(COALESCE(se.person_name, se.entity_name), '[.,]', '', 'g')) "
                    "          = LOWER(REGEXP_REPLACE(a.name, '[.,]', '', 'g')) "
                    "      AND (a.mandate_start IS NULL "
                    "           OR se.pub_date > a.mandate_start::date)"
                    "  ) "
                )
                admin_filter_args = [today_str]

            # 1. Administrators OF these companies
            admin_rows = fetch_all(
                f"SELECT a.enterprise_number, a.name, a.role, a.person_type, a.identifier "
                f"FROM administrator a "
                f"WHERE a.enterprise_number IN ({ph}) "
                f"{admin_filter_sql}"
                f"GROUP BY a.enterprise_number, a.name, a.role, a.person_type, a.identifier",
                batch + admin_filter_args,
            )

            # 2. Companies where these entities serve as administrator (reverse)
            admin_reverse_rows = fetch_all(
                f"SELECT a.enterprise_number, a.name, a.role, a.person_type, a.identifier "
                f"FROM administrator a "
                f"WHERE a.identifier IN ({ph}) "
                f"{admin_filter_sql}"
                f"GROUP BY a.enterprise_number, a.name, a.role, a.person_type, a.identifier",
                batch + admin_filter_args,
            )

            # 3-6. Shareholders / participating-interest queries. By default
            # we restrict to each enterprise's most recent fiscal_year per
            # JOIN side so prior ownership snapshots don't leak into the
            # graph. `include_historical=True` drops the filter.
            if include_historical:
                sh_rows = fetch_all(
                    f"SELECT DISTINCT enterprise_number, name, identifier, ownership_pct, shareholder_type "
                    f"FROM shareholder WHERE enterprise_number IN ({ph})",
                    batch,
                )
                sh_reverse_rows = fetch_all(
                    f"SELECT DISTINCT enterprise_number, name, identifier, ownership_pct, shareholder_type "
                    f"FROM shareholder WHERE identifier IN ({ph})",
                    batch,
                )
                pi_rows = fetch_all(
                    f"SELECT DISTINCT enterprise_number, name, identifier, ownership_pct, country "
                    f"FROM participating_interest WHERE enterprise_number IN ({ph})",
                    batch,
                )
                pi_reverse_rows = fetch_all(
                    f"SELECT DISTINCT enterprise_number, name, identifier, ownership_pct, country "
                    f"FROM participating_interest WHERE identifier IN ({ph})",
                    batch,
                )
            else:
                # Forward direction: latest fiscal_year per source enterprise.
                sh_rows = fetch_all(
                    f"WITH latest AS ("
                    f"  SELECT enterprise_number, MAX(fiscal_year) AS fy "
                    f"  FROM shareholder WHERE enterprise_number IN ({ph}) "
                    f"  GROUP BY enterprise_number"
                    f") "
                    f"SELECT DISTINCT s.enterprise_number, s.name, s.identifier, "
                    f"       s.ownership_pct, s.shareholder_type "
                    f"FROM shareholder s "
                    f"JOIN latest l ON l.enterprise_number = s.enterprise_number "
                    f"             AND l.fy = s.fiscal_year",
                    batch,
                )
                pi_rows = fetch_all(
                    f"WITH latest AS ("
                    f"  SELECT enterprise_number, MAX(fiscal_year) AS fy "
                    f"  FROM participating_interest WHERE enterprise_number IN ({ph}) "
                    f"  GROUP BY enterprise_number"
                    f") "
                    f"SELECT DISTINCT pi.enterprise_number, pi.name, pi.identifier, "
                    f"       pi.ownership_pct, pi.country "
                    f"FROM participating_interest pi "
                    f"JOIN latest l ON l.enterprise_number = pi.enterprise_number "
                    f"             AND l.fy = pi.fiscal_year",
                    batch,
                )
                # Reverse direction: "which OTHER enterprises currently
                # name one of `batch` as a shareholder / participation?"
                #
                # Two-step CTE so `latest` reflects each enterprise's most
                # recent filing in absolute terms, NOT just the latest
                # filing in which `batch` happened to appear. Otherwise an
                # enterprise that DROPPED a member of `batch` from its
                # cap table would still surface the prior filing as if
                # it were current. The `relevant` CTE narrows the MAX
                # scan to enterprises that have ever filed a member of
                # `batch`, so we don't scan the whole table for nothing.
                sh_reverse_rows = fetch_all(
                    f"WITH relevant AS ("
                    f"  SELECT DISTINCT enterprise_number "
                    f"  FROM shareholder WHERE identifier IN ({ph})"
                    f"), "
                    f"latest AS ("
                    f"  SELECT s.enterprise_number, MAX(s.fiscal_year) AS fy "
                    f"  FROM shareholder s "
                    f"  JOIN relevant r ON r.enterprise_number = s.enterprise_number "
                    f"  GROUP BY s.enterprise_number"
                    f") "
                    f"SELECT DISTINCT s.enterprise_number, s.name, s.identifier, "
                    f"       s.ownership_pct, s.shareholder_type "
                    f"FROM shareholder s "
                    f"JOIN latest l ON l.enterprise_number = s.enterprise_number "
                    f"             AND l.fy = s.fiscal_year "
                    f"WHERE s.identifier IN ({ph})",
                    batch + batch,
                )
                pi_reverse_rows = fetch_all(
                    f"WITH relevant AS ("
                    f"  SELECT DISTINCT enterprise_number "
                    f"  FROM participating_interest WHERE identifier IN ({ph})"
                    f"), "
                    f"latest AS ("
                    f"  SELECT pi.enterprise_number, MAX(pi.fiscal_year) AS fy "
                    f"  FROM participating_interest pi "
                    f"  JOIN relevant r ON r.enterprise_number = pi.enterprise_number "
                    f"  GROUP BY pi.enterprise_number"
                    f") "
                    f"SELECT DISTINCT pi.enterprise_number, pi.name, pi.identifier, "
                    f"       pi.ownership_pct, pi.country "
                    f"FROM participating_interest pi "
                    f"JOIN latest l ON l.enterprise_number = pi.enterprise_number "
                    f"             AND l.fy = pi.fiscal_year "
                    f"WHERE pi.identifier IN ({ph})",
                    batch + batch,
                )

            # Collect all new CBE numbers we discover so we can batch-resolve names
            new_cbes: set[str] = set()

            def _collect_cbe(identifier) -> str | None:
                c = _clean_cbe(identifier)
                if c and c not in node_ids:
                    new_cbes.add(c)
                return c

            # Scan all rows for new CBEs before adding nodes
            for row in admin_rows:
                _collect_cbe(row.get("identifier"))
            for row in admin_reverse_rows:
                _collect_cbe(row.get("enterprise_number"))
            for row in sh_rows:
                _collect_cbe(row.get("identifier"))
            for row in sh_reverse_rows:
                _collect_cbe(row.get("enterprise_number"))
            for row in pi_rows:
                _collect_cbe(row.get("identifier"))
            for row in pi_reverse_rows:
                _collect_cbe(row.get("enterprise_number"))

            # Batch-resolve names for all new CBEs
            name_map = _fetch_entity_names(list(sorted(new_cbes))) if new_cbes else {}

            # ── Process administrators (forward: company -> admin) ──────
            seen_admin = set()
            for row in admin_rows:
                ent = row["enterprise_number"]
                aname = row.get("name") or "Unknown"
                role_key = row.get("role") or ""
                is_legal = row.get("person_type") == "legal"
                cbe_id = _clean_cbe(row.get("identifier"))
                nid = cbe_id if cbe_id else f"person:{aname}"
                ntype = "company" if is_legal and cbe_id else "person"
                edge_key = (nid, ent, "administrator", role_key)
                if edge_key in seen_admin:
                    continue
                seen_admin.add(edge_key)

                label_name = name_map.get(cbe_id, aname) if cbe_id else aname
                role_label = ROLE_LABELS.get(role_key, role_key or "Administrator")
                added = _add_node(nid, label_name, ntype, current_depth)
                _add_edge(nid, ent, "administrator", role_label)

                if cbe_id and added:
                    frontier.add(cbe_id)

            # ── Process administrators (reverse: admin -> other companies) ──
            seen_admin_rev = set()
            for row in admin_reverse_rows:
                target_ent = row["enterprise_number"]
                identifier = row.get("identifier")
                cbe_id = _clean_cbe(identifier)
                if not cbe_id or cbe_id not in node_ids:
                    continue  # only expand from known nodes
                role_key = row.get("role") or ""
                edge_key = (cbe_id, target_ent, "administrator_reverse", role_key)
                if edge_key in seen_admin_rev:
                    continue
                seen_admin_rev.add(edge_key)

                target_name = name_map.get(target_ent, row.get("name") or target_ent)
                role_label = ROLE_LABELS.get(role_key, role_key or "Administrator")
                added = _add_node(target_ent, target_name, "company", current_depth)
                _add_edge(cbe_id, target_ent, "administrator", role_label)
                if added:
                    frontier.add(target_ent)

            # ── Process shareholders (forward: company -> shareholder) ──
            seen_sh = set()
            for row in sh_rows:
                ent = row["enterprise_number"]
                sname = row.get("name") or "Unknown"
                cbe_id = _clean_cbe(row.get("identifier"))
                pct = row.get("ownership_pct")
                is_indiv = row.get("shareholder_type") == "individual"
                nid = cbe_id if cbe_id else f"person:{sname}"
                ntype = "company" if cbe_id else "person"
                edge_key = (nid, ent, "shareholder")
                if edge_key in seen_sh:
                    continue
                seen_sh.add(edge_key)

                label_name = name_map.get(cbe_id, sname) if cbe_id else sname
                pct_label = f"{pct:.0f}%" if pct else ""
                added = _add_node(nid, label_name, ntype, current_depth)
                _add_edge(nid, ent, "shareholder", pct_label)
                if cbe_id and added:
                    frontier.add(cbe_id)

            # ── Process shareholders (reverse: entity holds shares elsewhere) ──
            seen_sh_rev = set()
            for row in sh_reverse_rows:
                target_ent = row["enterprise_number"]
                cbe_id = _clean_cbe(row.get("identifier"))
                if not cbe_id or cbe_id not in node_ids:
                    continue
                pct = row.get("ownership_pct")
                edge_key = (cbe_id, target_ent, "shareholder_reverse")
                if edge_key in seen_sh_rev:
                    continue
                seen_sh_rev.add(edge_key)

                target_name = name_map.get(target_ent, row.get("name") or target_ent)
                pct_label = f"{pct:.0f}%" if pct else ""
                added = _add_node(target_ent, target_name, "company", current_depth)
                _add_edge(cbe_id, target_ent, "shareholder", pct_label)
                if added:
                    frontier.add(target_ent)

            # ── Process participating interests (forward: company -> subsidiary) ──
            seen_pi = set()
            for row in pi_rows:
                ent = row["enterprise_number"]
                pname = row.get("name") or "Unknown"
                cbe_id = _clean_cbe(row.get("identifier"))
                pct = row.get("ownership_pct")
                nid = cbe_id if cbe_id else f"sub:{pname}"
                ntype = "company" if cbe_id else "subsidiary"
                edge_key = (ent, nid, "participating_interest")
                if edge_key in seen_pi:
                    continue
                seen_pi.add(edge_key)

                label_name = name_map.get(cbe_id, pname) if cbe_id else pname
                pct_label = f"{pct:.0f}%" if pct else ""
                added = _add_node(nid, label_name, ntype, current_depth)
                _add_edge(ent, nid, "participating_interest", pct_label)
                if cbe_id and added:
                    frontier.add(cbe_id)

            # ── Process participating interests (reverse: parent companies) ──
            seen_pi_rev = set()
            for row in pi_reverse_rows:
                parent_ent = row["enterprise_number"]
                cbe_id = _clean_cbe(row.get("identifier"))
                if not cbe_id or cbe_id not in node_ids:
                    continue
                pct = row.get("ownership_pct")
                edge_key = (parent_ent, cbe_id, "participating_interest_reverse")
                if edge_key in seen_pi_rev:
                    continue
                seen_pi_rev.add(edge_key)

                parent_name = name_map.get(parent_ent, row.get("name") or parent_ent)
                pct_label = f"{pct:.0f}%" if pct else ""
                added = _add_node(parent_ent, parent_name, "company", current_depth)
                _add_edge(parent_ent, cbe_id, "participating_interest", pct_label)
                if added:
                    frontier.add(parent_ent)

            # Only expand CBEs that were actually added as nodes
            frontier = {c for c in frontier if c in node_ids} - set(batch)

        return {
            "nodes": nodes,
            "edges": edges,
            "truncated": truncated,
            "depth_reached": min(depth, max((n["depth"] for n in nodes), default=0)),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Deep network query failed for %s", raw_center or cbe)
        raise HTTPException(status_code=500, detail="Internal server error")
