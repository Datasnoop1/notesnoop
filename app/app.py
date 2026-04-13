"""Belgian Company Database — Streamlit main app / home page."""

import os
import sys

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from db import get_connection

load_dotenv()

st.set_page_config(
    page_title="Belgian Company DB",
    page_icon="🇧🇪",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
.stat-tile {
    background:#ffffff; border:1px solid #e2e8f0; border-radius:12px;
    padding:18px 16px; text-align:center;
    box-shadow:0 2px 8px rgba(99,102,241,0.06); transition:box-shadow .2s;
    cursor:pointer;
}
.stat-tile:hover { box-shadow:0 4px 16px rgba(99,102,241,0.14); }
.stat-icon  { font-size:24px; margin-bottom:5px; }
.stat-value { font-size:24px; font-weight:800; color:#0f172a; line-height:1.2; }
.stat-label { font-size:10px; color:#94a3b8; text-transform:uppercase; letter-spacing:.08em; margin-top:4px; }

.nav-card {
    background:#ffffff; border:1px solid #e2e8f0; border-left:4px solid #6366f1;
    border-radius:10px; padding:14px 18px; margin-bottom:6px;
    box-shadow:0 1px 4px rgba(0,0,0,0.03); transition:box-shadow .2s, transform .15s;
    text-decoration:none; display:block;
}
.nav-card:hover { box-shadow:0 4px 14px rgba(99,102,241,0.12); transform:translateY(-1px); }
.nav-card h3 { margin:0 0 3px 0; font-size:14px; font-weight:700; color:#1e293b; }
.nav-card p  { margin:0; font-size:12px; color:#64748b; line-height:1.4; }

.hero h1 { font-size:30px; font-weight:800; color:#0f172a; margin-bottom:4px; }
.hero p  { font-size:14px; color:#64748b; margin:0; }

.section-hdr { font-size:12px; font-weight:700; color:#334155; border-left:3px solid #6366f1;
    padding-left:8px; margin:20px 0 8px 0; text-transform:uppercase; letter-spacing:.04em; }
.sr-header { font-size:10px; font-weight:700; color:#94a3b8; text-transform:uppercase; letter-spacing:.05em; }
</style>
""", unsafe_allow_html=True)

sys.path.insert(0, os.path.dirname(__file__))
from components import topbar
topbar(active="Home")

st.markdown("""
<div class="hero">
  <h1>🇧🇪 Belgian Company Database</h1>
  <p>KBO registry · NBB annual accounts · PE deal sourcing</p>
</div>
""", unsafe_allow_html=True)


def _conn():
    return get_connection()


def fmt_eur(v):
    if pd.isna(v) or v is None:
        return "—"
    v = float(v)
    neg = v < 0
    a = abs(v)
    if a >= 1e9:   s = f"€{a/1e9:,.1f}B"
    elif a >= 1e6: s = f"€{a/1e6:,.1f}M"
    elif a >= 1e3: s = f"€{a/1e3:,.0f}K"
    else:          s = f"€{a:,.0f}"
    return f"-{s}" if neg else s


def fmt_cbe(n):
    n = str(n).zfill(10)
    return f"{n[:4]}.{n[4:7]}.{n[7:]}"


# ---------------------------------------------------------------------------
# Database stats
# ---------------------------------------------------------------------------

STAT_DEFS = [
    ("🏢", "Active enterprises",        "SELECT COUNT(*) FROM enterprise WHERE status='AC'",           True),
    ("📊", "Companies with financials", "SELECT COUNT(DISTINCT enterprise_number) FROM financial_data",True),
    ("📄", "Filings loaded",            "SELECT COUNT(DISTINCT deposit_key) FROM financial_data",       True),
    ("👤", "Administrators indexed",    "SELECT COUNT(DISTINCT name) FROM administrator",               True),
    ("📅", "Snapshot date",             "SELECT value FROM meta WHERE variable='SnapshotDate'",        False),
]


@st.cache_data(ttl=300)
def get_db_stats():
    conn = _conn()
    cur = conn.cursor()
    results = []
    for icon, label, sql, is_int in STAT_DEFS:
        try:
            cur.execute(sql)
            val = cur.fetchone()[0]
        except Exception:
            val = "---"
        results.append((icon, label, val, is_int))
    conn.close()
    return results


@st.cache_data(ttl=300)
def get_top_companies(metric: str = "revenue", limit: int = 15):
    conn = _conn()
    cur = conn.cursor()
    col = metric
    cur.execute(f"""
        SELECT fl.enterprise_number, COALESCE(d.denomination, fl.enterprise_number) AS name,
               fl.{col}, fl.ebitda, fl.revenue,
               CASE WHEN fl.revenue > 0 THEN ROUND((fl.ebitda / fl.revenue * 100)::numeric, 1) END AS margin,
               fl.fte_total, fl.fiscal_year,
               ci.nace_code, COALESCE(nl.description, ci.nace_code) AS sector,
               ci.city
        FROM financial_latest fl
        JOIN company_info ci ON ci.enterprise_number = fl.enterprise_number
        LEFT JOIN denomination d ON d.entity_number = fl.enterprise_number
             AND d.type_of_denomination = '001' AND d.language IN ('2','1')
        LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
        WHERE fl.{col} IS NOT NULL AND fl.{col} > 0
        ORDER BY fl.{col} DESC
        LIMIT %s
    """, (limit,))
    rows = cur.fetchall()
    conn.close()
    return rows


@st.cache_data(ttl=300)
def get_recently_loaded(limit: int = 10):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT fl.enterprise_number, COALESCE(d.denomination, fl.enterprise_number) AS name,
               fl.revenue, fl.ebitda, fl.fiscal_year, n.loaded_at
        FROM financial_latest fl
        JOIN (
            SELECT enterprise_number, MAX(loaded_at) AS loaded_at
            FROM nbb_load_log
            WHERE deposit_key != 'NO_FILINGS'
            GROUP BY enterprise_number
        ) n ON n.enterprise_number = fl.enterprise_number
        LEFT JOIN denomination d ON d.entity_number = fl.enterprise_number
             AND d.type_of_denomination = '001' AND d.language IN ('2','1')
        ORDER BY n.loaded_at DESC
        LIMIT %s
    """, (limit,))
    rows = cur.fetchall()
    conn.close()
    return rows


try:
    stats = get_db_stats()
    cols = st.columns(len(stats))
    PAGE_LINKS = ["/screener", "/screener", "/stats", "/people", "/stats"]
    for col, (icon, label, val, is_int), link in zip(cols, stats, PAGE_LINKS):
        display = f"{val:,}" if is_int and isinstance(val, int) else (val or "—")
        col.markdown(f"""
        <a href="{link}" style="text-decoration:none">
        <div class="stat-tile">
          <div class="stat-icon">{icon}</div>
          <div class="stat-value">{display}</div>
          <div class="stat-label">{label}</div>
        </div>
        </a>
        """, unsafe_allow_html=True)
except Exception as e:
    st.error(f"⚠️ Database not found or not initialised: {e}")
    st.info("Run `python src/kbo_loader.py` and `python src/nbb_loader.py` first.")
    st.stop()

# ---------------------------------------------------------------------------
# Quick navigation
# ---------------------------------------------------------------------------

st.markdown('<div class="section-hdr">Quick access</div>', unsafe_allow_html=True)

nav_cols = st.columns(4)
NAV_ITEMS = [
    ("🔍", "Screener", "/screener",   "Filter by sector, revenue, EBITDA, FTE, region"),
    ("🏢", "Company",  "/company",    "Search by name or CBE — financials, structure, filings"),
    ("📊", "Stats",    "/stats",      "Sector benchmarks, margins, leverage, geography"),
    ("👤", "People",   "/people",     "Find administrators and shareholders by name"),
]
for col, (icon, title, href, desc) in zip(nav_cols, NAV_ITEMS):
    col.markdown(
        f'<a href="{href}" class="nav-card"><h3>{icon} {title}</h3><p>{desc}</p></a>',
        unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Top companies table
# ---------------------------------------------------------------------------

st.markdown('<div class="section-hdr">Largest companies by revenue (latest year)</div>', unsafe_allow_html=True)

metric_choice = st.selectbox(
    "Rank by", ["revenue", "ebitda", "fte_total"],
    format_func=lambda x: {"revenue": "Revenue", "ebitda": "EBITDA", "fte_total": "FTE"}[x],
    label_visibility="collapsed",
)

top_rows = get_top_companies(metric=metric_choice, limit=20)
if top_rows:
    # Column headers
    h1, h2, h3, h4, h5, h6, h7 = st.columns([4, 3, 2, 2, 1.5, 1.5, 1])
    for col, lbl in zip([h1, h2, h3, h4, h5, h6, h7],
                        ["Company", "Sector", "Revenue", "EBITDA", "Margin", "FTE", "FY"]):
        col.markdown(f'<span class="sr-header">{lbl}</span>', unsafe_allow_html=True)

    for i, row in enumerate(top_rows):
        cbe, cname, _val, ebitda, revenue, margin, fte, fy, nace, sector, city = row
        cbe_str = str(cbe).zfill(10)
        rev_s   = fmt_eur(revenue)
        ebd_s   = fmt_eur(ebitda)
        marg_s  = f"{margin:.1f}%" if margin is not None else "—"
        fte_s   = f"{int(fte):,}" if fte else "—"
        fy_s    = str(int(fy)) if fy else "—"
        sec_s   = (sector or "—")[:45]

        c1, c2, c3, c4, c5, c6, c7 = st.columns([4, 3, 2, 2, 1.5, 1.5, 1])
        with c1:
            if st.button(
                f"🏢 {(cname or fmt_cbe(cbe_str))[:38]}",
                key=f"top_{i}_{cbe_str}",
                use_container_width=True,
            ):
                st.session_state["company_cbe"] = cbe_str
                st.session_state["_clear_search"] = True
                st.switch_page("pages/2_company.py")
        c2.caption(sec_s)
        c3.caption(rev_s)
        c4.caption(ebd_s)
        c5.caption(marg_s)
        c6.caption(fte_s)
        c7.caption(fy_s)

# ---------------------------------------------------------------------------
# Recently loaded
# ---------------------------------------------------------------------------

st.markdown('<div class="section-hdr">Recently loaded financials</div>', unsafe_allow_html=True)
recent = get_recently_loaded(limit=10)
if recent:
    h1, h2, h3, h4, h5 = st.columns([4, 2, 2, 1, 2])
    for col, lbl in zip([h1, h2, h3, h4, h5],
                        ["Company", "Revenue", "EBITDA", "FY", "Loaded at"]):
        col.markdown(f'<span class="sr-header">{lbl}</span>', unsafe_allow_html=True)

    for row in recent:
        cbe, cname, revenue, ebitda, fy, loaded_at = row
        cbe_str = str(cbe).zfill(10)
        c1, c2, c3, c4, c5 = st.columns([4, 2, 2, 1, 2])
        with c1:
            if st.button(
                f"🏢 {(cname or fmt_cbe(cbe_str))[:38]}",
                key=f"rec_{cbe_str}",
                use_container_width=True,
            ):
                st.session_state["company_cbe"] = cbe_str
                st.session_state["_clear_search"] = True
                st.switch_page("pages/2_company.py")
        c2.caption(fmt_eur(revenue))
        c3.caption(fmt_eur(ebitda))
        c4.caption(str(int(fy)) if fy else "—")
        c5.caption((str(loaded_at) or "")[:16])
else:
    st.caption("No recent loads found.")
