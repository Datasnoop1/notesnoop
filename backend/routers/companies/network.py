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
async def get_company_network(cbe: str, max_depth: int = Query(1, ge=1, le=3)):
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
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# GET /api/companies/{cbe}/deep-network?depth=3
# ---------------------------------------------------------------------------

@router.get("/{cbe}/deep-network")
async def get_deep_network(cbe: str, depth: int = Query(3, ge=1, le=4)):
    """Deep corporate network graph — traverse administrator, shareholder,
    and participating_interest links up to 4 hops to find hidden connections.

    Uses BFS with batched queries at each depth level.  Nodes are companies
    and people; edges carry the relationship type and a human-readable label.
    Total nodes are capped at MAX_DEEP_NETWORK_NODES to prevent explosion.
    """
    cbe = clean_cbe(cbe)

    try:
        # Resolve the starting company name
        header = fetch_one(
            "SELECT denomination AS name FROM denomination "
            "WHERE entity_number = %s AND type_of_denomination = '001' LIMIT 1",
            (cbe,),
        )
        if not header:
            raise HTTPException(status_code=404, detail=f"Company {cbe} not found")

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

        def _add_edge(src: str, tgt: str, rel: str, label: str,
                      is_active: bool = True, mandate_end: str | None = None):
            """Add an edge (duplicates possible between same pair via different rels).

            ``is_active`` distinguishes current vs ended administrator mandates so
            the frontend can dim/dash the line. Shareholder + participating-interest
            edges have no temporal data — they default to active=True.
            """
            edges.append({
                "source": src, "target": tgt,
                "relationship": rel, "label": label,
                "is_active": is_active,
                "mandate_end": mandate_end,
            })

        # Seed node
        _add_node(cbe, header["name"], "company", 0)

        # BFS frontier — set of CBE numbers to expand at the next depth
        frontier: set[str] = {cbe}

        # Reference date for active-mandate classification.
        today_str = date.today().isoformat()

        for current_depth in range(1, depth + 1):
            if not frontier or len(nodes) >= MAX_DEEP_NETWORK_NODES:
                break

            batch = list(sorted(frontier))
            frontier = set()

            # ── Fetch all relationships for the current batch ──────────
            ph = ",".join(["%s"] * len(batch))

            # 1. Administrators OF these companies. ``is_active`` is true
            #    if ANY matching row has a NULL or future ``mandate_end``,
            #    so a person with both an ended and an ongoing mandate is
            #    still rendered as active. ``last_mandate_end`` is the
            #    latest end-date and is shown in the tooltip when the
            #    mandate has ended.
            admin_rows = fetch_all(
                f"SELECT enterprise_number, name, role, person_type, identifier, "
                f"       BOOL_OR(mandate_end IS NULL OR mandate_end >= %s) AS is_active, "
                f"       MAX(mandate_end) AS last_mandate_end "
                f"FROM administrator WHERE enterprise_number IN ({ph}) "
                f"GROUP BY enterprise_number, name, role, person_type, identifier",
                [today_str] + batch,
            )

            # 2. Companies where these entities serve as administrator (reverse)
            admin_reverse_rows = fetch_all(
                f"SELECT enterprise_number, name, role, person_type, identifier, "
                f"       BOOL_OR(mandate_end IS NULL OR mandate_end >= %s) AS is_active, "
                f"       MAX(mandate_end) AS last_mandate_end "
                f"FROM administrator WHERE identifier IN ({ph}) "
                f"GROUP BY enterprise_number, name, role, person_type, identifier",
                [today_str] + batch,
            )

            # 3. Shareholders OF these companies
            sh_rows = fetch_all(
                f"SELECT DISTINCT enterprise_number, name, identifier, ownership_pct, shareholder_type "
                f"FROM shareholder WHERE enterprise_number IN ({ph})",
                batch,
            )

            # 4. Companies where these entities are shareholders (reverse)
            sh_reverse_rows = fetch_all(
                f"SELECT DISTINCT enterprise_number, name, identifier, ownership_pct, shareholder_type "
                f"FROM shareholder WHERE identifier IN ({ph})",
                batch,
            )

            # 5. Participating interests (subsidiaries) OF these companies
            pi_rows = fetch_all(
                f"SELECT DISTINCT enterprise_number, name, identifier, ownership_pct, country "
                f"FROM participating_interest WHERE enterprise_number IN ({ph})",
                batch,
            )

            # 6. Companies that hold participating interests IN these entities (parent lookup)
            pi_reverse_rows = fetch_all(
                f"SELECT DISTINCT enterprise_number, name, identifier, ownership_pct, country "
                f"FROM participating_interest WHERE identifier IN ({ph})",
                batch,
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
                is_active = bool(row.get("is_active", True))
                _add_edge(nid, ent, "administrator", role_label,
                          is_active=is_active,
                          mandate_end=row.get("last_mandate_end"))

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
                is_active = bool(row.get("is_active", True))
                _add_edge(cbe_id, target_ent, "administrator", role_label,
                          is_active=is_active,
                          mandate_end=row.get("last_mandate_end"))
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
        logger.exception("Deep network query failed for %s", cbe)
        raise HTTPException(status_code=500, detail="Internal server error")
