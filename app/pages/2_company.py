"""Company — search by name or CBE and view full financial profile."""

import os
import sys

import pandas as pd
import streamlit as st
import plotly.graph_objects as go
import networkx as nx
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
from components import topbar, is_favourite, toggle_favourite
from db import get_connection

load_dotenv()

DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "..", "..", "db", "belgian_companies.db"))

st.set_page_config(page_title="Company · Belgian Co DB", layout="wide")

st.markdown("""
<style>
/* Compact company header */
.co-header { padding:8px 0 8px 0; border-bottom:1px solid #e2e8f0; margin-bottom:10px; }
.co-name { font-size:22px; font-weight:800; color:#0f172a; }
.co-tags { font-size:11px; color:#64748b; margin-top:3px; }
.co-tags strong { color:#334155; font-weight:600; }

/* KPI strip */
.kpi-strip { display:flex; gap:6px; margin:8px 0 4px 0; flex-wrap:wrap; }
.kpi-box { flex:1; min-width:90px; background:#f8fafc; border:1px solid #e2e8f0;
    border-radius:8px; padding:8px 10px; text-align:center; }
.kpi-val { font-size:16px; font-weight:700; color:#0f172a; line-height:1.2; }
.kpi-label { font-size:9px; color:#94a3b8; text-transform:uppercase; letter-spacing:.06em; margin-top:1px; }

/* Section titles */
.section-title { font-size:11px; font-weight:700; color:#334155; border-left:3px solid #6366f1;
    padding-left:8px; margin:16px 0 8px 0; text-transform:uppercase; letter-spacing:.04em; }

/* Filing rows */
.filing-row { display:flex; align-items:center; gap:6px; padding:6px 12px;
    border:1px solid #e2e8f0; border-radius:8px; margin-bottom:4px; background:#fafbff; font-size:11px; }
.filing-row a { color:#6366f1; text-decoration:none; font-weight:600; }

/* Tables */
.pnl-table { width:100%; border-collapse:collapse; font-size:11px; }
.pnl-table th { text-align:right; padding:4px 8px; font-weight:600; color:#64748b;
                border-bottom:2px solid #e2e8f0; font-size:10px; white-space:nowrap; }
.pnl-table th:first-child { text-align:left; min-width:160px; }
.pnl-table td { padding:3px 8px; text-align:right; color:#334155; border-bottom:1px solid #f1f5f9; }
.pnl-table td:first-child { text-align:left; color:#0f172a; }
.pnl-table tr.pnl-indent td:first-child { color:#64748b; padding-left:22px; }
.pnl-table tr.pnl-indent td { color:#64748b; }
.pnl-table tr.pnl-subtotal td { font-weight:700; border-bottom:2px solid #e2e8f0; background:#f8fafc; }
.pnl-table tr.pnl-total td { font-weight:800; border-bottom:2px solid #6366f1; background:#eef2ff; color:#4338ca; }
.pnl-table tr.pnl-header td { font-weight:800; background:#1e293b; color:#f8fafc;
    font-size:10px; text-transform:uppercase; letter-spacing:.06em; }
.pnl-table tr.pnl-spacer td { border:none; padding:3px 0; }
.pnl-table tr.pnl-cf-pos td { color:#166534; }
.pnl-table tr.pnl-cf-neg td { color:#991b1b; }

/* Structure tree */
.tree-root { font-size:13px; margin:4px 0 12px 0; }
.tree-section { font-weight:700; color:#334155; font-size:11px; text-transform:uppercase;
    letter-spacing:.05em; margin:10px 0 4px 0; border-left:3px solid #6366f1; padding-left:8px; }
.tree-row { display:flex; align-items:center; gap:8px; padding:5px 10px;
    border:1px solid #e2e8f0; border-radius:7px; margin:2px 0; background:#fafbff; font-size:12px; }
.tree-row:hover { background:#eef2ff; border-color:#c7d2fe; cursor:pointer; }
.tree-name { font-weight:600; color:#0f172a; flex:1; }
.tree-badge { background:#eef2ff; color:#4338ca; padding:1px 6px; border-radius:4px;
    font-size:10px; font-weight:700; white-space:nowrap; }
.tree-meta { color:#64748b; font-size:11px; white-space:nowrap; }

/* Constrain page width for readability */
.main .block-container {
    max-width: 1300px;
    padding-top: 0.5rem;
}
/* Column header for search results */
.sr-header { font-size:10px; font-weight:700; color:#94a3b8; text-transform:uppercase;
    letter-spacing:.05em; padding:2px 4px; }
</style>
""", unsafe_allow_html=True)

topbar(active="Company")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _conn():
    return get_connection()


def fmt_eur(v):
    if pd.isna(v) or v is None:
        return "—"
    v = float(v)
    neg = v < 0
    a = abs(v)
    if a >= 1_000_000_000:
        s = f"€{a/1e9:,.2f}B"
    elif a >= 1_000_000:
        s = f"€{a/1e6:,.1f}M"
    elif a >= 1_000:
        s = f"€{a/1e3:,.0f}K"
    else:
        s = f"€{a:,.0f}"
    return f"-{s}" if neg else s


def fmt_pct(v):
    return f"{float(v):.1f}%" if pd.notna(v) else "—"


def fmt_cbe(n):
    n = str(n).zfill(10)
    return f"{n[:4]}.{n[4:7]}.{n[7:]}"


ROLE_LABELS = {
    "fct:m10": "Director", "fct:m11": "Managing director",
    "fct:m12": "Chairman", "fct:m13": "Administrator",
    "fct:m14": "Secretary", "fct:m15": "Treasurer",
    "fct:m20": "Statutory auditor", "fct:m30": "Liquidator",
    "fct:m40": "Daily management",
}

# ---------------------------------------------------------------------------
# P&L rubric codes
# ---------------------------------------------------------------------------

PNL_LINES = [
    ("Revenue",                  "70",     "row"),
    ("Other operating income",   "74",     "row"),
    ("Total operating income",   "70/76A", "subtotal"),
    ("s1",                       None,     "spacer"),
    ("Cost of goods sold",       "60",     "row"),
    ("Services & misc",          "61",     "row"),
    ("Personnel costs",          "62",     "row"),
    ("D&A",                      "630",    "row"),
    ("Write-downs",              "631/4",  "row"),
    ("Provisions",               "635/8",  "row"),
    ("Other charges",            "640/8",  "row"),
    ("Total operating charges",  "60/66A", "subtotal"),
    ("s2",                       None,     "spacer"),
    ("EBIT",                     "9901",   "subtotal"),
    ("s3",                       None,     "spacer"),
    ("Financial income",         "75",     "row"),
    ("Financial charges",        "65",     "row"),
    ("Ordinary profit",          "9902",   "subtotal"),
    ("s4",                       None,     "spacer"),
    ("Extraordinary income",     "76",     "row"),
    ("Extraordinary charges",    "66",     "row"),
    ("Profit before tax",        "9903",   "subtotal"),
    ("Taxes",                    "67/77",  "row"),
    ("Net profit",               "9904",   "total"),
]
PNL_CODES = [c for _, c, _ in PNL_LINES if c]

# ---------------------------------------------------------------------------
# Balance sheet rubric codes
# ---------------------------------------------------------------------------

BS_LINES = [
    ("ASSETS",                    None,    "header"),
    ("Fixed assets",              "20/28", "row"),
    ("  Intangible assets",       "21",    "indent"),
    ("  Tangible assets",         "22",    "indent"),
    ("  Financial assets",        "28",    "indent"),
    ("Current assets",            "29/58", "row"),
    ("  Inventories",             "3",     "indent"),
    ("  Trade receivables",       "41",    "indent"),
    ("  Cash & equivalents",      "54/58", "indent"),
    ("Total assets",              "20/58", "total"),
    ("spacer_bs",                 None,    "spacer"),
    ("LIABILITIES & EQUITY",      None,    "header"),
    ("Equity",                    "10/15", "row"),
    ("LT provisions",             "16",    "row"),
    ("LT financial debts",        "17",    "row"),
    ("ST financial debts",        "43",    "indent"),
    ("Trade payables",            "44",    "indent"),
    ("Total equity & liabilities","10/49", "total"),
]
BS_CODES = [c for _, c, _ in BS_LINES if c]

# Cashflow helper codes (subset of above)
CF_CODES = ["9904", "630", "631/4", "635/8", "3", "41", "44", "22"]

ALL_RUBRIC_CODES = list(dict.fromkeys(PNL_CODES + BS_CODES))  # deduplicated, order preserved


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

@st.cache_data(ttl=30)
def search_companies(query: str):
    conn = _conn()
    query = query.strip()
    cbe_clean = query.replace(".", "").replace(" ", "")
    base_sql = """
        SELECT
            e.enterprise_number,
            COALESCE(d.denomination, e.enterprise_number) AS name,
            e.status,
            COALESCE(c_jf.description, e.juridical_form)  AS jf_label,
            a.municipality_nl AS city,
            COALESCE(c_n.description, act.nace_code)       AS sector,
            e.start_date,
            fl.revenue,
            fl.ebitda,
            CASE WHEN fl.revenue > 0 THEN ROUND((fl.ebitda / fl.revenue * 100)::numeric, 1) END AS ebitda_margin_pct,
            fl.fte_total,
            fl.fiscal_year
        FROM enterprise e
        LEFT JOIN denomination d  ON d.entity_number   = e.enterprise_number
             AND d.type_of_denomination = '001' AND d.language IN ('2','1')
        LEFT JOIN address a       ON a.entity_number   = e.enterprise_number AND a.type_of_address = 'REGO'
        LEFT JOIN activity act    ON act.entity_number = e.enterprise_number AND act.classification = 'MAIN'
        LEFT JOIN code c_jf       ON c_jf.category = 'JuridicalForm'
             AND c_jf.code = e.juridical_form AND c_jf.language = 'NL'
        LEFT JOIN code c_n        ON c_n.category IN ('Nace2025','Nace2008')
             AND c_n.code = act.nace_code AND c_n.language = 'NL'
        LEFT JOIN financial_latest fl ON fl.enterprise_number = e.enterprise_number
    """
    cur = conn.cursor()
    group_by = """GROUP BY e.enterprise_number, d.denomination, e.status,
            c_jf.description, e.juridical_form, a.municipality_nl,
            c_n.description, act.nace_code, e.start_date,
            fl.revenue, fl.ebitda, fl.fte_total, fl.fiscal_year"""
    if cbe_clean.isdigit():
        cur.execute(
            base_sql + f" WHERE e.enterprise_number LIKE %s {group_by} LIMIT 20",
            (f"{cbe_clean}%",)
        )
    else:
        cur.execute(
            base_sql + f"""
            WHERE d.denomination ILIKE %s AND d.type_of_denomination = '001'
            {group_by} ORDER BY d.denomination LIMIT 20
            """,
            (f"%{query}%",)
        )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


@st.cache_data(ttl=60)
def load_company_detail(cbe: str):
    conn = _conn()

    cur = conn.cursor()
    cur.execute("""
        SELECT e.enterprise_number, e.status, e.start_date,
               COALESCE(c_jf.description, e.juridical_form) AS jf_label,
               d.denomination AS name, a.zipcode, a.municipality_nl, a.street_nl, a.house_number,
               act.nace_code, COALESCE(c_n.description, act.nace_code) AS nace_label
        FROM enterprise e
        LEFT JOIN denomination d ON d.entity_number = e.enterprise_number
             AND d.type_of_denomination = '001' AND d.language IN ('2','1')
        LEFT JOIN address a ON a.entity_number = e.enterprise_number AND a.type_of_address = 'REGO'
        LEFT JOIN activity act ON act.entity_number = e.enterprise_number AND act.classification = 'MAIN'
        LEFT JOIN code c_jf ON c_jf.category = 'JuridicalForm' AND c_jf.code = e.juridical_form AND c_jf.language = 'NL'
        LEFT JOIN code c_n ON c_n.category IN ('Nace2025','Nace2008') AND c_n.code = act.nace_code AND c_n.language = 'NL'
        WHERE e.enterprise_number = %s LIMIT 1
    """, (cbe,))
    header = cur.fetchone()
    cur.close()

    hist = pd.read_sql_query("""
        SELECT fiscal_year, deposit_key, filing_model,
               revenue, ebit, da, ebitda, net_profit,
               equity, lt_financial_debt, st_financial_debt, cash, total_assets,
               fixed_assets, inventories, trade_receivables, trade_payables,
               financial_charges, fte_total, personnel_costs,
               CASE WHEN revenue > 0 THEN ROUND((ebitda / revenue * 100)::numeric, 1) END AS "ebitda_margin_pct"
        FROM financial_summary WHERE enterprise_number = %s ORDER BY fiscal_year
    """, conn, params=(cbe,))

    # Load all rubric codes at once (P&L + Balance sheet)
    rubric_df = pd.DataFrame()
    if not hist.empty:
        placeholders = ",".join(["%s"] * len(ALL_RUBRIC_CODES))
        rubric_raw = pd.read_sql_query(f"""
            SELECT fiscal_year, rubric_code, value FROM financial_data
            WHERE enterprise_number = %s AND period = 'N' AND rubric_code IN ({placeholders})
        """, conn, params=[cbe] + ALL_RUBRIC_CODES)
        if not rubric_raw.empty:
            rubric_df = rubric_raw.pivot_table(index="rubric_code", columns="fiscal_year",
                                               values="value", aggfunc="first")

    admins = pd.read_sql_query(
        "SELECT * FROM administrator WHERE enterprise_number = %s ORDER BY mandate_start DESC",
        conn, params=(cbe,))
    pis = pd.read_sql_query(
        "SELECT * FROM participating_interest WHERE enterprise_number = %s ORDER BY name",
        conn, params=(cbe,))
    shareholders = pd.read_sql_query(
        "SELECT * FROM shareholder WHERE enterprise_number = %s ORDER BY name",
        conn, params=(cbe,))
    sb_pubs = pd.read_sql_query(
        "SELECT pub_date, pub_type, reference, pdf_url FROM staatsblad_publication "
        "WHERE enterprise_number = %s ORDER BY pub_date DESC",
        conn, params=(cbe,))

    conn.close()
    return header, hist, rubric_df, admins, pis, shareholders, sb_pubs


# ---------------------------------------------------------------------------
# HELPERS: multi-level network + group financials
# ---------------------------------------------------------------------------

def _clean_cbe(identifier):
    """Strip dots/spaces from identifier, return 10-digit CBE or None."""
    if not identifier:
        return None
    c = str(identifier).replace(".", "").replace(" ", "").strip()
    return c if c.isdigit() and len(c) == 10 else None


@st.cache_data(ttl=60)
def fetch_connections(cbes: tuple):
    """Batch-fetch subsidiaries and shareholders for a set of CBEs."""
    if not cbes:
        return [], []
    conn = get_connection()
    ph = ",".join(["%s"] * len(cbes))
    subs = pd.read_sql_query(
        f"SELECT DISTINCT enterprise_number, name, identifier, ownership_pct, country "
        f"FROM participating_interest WHERE enterprise_number IN ({ph})",
        conn, params=list(cbes))
    shs = pd.read_sql_query(
        f"SELECT DISTINCT enterprise_number, name, identifier, ownership_pct, shareholder_type "
        f"FROM shareholder WHERE enterprise_number IN ({ph})",
        conn, params=list(cbes))
    conn.close()
    return subs.to_dict("records"), shs.to_dict("records")


@st.cache_data(ttl=60)
def fetch_entity_names(cbes: tuple):
    """Batch-resolve CBE numbers to company names."""
    if not cbes:
        return {}
    conn = get_connection()
    ph = ",".join(["%s"] * len(cbes))
    cur = conn.cursor()
    cur.execute(
        f"SELECT entity_number, denomination FROM denomination "
        f"WHERE entity_number IN ({ph}) AND type_of_denomination = '001' "
        f"GROUP BY entity_number", list(cbes))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return {r[0]: r[1] for r in rows}


MAX_NETWORK_NODES = 200

# Color palettes by depth
SH_COLORS = {0: "#22c55e", 1: "#22c55e", 2: "#86efac", 3: "#bbf7d0"}
PI_COLORS = {0: "#f97316", 1: "#f97316", 2: "#fdba74", 3: "#fed7aa"}
SH_INDIV_COLORS = {0: "#86efac", 1: "#86efac", 2: "#bbf7d0", 3: "#d9f99d"}
ADMIN_COLOR = "#94a3b8"
ADMIN_LEGAL_COLOR = "#06b6d4"


def bfs_build_graph(central_cbe, central_name, shareholders_df, pis_df, admins_df, max_depth=1):
    """Build a multi-level network graph via BFS traversal."""
    from collections import deque

    G = nx.Graph()
    nav_options = {}  # cbe -> label
    visited = {central_cbe}
    truncated = False

    # Central node
    G.add_node(central_cbe, label=central_name, ntype="central", size=35,
               color="#6366f1", cbe=central_cbe, depth=0,
               hover=f"<b>🏢 {central_name}</b><br>CBE: {fmt_cbe(central_cbe)}")

    # --- Depth 0: process already-loaded DataFrames ---
    frontier = set()

    # Shareholders
    if not shareholders_df.empty:
        for i, (_, sh) in enumerate(shareholders_df.drop_duplicates(subset=["name"]).iterrows()):
            cbe_clean = _clean_cbe(sh.get("identifier") or sh.get("enterprise_number_shareholder"))
            is_indiv = sh.get("shareholder_type") == "individual"
            sname = sh.get("name") or "Unknown"
            pct = sh.get("ownership_pct")
            nid = cbe_clean if cbe_clean else f"sh_{i}"

            node_color = SH_INDIV_COLORS[0] if is_indiv else SH_COLORS[0]
            node_size = max(14, min(28, int(18 + (pct or 0) / 10))) if not is_indiv else 14
            icon = "👤" if is_indiv else "🏢"
            hover = f"<b>{icon} {sname}</b>"
            if pct and pd.notna(pct):
                hover += f"<br>Ownership: {pct:.1f}%"
            if cbe_clean:
                hover += f"<br>CBE: {fmt_cbe(cbe_clean)}"
                nav_options[cbe_clean] = sname
                if cbe_clean not in visited:
                    frontier.add(cbe_clean)

            if nid not in G:
                G.add_node(nid, label=sname, ntype="shareholder", size=node_size,
                           color=node_color, cbe=cbe_clean, depth=1, hover=hover, indiv=is_indiv)
            edge_label = f"{pct:.0f}%" if pct and pd.notna(pct) else ""
            G.add_edge(nid, central_cbe, etype="shareholder", label=edge_label,
                       color=SH_COLORS[0], dash="dash", width=1.5)

    # Subsidiaries
    if not pis_df.empty:
        for i, (_, pi) in enumerate(pis_df.drop_duplicates(subset=["name"]).iterrows()):
            cbe_clean = _clean_cbe(pi.get("identifier"))
            pname = pi.get("name") or "Unknown"
            pct = pi.get("ownership_pct")
            country = pi.get("country") or ""
            eq_val = pi.get("equity_value")
            nid = cbe_clean if cbe_clean else f"pi_{i}"

            node_size = max(14, min(28, int(18 + (pct or 0) / 10)))
            hover = f"<b>🏢 {pname}</b>"
            if pct and pd.notna(pct):
                hover += f"<br>Ownership: {pct:.0f}%"
            if country:
                hover += f"<br>Country: {country}"
            if eq_val and pd.notna(eq_val):
                hover += f"<br>Equity: {fmt_eur(eq_val)}"
            if cbe_clean:
                hover += f"<br>CBE: {fmt_cbe(cbe_clean)}"
                nav_options[cbe_clean] = pname
                if cbe_clean not in visited:
                    frontier.add(cbe_clean)

            if nid not in G:
                G.add_node(nid, label=pname, ntype="subsidiary", size=node_size,
                           color=PI_COLORS[0], cbe=cbe_clean, depth=1, hover=hover)
            edge_label = f"{pct:.0f}%" if pct and pd.notna(pct) else ""
            G.add_edge(central_cbe, nid, etype="subsidiary", label=edge_label,
                       color=PI_COLORS[0], dash="solid", width=1.5)

    # Admins (only for central company)
    if not admins_df.empty:
        for i, (_, ad) in enumerate(admins_df.drop_duplicates(subset=["name", "role"]).iterrows()):
            role = ROLE_LABELS.get(ad.get("role", ""), ad.get("role", "") or "Administrator")
            cbe_clean = _clean_cbe(ad.get("identifier"))
            aname = ad.get("name") or "Unknown"
            is_legal = ad.get("person_type") == "legal"
            nid = cbe_clean if cbe_clean else f"ad_{i}"

            node_color = ADMIN_LEGAL_COLOR if is_legal else ADMIN_COLOR
            node_size = 14 if is_legal else 12
            icon = "🏢" if is_legal else "👤"
            hover = f"<b>{icon} {aname}</b><br>Role: {role}"
            if cbe_clean:
                hover += f"<br>CBE: {fmt_cbe(cbe_clean)}"
                nav_options[cbe_clean] = aname

            if nid not in G:
                G.add_node(nid, label=aname, ntype="admin", size=node_size,
                           color=node_color, cbe=cbe_clean, depth=1, hover=hover)
            G.add_edge(nid, central_cbe, etype="admin", label=role,
                       color=ADMIN_COLOR, dash="dot", width=1.5)

    visited.update(frontier)

    # --- Depths 1+: BFS expansion ---
    queue = deque(frontier)
    current_depth = 1

    while queue and current_depth < max_depth:
        next_depth_cbes = set()
        batch_cbes = set()
        while queue:
            batch_cbes.add(queue.popleft())

        if not batch_cbes or len(G.nodes()) >= MAX_NETWORK_NODES:
            if len(G.nodes()) >= MAX_NETWORK_NODES:
                truncated = True
            break

        sub_recs, sh_recs = fetch_connections(tuple(sorted(batch_cbes)))
        # Resolve names for newly discovered CBEs
        new_cbes_needing_names = set()
        for rec in sub_recs + sh_recs:
            c = _clean_cbe(rec.get("identifier"))
            if c and c not in G:
                new_cbes_needing_names.add(c)
        name_map = fetch_entity_names(tuple(sorted(new_cbes_needing_names))) if new_cbes_needing_names else {}

        d = current_depth + 1  # depth of newly discovered nodes
        sh_color = SH_COLORS.get(d, SH_COLORS[3])
        pi_color = PI_COLORS.get(d, PI_COLORS[3])
        edge_w = max(0.8, 1.5 - d * 0.3)
        node_max_size = max(10, 28 - d * 6)
        node_min_size = max(8, 14 - d * 3)

        # Process shareholders of expanded entities
        seen_sh_edges = set()
        for rec in sh_recs:
            source_cbe = rec["enterprise_number"]
            target_cbe = _clean_cbe(rec.get("identifier"))
            sname = rec.get("name") or "Unknown"
            pct = rec.get("ownership_pct")
            is_indiv = rec.get("shareholder_type") == "individual"

            nid = target_cbe if target_cbe else f"sh_d{d}_{sname[:10]}"
            edge_key = (nid, source_cbe)
            if edge_key in seen_sh_edges:
                continue
            seen_sh_edges.add(edge_key)

            if len(G.nodes()) >= MAX_NETWORK_NODES:
                truncated = True
                break

            if nid not in G:
                label = name_map.get(target_cbe, sname) if target_cbe else sname
                icon = "👤" if is_indiv else "🏢"
                hover = f"<b>{icon} {label}</b>"
                if pct and pd.notna(pct):
                    hover += f"<br>Ownership: {pct:.1f}%"
                if target_cbe:
                    hover += f"<br>CBE: {fmt_cbe(target_cbe)}"
                    nav_options[target_cbe] = label
                nc = SH_INDIV_COLORS.get(d, SH_INDIV_COLORS[3]) if is_indiv else sh_color
                ns = node_min_size if is_indiv else min(node_max_size, max(node_min_size, int(node_min_size + (pct or 0) / 10)))
                G.add_node(nid, label=label, ntype="shareholder", size=ns,
                           color=nc, cbe=target_cbe, depth=d, hover=hover, indiv=is_indiv)

            if not G.has_edge(nid, source_cbe):
                edge_label = f"{pct:.0f}%" if pct and pd.notna(pct) else ""
                G.add_edge(nid, source_cbe, etype="shareholder", label=edge_label,
                           color=sh_color, dash="dash", width=edge_w)

            if target_cbe and target_cbe not in visited:
                next_depth_cbes.add(target_cbe)

        # Process subsidiaries of expanded entities
        seen_pi_edges = set()
        for rec in sub_recs:
            source_cbe = rec["enterprise_number"]
            target_cbe = _clean_cbe(rec.get("identifier"))
            pname = rec.get("name") or "Unknown"
            pct = rec.get("ownership_pct")
            country = rec.get("country") or ""

            nid = target_cbe if target_cbe else f"pi_d{d}_{pname[:10]}"
            edge_key = (source_cbe, nid)
            if edge_key in seen_pi_edges:
                continue
            seen_pi_edges.add(edge_key)

            if len(G.nodes()) >= MAX_NETWORK_NODES:
                truncated = True
                break

            if nid not in G:
                label = name_map.get(target_cbe, pname) if target_cbe else pname
                hover = f"<b>🏢 {label}</b>"
                if pct and pd.notna(pct):
                    hover += f"<br>Ownership: {pct:.0f}%"
                if country:
                    hover += f"<br>Country: {country}"
                if target_cbe:
                    hover += f"<br>CBE: {fmt_cbe(target_cbe)}"
                    nav_options[target_cbe] = label
                ns = min(node_max_size, max(node_min_size, int(node_min_size + (pct or 0) / 10)))
                G.add_node(nid, label=label, ntype="subsidiary", size=ns,
                           color=pi_color, cbe=target_cbe, depth=d, hover=hover)

            if not G.has_edge(source_cbe, nid):
                edge_label = f"{pct:.0f}%" if pct and pd.notna(pct) else ""
                G.add_edge(source_cbe, nid, etype="subsidiary", label=edge_label,
                           color=pi_color, dash="solid", width=edge_w)

            if target_cbe and target_cbe not in visited:
                next_depth_cbes.add(target_cbe)

        visited.update(next_depth_cbes)
        for c in next_depth_cbes:
            queue.append(c)
        current_depth += 1

    return G, nav_options, truncated


@st.cache_data(ttl=60)
def load_group_financials(parent_cbe):
    """Load consolidated group financials for parent + subsidiaries."""
    conn = get_connection()

    # Get subsidiary CBEs
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT identifier FROM participating_interest "
        "WHERE enterprise_number = %s AND identifier IS NOT NULL",
        (parent_cbe,))
    pi_rows = cur.fetchall()
    cur.close()
    sub_cbes = []
    for (ident,) in pi_rows:
        c = _clean_cbe(ident)
        if c and c != parent_cbe:
            sub_cbes.append(c)
    sub_cbes = list(set(sub_cbes))
    total_subs = len(sub_cbes)

    if not sub_cbes:
        conn.close()
        return pd.DataFrame(), pd.DataFrame(), 0, 0

    all_cbes = [parent_cbe] + sub_cbes
    ph = ",".join(["%s"] * len(all_cbes))

    # Batch query financials
    fin_df = pd.read_sql_query(
        f"SELECT enterprise_number, fiscal_year, revenue, ebitda, ebit, net_profit, "
        f"equity, total_assets, fte_total, personnel_costs, da "
        f"FROM financial_summary WHERE enterprise_number IN ({ph}) ORDER BY fiscal_year",
        conn, params=all_cbes)

    # Resolve names
    cur = conn.cursor()
    cur.execute(
        f"SELECT entity_number, denomination FROM denomination "
        f"WHERE entity_number IN ({ph}) AND type_of_denomination = '001' "
        f"GROUP BY entity_number", all_cbes)
    name_rows = cur.fetchall()
    cur.close()
    conn.close()

    name_map = {r[0]: r[1] for r in name_rows}
    subs_with_data = len(set(fin_df["enterprise_number"].unique()) - {parent_cbe})

    if fin_df.empty:
        return pd.DataFrame(), pd.DataFrame(), total_subs, 0

    # Detail: latest year per company
    latest = fin_df.sort_values("fiscal_year").groupby("enterprise_number").last().reset_index()
    latest["name"] = latest["enterprise_number"].map(lambda c: name_map.get(c, fmt_cbe(c)))
    latest["is_parent"] = latest["enterprise_number"] == parent_cbe
    latest["ebitda_margin"] = latest.apply(
        lambda r: round(r["ebitda"] / r["revenue"] * 100, 1)
        if pd.notna(r.get("ebitda")) and pd.notna(r.get("revenue")) and r["revenue"] > 0
        else None, axis=1)
    latest = latest.sort_values(["is_parent", "revenue"], ascending=[False, False])

    # Yearly aggregation
    yearly = fin_df.groupby("fiscal_year").agg(
        revenue=("revenue", "sum"),
        ebitda=("ebitda", "sum"),
        ebit=("ebit", "sum"),
        net_profit=("net_profit", "sum"),
        equity=("equity", "sum"),
        total_assets=("total_assets", "sum"),
        fte_total=("fte_total", "sum"),
        personnel_costs=("personnel_costs", "sum"),
        company_count=("enterprise_number", "nunique"),
    ).reset_index()
    yearly["ebitda_margin"] = yearly.apply(
        lambda r: round(r["ebitda"] / r["revenue"] * 100, 1)
        if pd.notna(r.get("ebitda")) and pd.notna(r.get("revenue")) and r["revenue"] > 0
        else None, axis=1)
    yearly = yearly.sort_values("fiscal_year")

    return latest, yearly, total_subs, subs_with_data


def navigate_to(cbe):
    """Navigate to a company in-page — no new browser window."""
    st.session_state["company_cbe"] = str(cbe).zfill(10)
    st.session_state["_clear_search"] = True
    st.rerun()


# ---------------------------------------------------------------------------
# SEARCH BAR — always visible at top
# ---------------------------------------------------------------------------

# Delete (not set!) the widget key BEFORE rendering — safe in all Streamlit versions
if st.session_state.pop("_clear_search", False):
    st.session_state.pop("company_search_q", None)

# Initialise from URL param (?cbe=...)
if "company_cbe" not in st.session_state:
    qp = st.query_params.get("cbe", "")
    if qp:
        st.session_state["company_cbe"] = str(qp).zfill(10)

col_search, col_clear = st.columns([9, 1])
query = col_search.text_input(
    "Search", placeholder="🔍  Company name or CBE number…",
    label_visibility="collapsed",
    key="company_search_q",
)
if col_clear.button("✕ Clear", use_container_width=True):
    st.session_state.pop("company_cbe", None)
    st.session_state.pop("company_search_q", None)
    st.rerun()

selected_cbe = st.session_state.get("company_cbe", "")

# ---------------------------------------------------------------------------
# SEARCH RESULTS
# ---------------------------------------------------------------------------

# Show search results ONLY when there's no company already selected
if query and query.strip() and not selected_cbe:
    results = search_companies(query.strip())
    if not results:
        st.info("No companies found for that query.")
    else:
        # Column headers
        h1, h2, h3, h4, h5, h6 = st.columns([4, 2, 3, 1.5, 1.5, 1])
        h1.markdown('<span class="sr-header">Company</span>', unsafe_allow_html=True)
        h2.markdown('<span class="sr-header">City</span>', unsafe_allow_html=True)
        h3.markdown('<span class="sr-header">Sector (NACE)</span>', unsafe_allow_html=True)
        h4.markdown('<span class="sr-header">Revenue</span>', unsafe_allow_html=True)
        h5.markdown('<span class="sr-header">EBITDA margin</span>', unsafe_allow_html=True)
        h6.markdown('<span class="sr-header">FTE</span>', unsafe_allow_html=True)

        cols_raw = ["_cbe", "Name", "_status", "Type", "City", "Sector",
                    "_start", "_revenue", "_ebitda", "_margin", "_fte", "_fy"]
        df_res = pd.DataFrame(results, columns=cols_raw)

        for _, row in df_res.iterrows():
            cbe_val = str(row["_cbe"]).zfill(10)
            name    = (row["Name"] or fmt_cbe(cbe_val))[:40]
            city    = (row["City"] or "—")[:22]
            sector  = (row["Sector"] or "—")[:45]
            rev     = fmt_eur(row["_revenue"])
            margin  = (f"{row['_margin']:.1f}%" if pd.notna(row["_margin"]) else "—")
            fte     = (f"{int(row['_fte']):,}" if pd.notna(row["_fte"]) else "—")
            fy      = (f" FY{int(row['_fy'])}" if pd.notna(row.get("_fy")) else "")
            dot     = "🟢" if row["_status"] == "AC" else "🔴"

            c1, c2, c3, c4, c5, c6 = st.columns([4, 2, 3, 1.5, 1.5, 1])
            with c1:
                if st.button(f"{dot} **{name}**", key=f"res_{cbe_val}",
                             use_container_width=True):
                    navigate_to(cbe_val)
            c2.caption(city)
            c3.caption(sector)
            c4.caption(rev + fy)
            c5.caption(margin)
            c6.caption(fte)

    st.stop()

# ---------------------------------------------------------------------------
# PLACEHOLDER when nothing selected
# ---------------------------------------------------------------------------

if not selected_cbe:
    st.markdown(
        "<div style='color:#94a3b8;font-size:13px;margin-top:40px;text-align:center'>"
        "🔍  Search for a company above to view its full profile."
        "</div>",
        unsafe_allow_html=True,
    )
    st.stop()

# ---------------------------------------------------------------------------
# COMPANY DETAIL
# ---------------------------------------------------------------------------

header, hist, rubric_df, admins, pis, shareholders, sb_pubs = load_company_detail(selected_cbe)

if not header:
    st.warning(f"CBE {selected_cbe} not found in the KBO registry.")
    st.stop()

ent_num, status, start_date, jf_label, name, zipcode, muni, street, house, nace, nace_label = header

# Compact header
addr_parts = [p for p in [street, house] if p]
addr_city  = f"{zipcode or ''} {muni or ''}".strip()
if addr_city:
    addr_parts.append(addr_city)
addr_str = ", ".join(addr_parts) or "—"

status_badge = (
    '<span style="background:#dcfce7;color:#166534;padding:1px 8px;border-radius:10px;'
    'font-size:10px;font-weight:700;margin-left:8px">● Active</span>'
    if status == "AC" else
    f'<span style="background:#fee2e2;color:#991b1b;padding:1px 8px;border-radius:10px;'
    f'font-size:10px;font-weight:700;margin-left:8px">● {status}</span>'
)

tags = " · ".join(t for t in [jf_label, f"Est. {start_date[:4]}" if start_date else None] if t)
nace_str = " · ".join(t for t in [nace, nace_label] if t)

st.markdown(f"""
<div class="co-header">
  <div class="co-name">{name or fmt_cbe(selected_cbe)}{status_badge}</div>
  <div class="co-tags">
    <strong>{fmt_cbe(selected_cbe)}</strong>
    {"&nbsp;·&nbsp;" + tags if tags else ""}
    {"&nbsp;·&nbsp;📍 " + addr_str if addr_str != "—" else ""}
  </div>
  {"<div class='co-tags' style='margin-top:1px'>🏭 " + nace_str + "</div>" if nace_str else ""}
</div>
""", unsafe_allow_html=True)

# Favourite toggle
_is_fav = is_favourite(selected_cbe)
_fav_label = "⭐ Favourited" if _is_fav else "☆ Add to favourites"
fav_col, _ = st.columns([2, 8])
with fav_col:
    if st.button(_fav_label, key="fav_toggle", type="primary" if _is_fav else "secondary"):
        toggle_favourite(selected_cbe)
        st.rerun()

# KPI strip — latest year
if not hist.empty:
    latest = hist.iloc[-1]
    kpis = [
        (fmt_eur(latest.get("revenue")),          "Revenue"),
        (fmt_eur(latest.get("ebitda")),            "EBITDA"),
        (fmt_pct(latest.get("ebitda_margin_pct")), "Margin"),
        (fmt_eur(latest.get("ebit")),              "EBIT"),
        (fmt_eur(latest.get("net_profit")),        "Net profit"),
        (fmt_eur(latest.get("equity")),            "Equity"),
        (fmt_eur(latest.get("lt_financial_debt")), "LT Debt"),
        (fmt_eur(latest.get("cash")),              "Cash"),
        (f"{latest['fte_total']:,.0f}" if pd.notna(latest.get("fte_total")) else "—", "FTE"),
    ]
    kpi_html = "".join(
        f'<div class="kpi-box"><div class="kpi-val">{v}</div>'
        f'<div class="kpi-label">{l}</div></div>'
        for v, l in kpis
    )
    st.markdown(f'<div class="kpi-strip">{kpi_html}</div>', unsafe_allow_html=True)
    st.caption(
        f"Latest: FY{int(latest['fiscal_year'])}  ·  Model: {latest.get('filing_model','?')}"
    )

# ---------------------------------------------------------------------------
# TABS
# ---------------------------------------------------------------------------

t_fin, t_bs, t_cf, t_trend, t_struct, t_group, t_network, t_legal = st.tabs([
    "💶 P&L", "🏦 Balance sheet", "💸 Cash flow", "📈 Trend", "🏢 Structure", "🏗 Group", "🕸 Network", "📜 Publications"
])

# Rubric & hist helper functions available to all tabs
def _get(code, fy):
    """Get a rubric value for a specific fiscal year from the pivoted rubric_df."""
    if not rubric_df.empty and code in rubric_df.index and fy in rubric_df.columns:
        v = rubric_df.at[code, fy]
        return float(v) if pd.notna(v) else None
    return None

def _hist_val(col, fy):
    """Get a financial_summary column value for a specific fiscal year."""
    r2 = hist[hist["fiscal_year"] == fy]
    if r2.empty:
        return None
    v = r2.iloc[0].get(col)
    return float(v) if pd.notna(v) else None


# ── Helper: render a rubric table ────────────────────────────────────────────

def _rubric_table(line_defs, rubric_df, years):
    """Render an HTML table from line_defs using pivoted rubric_df."""
    if rubric_df.empty:
        return None
    yr_cols = [y for y in sorted(rubric_df.columns, reverse=True) if y in years or not years]
    h = "<tr><th>Line item</th>" + "".join(f"<th>FY {int(y)}</th>" for y in yr_cols) + "</tr>"
    r = ""
    for label, code, style in line_defs:
        if style == "spacer":
            r += '<tr class="pnl-spacer"><td></td>' + "<td></td>" * len(yr_cols) + "</tr>"
            continue
        if style == "header":
            r += f'<tr class="pnl-header"><td>{label}</td>' + "".join(f"<td></td>" for _ in yr_cols) + "</tr>"
            continue
        css_map = {"total": "pnl-total", "subtotal": "pnl-subtotal", "indent": "pnl-indent"}
        css = f' class="{css_map.get(style, "")}"' if style in css_map else ""
        cells = ""
        has = False
        for y in yr_cols:
            val = rubric_df.at[code, y] if (code in rubric_df.index and y in rubric_df.columns) else None
            if pd.notna(val):
                has = True
                cells += f"<td>{fmt_eur(val)}</td>"
            else:
                cells += "<td>—</td>"
        if has or style in ("total", "subtotal", "header"):
            r += f"<tr{css}><td>{label}</td>{cells}</tr>"
    if not r:
        return None
    return f'<table class="pnl-table">{h}{r}</table>'


# ── P&L tab ──────────────────────────────────────────────────────────────────
with t_fin:
    if hist.empty:
        st.info("No financial data loaded for this company yet.")
        st.info("Use the [DataSnoop web app](https://datasnoop.be) to load financials for this company.")
    else:
        # History summary table
        st.markdown('<div class="section-title">Key financials by year</div>', unsafe_allow_html=True)
        hist_show = hist[["fiscal_year", "revenue", "ebit", "ebitda", "ebitda_margin_pct",
                           "net_profit", "equity", "lt_financial_debt", "cash", "fte_total"]].copy()
        hist_show.columns = ["FY", "Revenue", "EBIT", "EBITDA", "Margin %",
                             "Net profit", "Equity", "LT Debt", "Cash", "FTE"]
        for col in ["Revenue", "EBIT", "EBITDA", "Net profit", "Equity", "LT Debt", "Cash"]:
            hist_show[col] = hist_show[col].apply(fmt_eur)
        hist_show["Margin %"] = hist_show["Margin %"].apply(fmt_pct)
        hist_show["FTE"] = hist_show["FTE"].apply(lambda v: f"{v:,.0f}" if pd.notna(v) else "—")
        hist_show["FY"] = hist_show["FY"].astype(int)
        st.dataframe(hist_show.sort_values("FY", ascending=False), use_container_width=True, hide_index=True)

        # Full P&L
        if not rubric_df.empty:
            st.markdown('<div class="section-title">Full income statement</div>', unsafe_allow_html=True)
            years = sorted(rubric_df.columns, reverse=True)
            tbl = _rubric_table(PNL_LINES, rubric_df, years)
            if tbl:
                st.markdown(tbl, unsafe_allow_html=True)

        # Filing links
        if "deposit_key" in hist.columns:
            st.markdown('<div class="section-title">NBB filings</div>', unsafe_allow_html=True)
            for _, row in hist.sort_values("fiscal_year", ascending=False).iterrows():
                dk = row.get("deposit_key")
                if dk:
                    url = f"https://ws.cbso.nbb.be/authentic/deposit/{dk}/accountingData"
                    model = row.get("filing_model", "")
                    badge = f'<span style="background:#eef2ff;color:#4338ca;padding:1px 6px;border-radius:4px;font-size:10px;font-weight:700">{model}</span>' if model else ""
                    st.markdown(
                        f'<div class="filing-row">📄 <strong>FY{int(row.get("fiscal_year","?"))}</strong>'
                        f'&nbsp;{badge}&nbsp;'
                        f'<a href="{url}" target="_blank">View filing ↗</a></div>',
                        unsafe_allow_html=True)


# ── Balance sheet tab ────────────────────────────────────────────────────────
with t_bs:
    if hist.empty:
        st.info("No financial data loaded. Use the P&L tab to load financials.")
    else:
        # Detailed balance sheet from rubric codes (if available)
        if not rubric_df.empty:
            years = sorted(rubric_df.columns, reverse=True)
            st.markdown('<div class="section-title">Balance sheet</div>', unsafe_allow_html=True)
            tbl = _rubric_table(BS_LINES, rubric_df, years)
            if tbl:
                st.markdown(tbl, unsafe_allow_html=True)

        # Summary from financial_summary table (always shown)
        st.markdown('<div class="section-title">Summary (from filing metadata)</div>', unsafe_allow_html=True)
        bs_show = hist[["fiscal_year", "total_assets", "equity", "lt_financial_debt", "st_financial_debt", "cash"]].copy()
        bs_show.columns = ["FY", "Total assets", "Equity", "LT Debt", "ST Debt", "Cash"]
        for col in ["Total assets", "Equity", "LT Debt", "ST Debt", "Cash"]:
            bs_show[col] = bs_show[col].apply(fmt_eur)
        bs_show["FY"] = bs_show["FY"].astype(int)
        st.dataframe(bs_show.sort_values("FY", ascending=False), use_container_width=True, hide_index=True)

        # Comprehensive debt & leverage metrics
        st.markdown('<div class="section-title">Debt & leverage metrics</div>', unsafe_allow_html=True)
        ratio_rows = []
        for _, r in hist.sort_values("fiscal_year", ascending=False).iterrows():
            assets    = r.get("total_assets") or None
            equity    = r.get("equity") or None
            lt_debt   = float(r.get("lt_financial_debt") or 0)
            st_debt   = float(r.get("st_financial_debt") or 0)
            cash      = float(r.get("cash") or 0)
            ebitda    = r.get("ebitda") or None
            ebit      = r.get("ebit") or None
            net_profit = r.get("net_profit") or None
            revenue   = r.get("revenue") or None
            fin_charges = r.get("financial_charges") or _get("65", r["fiscal_year"])

            gross_debt = lt_debt + st_debt
            net_debt   = gross_debt - cash

            # Ratios
            equity_ratio  = f"{equity/assets*100:.1f}%" if equity and assets else "—"
            debt_equity   = f"{gross_debt/equity:.1f}×" if equity and equity > 0 else "—"
            net_lev       = f"{net_debt/ebitda:.1f}×" if ebitda and ebitda > 0 else "—"
            gross_lev     = f"{gross_debt/ebitda:.1f}×" if ebitda and ebitda > 0 else "—"
            int_cov       = f"{ebit/fin_charges:.1f}×" if (ebit and fin_charges and fin_charges > 0) else "—"
            debt_assets   = f"{gross_debt/assets*100:.1f}%" if assets else "—"
            roe           = f"{net_profit/equity*100:.1f}%" if (net_profit and equity and equity > 0) else "—"
            roa           = f"{ebit/assets*100:.1f}%" if (ebit and assets) else "—"

            ratio_rows.append({
                "FY":                     int(r["fiscal_year"]),
                "Equity":                 fmt_eur(equity),
                "Gross debt":             fmt_eur(gross_debt),
                "Net debt":               fmt_eur(net_debt),
                "Cash":                   fmt_eur(cash),
                "Equity ratio":           equity_ratio,
                "Debt / equity":          debt_equity,
                "Debt / assets":          debt_assets,
                "Net debt / EBITDA":      net_lev,
                "Gross debt / EBITDA":    gross_lev,
                "EBIT / interest cover":  int_cov,
                "RoE":                    roe,
                "RoA":                    roa,
            })
        ratio_df = pd.DataFrame(ratio_rows)
        st.dataframe(ratio_df, use_container_width=True, hide_index=True)

        # Visual: leverage over time
        if len(ratio_rows) >= 2:
            nd_chart = pd.DataFrame([
                {"FY": int(r["fiscal_year"]),
                 "Net debt": float(r.get("lt_financial_debt") or 0) + float(r.get("st_financial_debt") or 0) - float(r.get("cash") or 0),
                 "Equity": float(r.get("equity") or 0)}
                for _, r in hist.sort_values("fiscal_year").iterrows()
            ]).set_index("FY")
            st.markdown('<div class="section-title">Net debt vs equity evolution</div>', unsafe_allow_html=True)
            st.bar_chart(nd_chart, use_container_width=True)


# ── Cash flow tab ─────────────────────────────────────────────────────────────
with t_cf:
    if hist.empty:
        st.info("No financial data loaded. Use the P&L tab to load financials.")
    else:
        # Build in chronological order (need prev-year values)
        fy_list = sorted(hist["fiscal_year"].tolist())

        # Per-year data dict — prefer financial_summary columns (pre-computed),
        # fall back to raw rubric codes only if not available
        fy_data = {}
        for fy in fy_list:
            fy_data[fy] = {
                "net_profit":  _hist_val("net_profit", fy) or _get("9904", fy),
                "da":          _hist_val("da", fy) or _get("630", fy),
                # Non-cash items: use rubric codes (not in financial_summary)
                "writedowns":  _get("631/4", fy),
                "provisions":  _get("635/8", fy),
                # Balance sheet items — from financial_summary directly
                "tang_fa":     _hist_val("fixed_assets", fy) or _get("22", fy),
                "fin_fa":      _get("28", fy),   # financial FA not in summary
                "inv":         _hist_val("inventories", fy) or _get("3", fy),
                "rec":         _hist_val("trade_receivables", fy) or _get("41", fy),
                "pay":         _hist_val("trade_payables", fy) or _get("44", fy),
                "equity":      _hist_val("equity", fy),
                "lt_debt":     _hist_val("lt_financial_debt", fy),
                "st_debt":     _hist_val("st_financial_debt", fy),
                "cash":        _hist_val("cash", fy),
            }

        # ── Build the CF statement rows ────────────────────────────────────────
        # We render one HTML table with all years as columns

        years = sorted(fy_list, reverse=True)

        def _sign(v):
            """Return formatted value with sign; None → '—'."""
            if v is None: return "—"
            return fmt_eur(v)

        def _row(label, values_dict, style="row", note=None):
            """Return (label, style, {fy: value_str}, note)."""
            return (label, style, {fy: values_dict.get(fy) for fy in years}, note)

        CF_SECTIONS = []  # list of (label, style, {fy: num_or_None}, note)

        # Per-year computation
        op_cfs  = {}
        inv_cfs = {}
        fin_cfs = {}
        tot_cfs = {}

        np_by_fy      = {}
        da_by_fy      = {}
        wd_by_fy      = {}
        prov_by_fy    = {}
        dinv_by_fy    = {}
        drec_by_fy    = {}
        dpay_by_fy    = {}
        capex_by_fy   = {}
        dfin_by_fy    = {}
        dlt_by_fy     = {}
        dst_by_fy     = {}
        dequity_by_fy = {}
        cash_open     = {}
        cash_close    = {}
        dcash_by_fy   = {}

        for i, fy in enumerate(fy_list):
            d    = fy_data[fy]
            prev = fy_data[fy_list[i-1]] if i > 0 else {}

            np_   = d["net_profit"]
            da_   = d["da"]
            wd_   = d["writedowns"] or 0
            prov_ = d["provisions"] or 0

            # Δ Working capital (increase in assets = outflow, increase in liabilities = inflow)
            dinv = (-(d["inv"] - prev["inv"])) if (d["inv"] is not None and prev.get("inv") is not None) else None
            drec = (-(d["rec"] - prev["rec"])) if (d["rec"] is not None and prev.get("rec") is not None) else None
            dpay = (  d["pay"] - prev["pay"] ) if (d["pay"] is not None and prev.get("pay") is not None) else None

            # OPERATING CF
            op_cf = None
            if np_ is not None:
                non_cash = (da_ or 0) + wd_ + prov_
                wc = sum(x for x in [dinv, drec, dpay] if x is not None)
                op_cf = np_ + non_cash + wc

            # INVESTING CF: capex + Δ financial FA
            capex  = None
            if d["tang_fa"] is not None and prev.get("tang_fa") is not None and da_ is not None:
                capex = -((d["tang_fa"] - prev["tang_fa"]) + da_)   # outflow = negative

            dfin  = None
            if d["fin_fa"] is not None and prev.get("fin_fa") is not None:
                dfin = -(d["fin_fa"] - prev["fin_fa"])  # increase in fin assets = outflow

            inv_cf = None
            if capex is not None or dfin is not None:
                inv_cf = (capex or 0) + (dfin or 0)

            # FINANCING CF: Δ LT debt + Δ ST debt − Δ equity (excl profit)
            dlt   = (d["lt_debt"] - prev["lt_debt"]) if (d["lt_debt"] is not None and prev.get("lt_debt") is not None) else None
            dst   = (d["st_debt"] - prev["st_debt"]) if (d["st_debt"] is not None and prev.get("st_debt") is not None) else None
            # Equity retained = change in equity - net profit (proxy for dividends/capital moves)
            dequity = None
            if d["equity"] is not None and prev.get("equity") is not None and np_ is not None:
                dequity = (d["equity"] - prev["equity"]) - np_   # net equity change ex-profit

            fin_cf = None
            if dlt is not None or dst is not None:
                fin_cf = (dlt or 0) + (dst or 0) + (dequity or 0)

            # TOTAL & RECONCILIATION
            tot_cf = sum(x for x in [op_cf, inv_cf, fin_cf] if x is not None) or None
            cash_o = prev.get("cash")   # opening = previous year cash
            cash_c = d["cash"]          # closing
            dcash  = (cash_c - cash_o) if (cash_c is not None and cash_o is not None) else None

            op_cfs[fy]  = op_cf
            inv_cfs[fy] = inv_cf
            fin_cfs[fy] = fin_cf
            tot_cfs[fy] = tot_cf

            np_by_fy[fy]      = np_
            da_by_fy[fy]      = (da_ or 0) + wd_ + prov_ if np_ is not None else None
            wd_by_fy[fy]      = wd_ if wd_ else None
            prov_by_fy[fy]    = prov_ if prov_ else None
            dinv_by_fy[fy]    = dinv
            drec_by_fy[fy]    = drec
            dpay_by_fy[fy]    = dpay
            capex_by_fy[fy]   = capex
            dfin_by_fy[fy]    = dfin
            dlt_by_fy[fy]     = dlt
            dst_by_fy[fy]     = dst
            dequity_by_fy[fy] = dequity
            cash_open[fy]     = cash_o
            cash_close[fy]    = cash_c
            dcash_by_fy[fy]   = dcash

        # ── Render the table ──────────────────────────────────────────────────
        def _cell(d, fy):
            v = d.get(fy)
            return fmt_eur(v) if v is not None else "—"

        def _cfrow(label, data_dict, style="row"):
            cells = "".join(f"<td>{_cell(data_dict, fy)}</td>" for fy in years)
            css_map = {
                "subtotal": "pnl-subtotal", "total": "pnl-total",
                "header": "pnl-header", "spacer": "pnl-spacer",
                "indent": "pnl-indent",
            }
            css = f' class="{css_map.get(style, "")}"' if style in css_map else ""
            return f"<tr{css}><td>{label}</td>{cells}</tr>"

        yr_heads = "".join(f"<th>FY {int(y)}</th>" for y in years)
        h = f"<tr><th>Cash flow statement</th>{yr_heads}</tr>"
        r = ""

        r += _cfrow("A. OPERATING ACTIVITIES", {}, "header")
        r += _cfrow("Net profit", np_by_fy, "indent")
        r += _cfrow("+ D&A &amp; non-cash charges", da_by_fy, "indent")
        r += _cfrow("± Change in inventories", dinv_by_fy, "indent")
        r += _cfrow("± Change in receivables", drec_by_fy, "indent")
        r += _cfrow("± Change in trade payables", dpay_by_fy, "indent")
        r += _cfrow("= Net cash from operations", op_cfs, "subtotal")

        r += _cfrow("", {}, "spacer")
        r += _cfrow("B. INVESTING ACTIVITIES", {}, "header")
        r += _cfrow("− Capex (est.)", capex_by_fy, "indent")
        r += _cfrow("± Change in financial assets", dfin_by_fy, "indent")
        r += _cfrow("= Net cash from investing", inv_cfs, "subtotal")

        r += _cfrow("", {}, "spacer")
        r += _cfrow("C. FINANCING ACTIVITIES", {}, "header")
        r += _cfrow("± Change in LT financial debt", dlt_by_fy, "indent")
        r += _cfrow("± Change in ST financial debt", dst_by_fy, "indent")
        r += _cfrow("± Equity changes (excl. profit)", dequity_by_fy, "indent")
        r += _cfrow("= Net cash from financing", fin_cfs, "subtotal")

        r += _cfrow("", {}, "spacer")
        r += _cfrow("NET CASH MOVEMENT (A+B+C)", tot_cfs, "total")

        r += _cfrow("", {}, "spacer")
        r += _cfrow("D. RECONCILIATION", {}, "header")
        r += _cfrow("Opening cash", cash_open, "indent")
        r += _cfrow("Net cash movement", tot_cfs, "indent")
        r += _cfrow("Closing cash (balance sheet)", cash_close, "subtotal")
        r += _cfrow("Δ Cash (BS check)", dcash_by_fy, "indent")

        st.markdown(f'<table class="pnl-table">{h}{r}</table>', unsafe_allow_html=True)

        # Free cash flow summary
        fcf_by_fy = {fy: (op_cfs.get(fy) or 0) + (capex_by_fy.get(fy) or 0)
                     if op_cfs.get(fy) is not None else None
                     for fy in fy_list}

        st.markdown('<div class="section-title">Free cash flow (Operating CF + Capex)</div>', unsafe_allow_html=True)
        if len(fy_list) >= 2:
            fcf_chart = pd.DataFrame([
                {"FY": int(fy), "Free cash flow": fcf_by_fy.get(fy), "Operating CF": op_cfs.get(fy)}
                for fy in fy_list if fcf_by_fy.get(fy) is not None
            ]).set_index("FY")
            if not fcf_chart.empty:
                st.bar_chart(fcf_chart, use_container_width=True)

        st.markdown("""
        <div style="font-size:10px;color:#94a3b8;margin-top:8px;line-height:1.6">
        <strong>Methodology (indirect method):</strong>
        Operating CF = Net profit + D&amp;A + non-cash charges ± working capital changes.
        Capex = Δ net tangible fixed assets + D&amp;A (estimated since gross additions are not separately reported).
        Financing CF = Δ financial debts ± equity movements excluding current-year profit.
        WC lines and capex shown as — when balance sheet rubric codes (3, 41, 44, 22) are unavailable
        (abbreviated filing model).
        Reconciliation compares computed net movement to the actual change in cash per balance sheet.
        </div>
        """, unsafe_allow_html=True)


# ── Trend tab ─────────────────────────────────────────────────────────────────
with t_trend:
    if hist.empty:
        st.info("Load financials to see trends.")
    elif len(hist) >= 2:
        chart_df = hist.set_index("fiscal_year")[["revenue", "ebitda", "ebit", "net_profit"]].copy()
        chart_df.index = chart_df.index.astype(int)
        chart_df.columns = ["Revenue", "EBITDA", "EBIT", "Net profit"]
        st.markdown('<div class="section-title">Revenue & EBITDA (€)</div>', unsafe_allow_html=True)
        st.line_chart(chart_df[["Revenue", "EBITDA"]], use_container_width=True)
        st.markdown('<div class="section-title">EBIT & net profit (€)</div>', unsafe_allow_html=True)
        st.line_chart(chart_df[["EBIT", "Net profit"]], use_container_width=True)
        if hist["ebitda_margin_pct"].notna().any():
            marg_df = hist.set_index("fiscal_year")[["ebitda_margin_pct"]].dropna()
            marg_df.index = marg_df.index.astype(int)
            marg_df.columns = ["EBITDA margin %"]
            st.markdown('<div class="section-title">EBITDA margin (%)</div>', unsafe_allow_html=True)
            st.line_chart(marg_df, use_container_width=True)
        if hist["fte_total"].notna().any():
            fte_df = hist.set_index("fiscal_year")[["fte_total"]].dropna()
            fte_df.index = fte_df.index.astype(int)
            fte_df.columns = ["FTE"]
            st.markdown('<div class="section-title">Headcount (FTE)</div>', unsafe_allow_html=True)
            st.line_chart(fte_df, use_container_width=True)
    else:
        st.info("Need at least 2 years of data for trend charts.")


# ── Structure tab ─────────────────────────────────────────────────────────────
with t_struct:
    has_struct = not admins.empty or not pis.empty or not shareholders.empty

    if not has_struct:
        st.info("No structure data loaded yet.")
        st.info("Use the [DataSnoop web app](https://datasnoop.be) to load structure data for this company.")
    else:
        import random

        # ── Side-by-side: lists LEFT | spider-web RIGHT ─────────────────────
        col_lists, col_graph = st.columns([2, 3], gap="medium")

        # ── LEFT PANEL: three visually distinct sections ────────────────────
        with col_lists:

            # ── SHAREHOLDERS ────────────────────────────────────────────────
            if not shareholders.empty:
                unique_sh = shareholders.drop_duplicates(subset=["name"])
                st.markdown(
                    f'<div style="background:#f0fdf4;border:1px solid #86efac;border-radius:8px;'
                    f'padding:10px 12px;margin-bottom:8px">'
                    f'<div style="font-size:12px;font-weight:800;color:#166534;margin-bottom:6px">'
                    f'\u2b06 SHAREHOLDERS ({len(unique_sh)})</div>',
                    unsafe_allow_html=True)
                for i_sh, (_, sh) in enumerate(unique_sh.iterrows()):
                    identifier = sh.get("identifier") or sh.get("enterprise_number_shareholder") or ""
                    cbe_clean  = str(identifier).replace(".", "").strip()
                    is_cbe     = cbe_clean.isdigit() and len(cbe_clean) == 10
                    sname      = sh.get("name") or "Unknown"
                    pct        = sh.get("ownership_pct")
                    is_indiv   = sh.get("shareholder_type") == "individual"
                    icon       = "👤" if is_indiv else "🏢"
                    pct_str    = f" ({pct:.1f}%)" if pd.notna(pct) else ""
                    cbe_str    = f" · {fmt_cbe(cbe_clean)}" if is_cbe else ""

                    if is_cbe:
                        if st.button(f"{icon} {sname}{pct_str}", key=f"sh_nav_{i_sh}_{cbe_clean}",
                                     use_container_width=True):
                            navigate_to(cbe_clean)
                    else:
                        st.markdown(
                            f'<div style="font-size:12px;padding:2px 0;color:#334155">'
                            f'{icon} {sname}{pct_str}{cbe_str}</div>',
                            unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)

            # ── CURRENT COMPANY (central node) ──────────────────────────────
            st.markdown(
                f'<div style="margin:4px 0;padding:10px 14px;background:#eef2ff;'
                f'border:2px solid #6366f1;border-radius:8px;font-weight:800;color:#4338ca;font-size:14px;'
                f'text-align:center">'
                f'🏢 {name or fmt_cbe(selected_cbe)}'
                f'<div style="font-weight:400;font-size:11px;color:#64748b;margin-top:2px">'
                f'{fmt_cbe(selected_cbe)}</div></div>',
                unsafe_allow_html=True)

            # ── SUBSIDIARIES ────────────────────────────────────────────────
            if not pis.empty:
                unique_pi = pis.drop_duplicates(subset=["name"])
                st.markdown(
                    f'<div style="background:#fff7ed;border:1px solid #fdba74;border-radius:8px;'
                    f'padding:10px 12px;margin-top:8px;margin-bottom:8px">'
                    f'<div style="font-size:12px;font-weight:800;color:#9a3412;margin-bottom:6px">'
                    f'\u2b07 SUBSIDIARIES ({len(unique_pi)})</div>',
                    unsafe_allow_html=True)
                for i_pi, (_, pi) in enumerate(unique_pi.sort_values(
                        "ownership_pct", ascending=False, na_position="last").iterrows()):
                    identifier = pi.get("identifier") or ""
                    cbe_clean  = str(identifier).replace(".", "").strip()
                    is_cbe     = cbe_clean.isdigit() and len(cbe_clean) == 10
                    pname      = pi.get("name") or "Unknown"
                    pct        = pi.get("ownership_pct")
                    country    = pi.get("country") or ""
                    pct_str    = f" ({pct:.0f}%)" if pd.notna(pct) else ""
                    ctry_str   = f" [{country}]" if country else ""

                    if is_cbe:
                        if st.button(f"🏢 {pname}{pct_str}{ctry_str}",
                                     key=f"pi_nav_{i_pi}_{cbe_clean}", use_container_width=True):
                            navigate_to(cbe_clean)
                    else:
                        st.markdown(
                            f'<div style="font-size:12px;padding:2px 0;color:#334155">'
                            f'🏢 {pname}{pct_str}{ctry_str}</div>',
                            unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)

            # ── BOARD & ADMINISTRATORS ──────────────────────────────────────
            if not admins.empty:
                unique_ad = admins.drop_duplicates(subset=["name", "role"])
                st.markdown(
                    f'<div style="background:#fefce8;border:1px solid #fde047;border-radius:8px;'
                    f'padding:10px 12px;margin-top:8px">'
                    f'<div style="font-size:12px;font-weight:800;color:#854d0e;margin-bottom:6px">'
                    f'👔 BOARD & ADMINISTRATORS ({len(unique_ad)})</div>',
                    unsafe_allow_html=True)
                for i_ad, (_, ad) in enumerate(unique_ad.iterrows()):
                    role       = ROLE_LABELS.get(ad.get("role", ""), ad.get("role", "") or "Administrator")
                    identifier = ad.get("identifier") or ""
                    cbe_clean  = str(identifier).replace(".", "").strip()
                    is_cbe     = cbe_clean.isdigit() and len(cbe_clean) == 10
                    aname      = ad.get("name") or "Unknown"
                    rep        = ad.get("representative_name") or ""
                    is_legal   = ad.get("person_type") == "legal"
                    icon       = "🏢" if is_legal else "👤"
                    rep_str    = f" (rep: {rep})" if rep else ""

                    if is_cbe:
                        if st.button(f"{icon} {aname} \u2014 {role}",
                                     key=f"ad_nav_{i_ad}_{cbe_clean}", use_container_width=True):
                            navigate_to(cbe_clean)
                    else:
                        st.markdown(
                            f'<div style="font-size:12px;padding:2px 0;color:#334155">'
                            f'{icon} {aname} \u2014 '
                            f'<span style="color:#92400e;font-weight:600">{role}</span>'
                            f'{rep_str}</div>',
                            unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)

        # ── RIGHT PANEL: clickable spider-web ───────────────────────────────
        with col_graph:
            central_label = name or fmt_cbe(selected_cbe)
            G_s, nav_s, trunc_s = bfs_build_graph(
                selected_cbe, central_label, shareholders, pis, admins, max_depth=4)

            if trunc_s:
                st.warning(f"Network truncated at {MAX_NETWORK_NODES} nodes.")
            st.caption(f"{len(G_s.nodes())} entities \u00b7 {len(G_s.edges())} connections")

            # Layout
            random.seed(42)
            seed_pos_s = {selected_cbe: (0.0, 0.0)}
            for n, d in G_s.nodes(data=True):
                if n == selected_cbe:
                    continue
                nt = d.get("ntype", "")
                nd = d.get("depth", 1)
                spread = 0.5 + nd * 0.4
                if nt == "shareholder":
                    seed_pos_s[n] = (random.uniform(-spread, spread),
                                     random.uniform(0.3 + nd * 0.4, 0.8 + nd * 0.5))
                elif nt == "subsidiary":
                    seed_pos_s[n] = (random.uniform(-spread, spread),
                                     random.uniform(-0.8 - nd * 0.5, -0.3 - nd * 0.4))
                elif nt == "admin":
                    side = random.choice([-1, 1])
                    seed_pos_s[n] = (side * random.uniform(0.5, 1.0), random.uniform(-0.3, 0.3))
                else:
                    seed_pos_s[n] = (random.uniform(-spread, spread),
                                     random.uniform(-spread, spread))

            pos_s = nx.spring_layout(G_s, pos=seed_pos_s, fixed=[selected_cbe], seed=42,
                                     k=2.5 / max(1, len(G_s.nodes()) ** 0.5), iterations=80)

            # Edge traces
            edge_traces_s = []
            edge_ann_s = []
            for u, v, d in G_s.edges(data=True):
                x0, y0 = pos_s[u]
                x1, y1 = pos_s[v]
                edge_traces_s.append(go.Scatter(
                    x=[x0, x1, None], y=[y0, y1, None], mode="lines",
                    line=dict(width=d.get("width", 1.5), color=d.get("color", "#cbd5e1"),
                              dash=d.get("dash", "solid")),
                    hoverinfo="none", showlegend=False))
                lbl = d.get("label", "")
                if lbl:
                    edge_ann_s.append(dict(
                        x=(x0+x1)/2, y=(y0+y1)/2, text=f"<b>{lbl}</b>", showarrow=False,
                        font=dict(size=8, color=d.get("color", "#94a3b8")),
                        bgcolor="rgba(255,255,255,0.85)", borderpad=2))

            # Node traces with customdata for click navigation
            # Build an ordered list of all nodes for click lookup
            _all_node_cbes = []  # parallel to plotly point indices
            ngroups_s = {}
            for n, d in G_s.nodes(data=True):
                nt = d.get("ntype", "other")
                if nt not in ngroups_s:
                    ngroups_s[nt] = {"x": [], "y": [], "text": [], "hover": [],
                                     "size": [], "color": [], "cbe": []}
                x, y = pos_s[n]
                lbl = d.get("label", "")
                ngroups_s[nt]["x"].append(x)
                ngroups_s[nt]["y"].append(y)
                ngroups_s[nt]["text"].append(lbl[:22] + "..." if len(lbl) > 22 else lbl)
                ngroups_s[nt]["hover"].append(d.get("hover", lbl))
                ngroups_s[nt]["size"].append(d.get("size", 14))
                ngroups_s[nt]["color"].append(d.get("color", "#94a3b8"))
                ngroups_s[nt]["cbe"].append(d.get("cbe") or "")

            legend_s = {"central": "🏢 This company", "shareholder": "\u2b06 Shareholders",
                        "subsidiary": "\u2b07 Subsidiaries", "admin": "👔 Admins"}
            ntrace_s = []
            for nt, grp in ngroups_s.items():
                ntrace_s.append(go.Scatter(
                    x=grp["x"], y=grp["y"], mode="markers+text",
                    marker=dict(size=grp["size"], color=grp["color"],
                                line=dict(width=1.5, color="white")),
                    text=grp["text"], textposition="top center",
                    textfont=dict(size=9, color="#334155"),
                    hovertext=grp["hover"], hoverinfo="text",
                    customdata=grp["cbe"],
                    name=legend_s.get(nt, nt), legendgroup=nt, showlegend=True))

            fig_s = go.Figure(data=edge_traces_s + ntrace_s)
            fig_s.update_layout(
                annotations=edge_ann_s, showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=1.02,
                            xanchor="center", x=0.5, font=dict(size=11)),
                xaxis=dict(showgrid=False, zeroline=False, showticklabels=False, visible=False),
                yaxis=dict(showgrid=False, zeroline=False, showticklabels=False, visible=False),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=5, r=5, t=40, b=5),
                height=900,
                hoverlabel=dict(bgcolor="white", font_size=12, bordercolor="#e2e8f0"),
                dragmode="pan")

            # Clickable graph
            event_s = st.plotly_chart(fig_s, use_container_width=True,
                                      key="struct_network_graph",
                                      on_select="rerun", selection_mode="points")

            # Handle click → navigate
            if event_s and event_s.selection and event_s.selection.points:
                pt = event_s.selection.points[0]
                clicked_cbe = pt.get("customdata", "")
                if clicked_cbe and len(clicked_cbe) == 10 and clicked_cbe != selected_cbe:
                    navigate_to(clicked_cbe)


# ── Group financials tab ─────────────────────────────────────────────────────
with t_group:
    if pis.empty:
        st.info("No subsidiaries found. Group financials require participating interest data.")
    else:
        detail_df, yearly_df, total_subs, subs_with_data = load_group_financials(selected_cbe)

        if detail_df.empty:
            st.warning("No financial data available for any group entity.")
        else:
            st.caption(
                f"Group view: **{subs_with_data}** of **{total_subs}** subsidiaries have financial data. "
                f"Ownership % not available in most filings — all entities included at 100% (no pro-rata)."
            )

            # ── Section 1: Group breakdown (latest year) ────────────────
            st.markdown('<div class="section-title">Group breakdown (latest available year)</div>',
                        unsafe_allow_html=True)

            # Header row
            hdr_cols = st.columns([3, 1.5, 1, 1.5, 1.5, 1, 1.5, 1.5, 1])
            hdr_labels = ["Company", "CBE", "FY", "Revenue", "EBITDA", "Margin", "Net profit", "Equity", "FTE"]
            for c, lbl in zip(hdr_cols, hdr_labels):
                c.markdown(f"<span style='font-size:10px;font-weight:700;color:#64748b;text-transform:uppercase'>{lbl}</span>",
                           unsafe_allow_html=True)

            # Data rows
            for idx, (_, row) in enumerate(detail_df.iterrows()):
                is_par = row.get("is_parent", False)
                cols = st.columns([3, 1.5, 1, 1.5, 1.5, 1, 1.5, 1.5, 1])
                cbe_val = row["enterprise_number"]
                rname = row.get("name") or fmt_cbe(cbe_val)

                if is_par:
                    cols[0].markdown(
                        f"<span style='font-weight:800;color:#4338ca;font-size:12px'>🏢 {rname}</span>",
                        unsafe_allow_html=True)
                else:
                    if cols[0].button(f"🏢 {rname}", key=f"grp_{idx}_{cbe_val}", use_container_width=True):
                        navigate_to(cbe_val)

                cols[1].caption(fmt_cbe(cbe_val))
                cols[2].caption(str(int(row["fiscal_year"])) if pd.notna(row.get("fiscal_year")) else "—")
                cols[3].markdown(f"**{fmt_eur(row.get('revenue'))}**" if is_par else fmt_eur(row.get("revenue")))
                cols[4].markdown(f"**{fmt_eur(row.get('ebitda'))}**" if is_par else fmt_eur(row.get("ebitda")))
                m = row.get("ebitda_margin")
                cols[5].caption(f"{m:.1f}%" if pd.notna(m) else "—")
                cols[6].caption(fmt_eur(row.get("net_profit")))
                cols[7].caption(fmt_eur(row.get("equity")))
                fte = row.get("fte_total")
                cols[8].caption(f"{fte:,.0f}" if pd.notna(fte) else "—")

            # Totals row
            st.divider()
            tot_cols = st.columns([3, 1.5, 1, 1.5, 1.5, 1, 1.5, 1.5, 1])
            tot_cols[0].markdown("**GROUP TOTAL**")
            tot_rev = detail_df["revenue"].sum()
            tot_ebitda = detail_df["ebitda"].sum()
            tot_np = detail_df["net_profit"].sum()
            tot_eq = detail_df["equity"].sum()
            tot_fte = detail_df["fte_total"].sum()
            tot_margin = round(tot_ebitda / tot_rev * 100, 1) if tot_rev and tot_rev > 0 else None
            tot_cols[3].markdown(f"**{fmt_eur(tot_rev)}**")
            tot_cols[4].markdown(f"**{fmt_eur(tot_ebitda)}**")
            tot_cols[5].markdown(f"**{tot_margin:.1f}%**" if tot_margin else "—")
            tot_cols[6].markdown(f"**{fmt_eur(tot_np)}**")
            tot_cols[7].markdown(f"**{fmt_eur(tot_eq)}**")
            tot_cols[8].markdown(f"**{tot_fte:,.0f}**" if pd.notna(tot_fte) else "—")

            # ── Section 2: Group financials over time ───────────────────
            if not yearly_df.empty and len(yearly_df) >= 2:
                st.markdown('<div class="section-title">Group financials over time</div>',
                            unsafe_allow_html=True)

                # Build HTML table
                years = yearly_df["fiscal_year"].tolist()
                rows_data = [
                    ("Revenue",        "revenue",        "subtotal"),
                    ("EBITDA",         "ebitda",         "subtotal"),
                    ("EBITDA margin",  "ebitda_margin",  "row"),
                    ("EBIT",           "ebit",           "row"),
                    ("Net profit",     "net_profit",     "row"),
                    ("Equity",         "equity",         "row"),
                    ("Total assets",   "total_assets",   "row"),
                    ("FTE",            "fte_total",       "row"),
                    ("# companies",    "company_count",   "row"),
                ]

                html = '<table class="pnl-table"><thead><tr><th>Line item</th>'
                for fy in years:
                    html += f'<th>FY {int(fy)}</th>'
                html += '</tr></thead><tbody>'
                for label, col, style in rows_data:
                    cls = "pnl-subtotal" if style == "subtotal" else ""
                    html += f'<tr class="{cls}"><td>{label}</td>'
                    for fy in years:
                        yr_row = yearly_df[yearly_df["fiscal_year"] == fy]
                        if yr_row.empty:
                            html += '<td style="text-align:right">—</td>'
                        else:
                            v = yr_row.iloc[0].get(col)
                            if col == "ebitda_margin":
                                cell = f"{v:.1f}%" if pd.notna(v) else "—"
                            elif col == "company_count":
                                cell = f"{int(v)}" if pd.notna(v) else "—"
                            elif col == "fte_total":
                                cell = f"{v:,.0f}" if pd.notna(v) else "—"
                            else:
                                cell = fmt_eur(v)
                            html += f'<td style="text-align:right">{cell}</td>'
                    html += '</tr>'
                html += '</tbody></table>'
                st.markdown(html, unsafe_allow_html=True)

                # Trend charts
                st.markdown('<div class="section-title">Group revenue & EBITDA trend</div>',
                            unsafe_allow_html=True)
                chart_df = yearly_df.set_index("fiscal_year")[["revenue", "ebitda"]].copy()
                chart_df.index = chart_df.index.astype(int)
                chart_df.columns = ["Revenue", "EBITDA"]
                st.line_chart(chart_df, use_container_width=True)

            # ── Section 3: Revenue composition ──────────────────────────
            if len(detail_df) >= 2 and detail_df["revenue"].notna().any():
                st.markdown('<div class="section-title">Revenue composition</div>',
                            unsafe_allow_html=True)
                comp = detail_df[detail_df["revenue"].notna() & (detail_df["revenue"] > 0)].copy()
                if not comp.empty:
                    comp = comp.sort_values("revenue", ascending=True)
                    fig = go.Figure(go.Bar(
                        x=comp["revenue"],
                        y=comp["name"],
                        orientation="h",
                        marker_color=["#6366f1" if p else "#94a3b8" for p in comp["is_parent"]],
                        text=[fmt_eur(v) for v in comp["revenue"]],
                        textposition="auto",
                        textfont=dict(size=10),
                    ))
                    fig.update_layout(
                        xaxis=dict(visible=False),
                        yaxis=dict(tickfont=dict(size=10)),
                        margin=dict(l=10, r=10, t=10, b=10),
                        height=max(200, len(comp) * 35),
                        plot_bgcolor="rgba(0,0,0,0)",
                        paper_bgcolor="rgba(0,0,0,0)",
                    )
                    st.plotly_chart(fig, use_container_width=True, key="group_rev_comp")


# ── Network tab (spider-web group structure) ──────────────────────────────────
with t_network:
    has_struct_net = not admins.empty or not pis.empty or not shareholders.empty

    if not has_struct_net:
        st.info("No structure data loaded yet.")
        st.info("Use the [DataSnoop web app](https://datasnoop.be) to load structure data for this company.")
    else:
        # ── Depth slider ────────────────────────────────────────────────────
        import random
        depth = 4

        central_label = name or fmt_cbe(selected_cbe)
        G, nav_options, truncated = bfs_build_graph(
            selected_cbe, central_label, shareholders, pis, admins, max_depth=depth)

        if truncated:
            st.warning(f"Network truncated at {MAX_NETWORK_NODES} nodes. Reduce depth for a cleaner view.")

        st.caption(f"{len(G.nodes())} entities · {len(G.edges())} connections")

        # ── Layout: spring with seeded positions ────────────────────────────
        random.seed(42)
        seed_pos = {selected_cbe: (0.0, 0.0)}
        for n, d in G.nodes(data=True):
            if n == selected_cbe:
                continue
            nt = d.get("ntype", "")
            nd = d.get("depth", 1)
            spread = 0.5 + nd * 0.4  # wider spread for deeper nodes
            if nt == "shareholder":
                seed_pos[n] = (random.uniform(-spread, spread), random.uniform(0.3 + nd * 0.4, 0.8 + nd * 0.5))
            elif nt == "subsidiary":
                seed_pos[n] = (random.uniform(-spread, spread), random.uniform(-0.8 - nd * 0.5, -0.3 - nd * 0.4))
            elif nt == "admin":
                side = random.choice([-1, 1])
                seed_pos[n] = (side * random.uniform(0.5, 1.0), random.uniform(-0.3, 0.3))
            else:
                seed_pos[n] = (random.uniform(-spread, spread), random.uniform(-spread, spread))

        pos = nx.spring_layout(G, pos=seed_pos, fixed=[selected_cbe], seed=42,
                               k=2.5 / max(1, len(G.nodes()) ** 0.5), iterations=80)

        # ── Build Plotly traces ─────────────────────────────────────────────
        edge_traces = []
        edge_annotations = []

        for u, v, d in G.edges(data=True):
            x0, y0 = pos[u]
            x1, y1 = pos[v]
            ecolor = d.get("color", "#cbd5e1")
            edash = d.get("dash", "solid")
            ewidth = d.get("width", 1.5)

            edge_traces.append(go.Scatter(
                x=[x0, x1, None], y=[y0, y1, None],
                mode="lines",
                line=dict(width=ewidth, color=ecolor, dash=edash),
                hoverinfo="none",
                showlegend=False,
            ))

            label = d.get("label", "")
            if label:
                mx, my = (x0 + x1) / 2, (y0 + y1) / 2
                edge_annotations.append(dict(
                    x=mx, y=my, text=f"<b>{label}</b>",
                    showarrow=False,
                    font=dict(size=8, color=ecolor),
                    bgcolor="rgba(255,255,255,0.85)",
                    borderpad=2,
                ))

        # Node traces — group by type for legend
        node_groups = {}
        for n, d in G.nodes(data=True):
            nt = d.get("ntype", "other")
            if nt not in node_groups:
                node_groups[nt] = {"x": [], "y": [], "text": [], "hover": [],
                                   "size": [], "color": []}
            x, y = pos[n]
            node_groups[nt]["x"].append(x)
            node_groups[nt]["y"].append(y)
            lbl = d.get("label", "")
            max_lbl = 20 if d.get("depth", 0) > 1 else 25
            node_groups[nt]["text"].append(lbl[:max_lbl] + "..." if len(lbl) > max_lbl else lbl)
            node_groups[nt]["hover"].append(d.get("hover", lbl))
            node_groups[nt]["size"].append(d.get("size", 14))
            node_groups[nt]["color"].append(d.get("color", "#94a3b8"))

        legend_names = {
            "central": "🏢 This company",
            "shareholder": "⬆ Shareholders",
            "subsidiary": "⬇ Subsidiaries",
            "admin": "👔 Board & admins",
        }

        node_traces = []
        for nt, grp in node_groups.items():
            node_traces.append(go.Scatter(
                x=grp["x"], y=grp["y"],
                mode="markers+text",
                marker=dict(size=grp["size"], color=grp["color"],
                            line=dict(width=1.5, color="white")),
                text=grp["text"],
                textposition="top center",
                textfont=dict(size=9, color="#334155"),
                hovertext=grp["hover"],
                hoverinfo="text",
                name=legend_names.get(nt, nt),
                legendgroup=nt,
                showlegend=True,
            ))

        # ── Assemble figure ─────────────────────────────────────────────────
        fig_height = 550 + (depth - 1) * 150
        fig = go.Figure(data=edge_traces + node_traces)
        fig.update_layout(
            annotations=edge_annotations,
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5,
                        font=dict(size=11)),
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False, visible=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False, visible=False),
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=10, r=10, t=40, b=10),
            height=fig_height,
            hoverlabel=dict(bgcolor="white", font_size=12, bordercolor="#e2e8f0"),
        )

        st.plotly_chart(fig, use_container_width=True, key="network_graph")

        # ── Navigation selectbox ────────────────────────────────────────────
        if nav_options:
            st.markdown('<div class="section-title">Navigate to linked company</div>',
                        unsafe_allow_html=True)
            options_list = [""] + [f"{fmt_cbe(c)} — {n}" for c, n in sorted(nav_options.items(), key=lambda x: x[1])]
            cbe_list = [""] + [c for c, _ in sorted(nav_options.items(), key=lambda x: x[1])]
            sel = st.selectbox("Jump to company", options_list, index=0,
                               label_visibility="collapsed", key="net_nav_select")
            if sel:
                idx = options_list.index(sel)
                navigate_to(cbe_list[idx])


# ── Publications tab ──────────────────────────────────────────────────────────
with t_legal:
    if sb_pubs.empty:
        st.info("No Staatsblad publications loaded yet.")
        st.info("Use the [DataSnoop web app](https://datasnoop.be) to load publications for this company.")
    else:
        PUB_ICONS = {
            "ONTSLAGEN - BENOEMINGEN": "👤",
            "KAPITAAL - AANDELEN":     "💰",
            "MAATSCHAPPELIJKE ZETEL":  "📍",
            "DOEL":                    "🎯",
            "DIVERSEN":                "📋",
        }
        for _, pub in sb_pubs.iterrows():
            ptype    = pub["pub_type"] or "Publication"
            icon     = PUB_ICONS.get(ptype, "📄")
            pdf      = pub["pdf_url"]
            pdf_link = (
                f' <a href="https://www.ejustice.just.fgov.be{pdf}" target="_blank">PDF ↗</a>'
                if pdf else ""
            )
            st.markdown(
                f'<div class="filing-row">{icon} <strong>{pub["pub_date"]}</strong>'
                f'&nbsp;&nbsp;{ptype}{pdf_link}</div>',
                unsafe_allow_html=True)
        st.caption(f"{len(sb_pubs)} publication(s) from the Official Gazette")
