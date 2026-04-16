"""Screener — filter, browse, and drill into Belgian companies."""

import io
import os
import sys

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
from components import topbar, favourite_star
from db import get_connection

load_dotenv()

DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "..", "..", "db", "belgian_companies.db"))

st.set_page_config(page_title="Screener \u00b7 Belgian Co DB", layout="wide")

st.markdown("""
<style>
.result-badge { display:inline-block; background:#eef2ff; color:#4338ca;
    font-size:13px; font-weight:600; padding:4px 14px; border-radius:20px;
    margin:8px 0 4px 0; border:1px solid #c7d2fe; }
.stats-strip { display:flex; gap:10px; margin:6px 0 12px 0; flex-wrap:wrap; }
.stat-box { flex:1; min-width:110px; background:#f8fafc; border:1px solid #e2e8f0;
    border-radius:8px; padding:8px 12px; }
.stat-val { font-size:15px; font-weight:700; color:#0f172a; }
.stat-lbl { font-size:10px; color:#94a3b8; text-transform:uppercase; letter-spacing:.05em; margin-top:2px; }

/* Company detail card */
.detail-card { background:#fff; border:1px solid #e2e8f0; border-radius:12px;
    padding:20px 24px; margin:12px 0; box-shadow:0 2px 8px rgba(99,102,241,0.06); }
.detail-name { font-size:22px; font-weight:800; color:#0f172a; margin-bottom:6px; }
.detail-meta { font-size:12px; color:#64748b; line-height:1.9; }
.detail-meta strong { color:#334155; font-size:11px; text-transform:uppercase; letter-spacing:.04em; }

.kpi-strip { display:flex; gap:6px; margin:10px 0; flex-wrap:wrap; }
.kpi-box { flex:1; min-width:90px; background:#f8fafc; border:1px solid #e2e8f0;
    border-radius:8px; padding:8px 10px; text-align:center; }
.kpi-val { font-size:16px; font-weight:700; color:#0f172a; line-height:1.2; }
.kpi-label { font-size:9px; color:#94a3b8; text-transform:uppercase; letter-spacing:.06em; margin-top:1px; }

.section-title { font-size:12px; font-weight:700; color:#334155; border-left:3px solid #6366f1;
    padding-left:8px; margin:16px 0 8px 0; text-transform:uppercase; letter-spacing:.04em; }
.filing-row { display:flex; align-items:center; gap:6px; padding:6px 12px;
    border:1px solid #e2e8f0; border-radius:8px; margin-bottom:4px; background:#fafbff; font-size:11px; }
.filing-row a { color:#6366f1; text-decoration:none; font-weight:600; }

.pnl-table { width:100%; border-collapse:collapse; font-size:11px; }
.pnl-table th { text-align:right; padding:4px 8px; font-weight:600; color:#64748b;
                border-bottom:2px solid #e2e8f0; font-size:10px; }
.pnl-table th:first-child { text-align:left; }
.pnl-table td { padding:3px 8px; text-align:right; color:#334155; border-bottom:1px solid #f1f5f9; }
.pnl-table td:first-child { text-align:left; color:#0f172a; }
.pnl-table tr.pnl-subtotal td { font-weight:700; border-bottom:2px solid #e2e8f0; background:#f8fafc; }
.pnl-table tr.pnl-total td { font-weight:800; border-bottom:2px solid #6366f1; background:#eef2ff; }
.pnl-table tr.pnl-spacer td { border:none; padding:2px 0; }

.struct-card { background:#fafbff; border:1px solid #e2e8f0; border-radius:8px;
    padding:8px 12px; margin-bottom:4px; font-size:12px; }
.struct-name { font-weight:700; color:#0f172a; }
.struct-detail { color:#64748b; font-size:11px; }
.struct-badge { display:inline-block; background:#eef2ff; color:#4338ca;
    padding:1px 6px; border-radius:4px; font-size:10px; font-weight:700; }
</style>
""", unsafe_allow_html=True)

topbar(active="Screener")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _conn():
    return get_connection()

def fmt_eur(v, unit="Auto"):
    """Format a euro value. unit: 'Auto', '€K', '€M'."""
    if pd.isna(v) or v is None:
        return "—"
    v = float(v)
    neg = v < 0
    a = abs(v)
    if unit == "€M":
        s = f"€{a/1e6:,.1f}M"
    elif unit == "€K":
        s = f"€{a/1e3:,.0f}K"
    else:  # Auto
        if a >= 1e9:   s = f"€{a/1e9:,.1f}B"
        elif a >= 1e6: s = f"€{a/1e6:,.1f}M"
        elif a >= 1e3: s = f"€{a/1e3:,.0f}K"
        else:          s = f"€{a:,.0f}"
    return f"-{s}" if neg else s

def fmt_pct(v):
    return f"{float(v):.1f}%" if pd.notna(v) else "\u2014"

def fmt_cbe(n):
    n = str(n).zfill(10)
    return f"{n[:4]}.{n[4:7]}.{n[7:]}"

PROVINCES = {
    "(all)": "", "Antwerpen": "2", "Oost-Vlaanderen": "9", "West-Vlaanderen": "8",
    "Vlaams-Brabant": "3", "Limburg": "35", "Brussels": "1",
    "Brabant Wallon": "14", "Hainaut": "7", "Li\u00e8ge": "4",
    "Luxembourg (BE)": "6", "Namur": "5",
}

ROLE_LABELS = {
    "fct:m10": "Director", "fct:m11": "Managing director",
    "fct:m12": "Chairman", "fct:m13": "Administrator",
    "fct:m14": "Secretary", "fct:m15": "Treasurer",
    "fct:m20": "Statutory auditor", "fct:m30": "Liquidator",
    "fct:m40": "Daily management",
}

PNL_LINES = [
    ("Revenue", "70", "row"), ("Other operating income", "74", "row"),
    ("Total operating income", "70/76A", "subtotal"), ("s1", None, "spacer"),
    ("Cost of goods sold", "60", "row"), ("Services & misc", "61", "row"),
    ("Personnel costs", "62", "row"), ("D&A", "630", "row"),
    ("Write-downs", "631/4", "row"), ("Provisions", "635/8", "row"),
    ("Other charges", "640/8", "row"), ("Total operating charges", "60/66A", "subtotal"),
    ("s2", None, "spacer"), ("EBIT", "9901", "subtotal"), ("s3", None, "spacer"),
    ("Financial income", "75", "row"), ("Financial charges", "65", "row"),
    ("Ordinary profit", "9902", "subtotal"), ("s4", None, "spacer"),
    ("Extraordinary income", "76", "row"), ("Extraordinary charges", "66", "row"),
    ("Profit before tax", "9903", "subtotal"), ("Taxes", "67/77", "row"),
    ("Net profit", "9904", "total"),
]
PNL_CODES = [c for _, c, _ in PNL_LINES if c]


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

SORT_OPTIONS = {
    "EBIT (high to low)": "fl.ebit DESC",
    "EBIT (low to high)": "fl.ebit ASC",
    "Revenue (high to low)": "fl.revenue DESC",
    "EBITDA (high to low)": "fl.ebitda DESC",
    "FTE (high to low)": "fl.fte_total DESC",
    "Name (A-Z)": "ci.name ASC",
}


@st.cache_data(ttl=60)
def run_query(nace_prefix, province_zip, ebit_min, ebit_max, ebitda_min, ebitda_max,
              rev_min, rev_max, fte_min, fte_max, margin_min, limit, sort_sql="fl.ebit DESC"):
    conn = _conn()
    conditions = []
    params = []
    if nace_prefix:
        conditions.append("ci.nace_code LIKE %s")
        params.append(f"{nace_prefix}%")
    if province_zip:
        conditions.append("ci.zipcode LIKE %s")
        params.append(f"{province_zip}%")
    if ebit_min:
        conditions.append("fl.ebit >= %s"); params.append(ebit_min)
    if ebit_max:
        conditions.append("fl.ebit <= %s"); params.append(ebit_max)
    if ebitda_min:
        conditions.append("fl.ebitda >= %s"); params.append(ebitda_min)
    if ebitda_max:
        conditions.append("fl.ebitda <= %s"); params.append(ebitda_max)
    if rev_min:
        conditions.append("fl.revenue >= %s"); params.append(rev_min)
    if rev_max:
        conditions.append("fl.revenue <= %s"); params.append(rev_max)
    if fte_min:
        conditions.append("fl.fte_total >= %s"); params.append(fte_min)
    if fte_max:
        conditions.append("fl.fte_total <= %s"); params.append(fte_max)
    if margin_min:
        conditions.append("fl.revenue > 0")
        conditions.append("(fl.ebitda / fl.revenue * 100) >= %s"); params.append(margin_min)

    where = (" AND " + " AND ".join(conditions)) if conditions else ""
    sql = f"""
        SELECT fl.enterprise_number AS "CBE", ci.name AS "Name",
               COALESCE(nl.description, ci.nace_code) AS "NACE",
               ci.city AS "City",
               fl.fiscal_year AS "FY", fl.revenue AS "Revenue",
               fl.ebit AS "EBIT", fl.ebitda AS "EBITDA",
               CASE WHEN fl.revenue > 0 THEN ROUND((fl.ebitda / fl.revenue * 100)::numeric, 1) END AS "Margin %%",
               fl.net_profit AS "Net profit", fl.fte_total AS "FTE"
        FROM financial_latest fl
        JOIN company_info ci ON ci.enterprise_number = fl.enterprise_number
        LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
        WHERE 1=1 {where}
        ORDER BY {sort_sql} LIMIT %s
    """
    params.append(limit)
    df = pd.read_sql_query(sql, conn, params=tuple(params))
    conn.close()
    return df


@st.cache_data(ttl=60)
def load_company_detail(cbe):
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
        SELECT fiscal_year, deposit_key, filing_model, revenue, ebit, da, ebitda, net_profit,
               equity, lt_financial_debt, cash, fte_total,
               CASE WHEN revenue > 0 THEN ROUND((ebitda / revenue * 100)::numeric, 1) END AS "ebitda_margin_pct"
        FROM financial_summary WHERE enterprise_number = %s ORDER BY fiscal_year
    """, conn, params=(cbe,))

    pnl = pd.DataFrame()
    if not hist.empty:
        placeholders = ",".join(["%s"] * len(PNL_CODES))
        pnl_raw = pd.read_sql_query(f"""
            SELECT fiscal_year, rubric_code, value FROM financial_data
            WHERE enterprise_number = %s AND period = 'N' AND rubric_code IN ({placeholders})
        """, conn, params=[cbe] + PNL_CODES)
        if not pnl_raw.empty:
            pnl = pnl_raw.pivot_table(index="rubric_code", columns="fiscal_year", values="value", aggfunc="first")

    admins = pd.read_sql_query(
        "SELECT * FROM administrator WHERE enterprise_number = %s ORDER BY mandate_start DESC", conn, params=(cbe,))
    pis = pd.read_sql_query(
        "SELECT * FROM participating_interest WHERE enterprise_number = %s ORDER BY name", conn, params=(cbe,))
    shareholders = pd.read_sql_query(
        "SELECT * FROM shareholder WHERE enterprise_number = %s ORDER BY name", conn, params=(cbe,))
    sb_pubs = pd.read_sql_query(
        "SELECT pub_date, pub_type, reference, pdf_url FROM staatsblad_publication "
        "WHERE enterprise_number = %s ORDER BY pub_date DESC", conn, params=(cbe,))

    conn.close()
    return header, hist, pnl, admins, pis, shareholders, sb_pubs


# ---------------------------------------------------------------------------
# FILTERS
# ---------------------------------------------------------------------------

c1, c2, c3, c4, c5, c6, c7, c8 = st.columns([1, 1, 1.2, 1.2, 1.2, 0.5, 1, 0.8])
nace_prefix = c1.text_input("NACE", placeholder="28, 461").strip()
province = c2.selectbox("Province", list(PROVINCES.keys()))
province_zip = PROVINCES[province]

eb1, eb2 = c3.columns(2)
ebit_min = eb1.number_input("EBIT \u2265", min_value=0, value=0, step=100_000, format="%d") or None
ebit_max = eb2.number_input("EBIT \u2264", min_value=0, value=0, step=500_000, format="%d") or None

ft1, ft2 = c4.columns(2)
fte_min = ft1.number_input("FTE \u2265", min_value=0, value=0, step=5, format="%d") or None
fte_max = ft2.number_input("FTE \u2264", min_value=0, value=0, step=10, format="%d") or None

rv1, rv2 = c5.columns(2)
rev_min = rv1.number_input("Rev \u2265", min_value=0, value=0, step=500_000, format="%d") or None
rev_max = rv2.number_input("Rev \u2264", min_value=0, value=0, step=500_000, format="%d") or None

limit = c6.select_slider("n", options=[50, 100, 250, 500, 1000], value=100)
sort_choice = c7.selectbox("Sort by", list(SORT_OPTIONS.keys()))
sort_sql = SORT_OPTIONS[sort_choice]
unit = c8.radio("Unit", ["Auto", "\u20acK", "\u20acM"], index=2, horizontal=True)

ebitda_min = ebitda_max = margin_min = None
with st.expander("More filters"):
    m1, m2, m3 = st.columns(3)
    ed1, ed2 = m1.columns(2)
    ebitda_min = ed1.number_input("EBITDA \u2265", min_value=0, value=0, step=100_000, format="%d") or None
    ebitda_max = ed2.number_input("EBITDA \u2264", min_value=0, value=0, step=500_000, format="%d") or None
    margin_min = m2.number_input("Margin \u2265 %", min_value=0.0, value=0.0, step=1.0) or None

# ---------------------------------------------------------------------------
# QUERY
# ---------------------------------------------------------------------------

df = run_query(nace_prefix, province_zip, ebit_min, ebit_max, ebitda_min, ebitda_max,
               rev_min, rev_max, fte_min, fte_max, margin_min, limit, sort_sql)

# ---------------------------------------------------------------------------
# SELECTED COMPANY (session state, also supports ?cbe= URL param)
# ---------------------------------------------------------------------------

if "selected_cbe" not in st.session_state:
    qp = st.query_params.get("cbe", "")
    if qp:
        st.session_state["selected_cbe"] = qp

selected_cbe = st.session_state.get("selected_cbe", "")

# ---------------------------------------------------------------------------
# COMPANY DRILL-DOWN  (shown above results when a company is selected)
# ---------------------------------------------------------------------------

if selected_cbe:
    c_back, c_fav, c_open = st.columns([3, 1, 2])
    with c_back:
        if st.button("← Back to results"):
            st.session_state.pop("selected_cbe", None)
            st.query_params.clear()
            st.rerun()
    with c_fav:
        favourite_star(selected_cbe, key="scr_fav")
    with c_open:
        if st.button("🏢 Open full profile →", type="primary", use_container_width=True):
            st.session_state["company_cbe"] = selected_cbe
            st.session_state["_clear_search"] = True
            st.switch_page("pages/2_company.py")

    header, hist, pnl, admins, pis, shareholders, sb_pubs = load_company_detail(selected_cbe)

    if not header:
        st.warning(f"CBE {selected_cbe} not found.")
    else:
        ent_num, status, start_date, jf_label, name, zipcode, muni, street, house, nace, nace_label = header
        addr = ", ".join(p for p in [street, house, f"{zipcode} {muni}"] if p) or "\u2014"
        badge = ('<span style="background:#dcfce7;color:#166534;padding:2px 10px;border-radius:12px;'
                 'font-size:11px;font-weight:700">\u25cf Active</span>' if status == "AC"
                 else f'<span style="background:#fee2e2;color:#991b1b;padding:2px 10px;border-radius:12px;'
                      f'font-size:11px;font-weight:700">\u25cf {status}</span>')

        st.markdown(f"""
        <div class="detail-card">
          <div class="detail-name">{name or fmt_cbe(selected_cbe)} {badge}</div>
          <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;">
            <div class="detail-meta"><strong>CBE</strong><br>{fmt_cbe(selected_cbe)}<br><strong>Legal form</strong><br>{jf_label or chr(8212)}</div>
            <div class="detail-meta"><strong>Founded</strong><br>{start_date or chr(8212)}<br><strong>Address</strong><br>{addr}</div>
            <div class="detail-meta"><strong>NACE</strong><br>{nace or chr(8212)}<br><strong>Sector</strong><br>{nace_label or chr(8212)}</div>
          </div>
        </div>
        """, unsafe_allow_html=True)

        if hist.empty:
            st.info("No financial data loaded yet.")
            st.info("Use the [DataSnoop web app](https://datasnoop.be) to load financials for this company.")
        else:
            # KPI strip
            latest = hist.iloc[-1]
            kpis = [
                (fmt_eur(latest.get("revenue")), "Revenue"),
                (fmt_eur(latest.get("ebitda")), "EBITDA"),
                (fmt_pct(latest.get("ebitda_margin_pct")), "Margin"),
                (fmt_eur(latest.get("net_profit")), "Net profit"),
                (fmt_eur(latest.get("equity")), "Equity"),
                (f"{latest['fte_total']:.0f}" if pd.notna(latest.get("fte_total")) else "\u2014", "FTE"),
            ]
            kpi_html = "".join(
                f'<div class="kpi-box"><div class="kpi-val">{v}</div><div class="kpi-label">{l}</div></div>'
                for v, l in kpis
            )
            st.markdown(f'<div class="kpi-strip">{kpi_html}</div>', unsafe_allow_html=True)

            t_fin, t_struct, t_legal = st.tabs(["\U0001f4b6 Financials", "\U0001f3e2 Structure", "\U0001f4dc Legal"])

            with t_fin:
                if not pnl.empty:
                    years = sorted(pnl.columns, reverse=True)
                    h = "<tr><th>Line item</th>" + "".join(f"<th>FY {y}</th>" for y in years) + "</tr>"
                    r = ""
                    for label, code, style in PNL_LINES:
                        if style == "spacer":
                            r += '<tr class="pnl-spacer"><td></td>' + "<td></td>" * len(years) + "</tr>"
                            continue
                        css = (f' class="pnl-{"total" if style == "total" else "subtotal"}"'
                               if style in ("subtotal", "total") else "")
                        cells = ""
                        has = False
                        for y in years:
                            val = pnl.at[code, y] if code in pnl.index and y in pnl.columns else None
                            if pd.notna(val):
                                has = True
                                cells += f"<td>{fmt_eur(val)}</td>"
                            else:
                                cells += "<td>\u2014</td>"
                        if has or style in ("subtotal", "total"):
                            r += f"<tr{css}><td>{label}</td>{cells}</tr>"
                    st.markdown(f'<table class="pnl-table">{h}{r}</table>', unsafe_allow_html=True)

                if "deposit_key" in hist.columns:
                    st.markdown('<div class="section-title">NBB filings</div>', unsafe_allow_html=True)
                    for _, row in hist.sort_values("fiscal_year", ascending=False).iterrows():
                        dk = row.get("deposit_key")
                        if dk:
                            url = f"https://ws.cbso.nbb.be/authentic/deposit/{dk}/accountingData"
                            st.markdown(
                                f'<div class="filing-row">\U0001f4c4 <strong>FY{row.get("fiscal_year","?")}</strong>'
                                f' <span class="struct-badge">{row.get("filing_model","")}</span>'
                                f' <a href="{url}" target="_blank">PDF \u2197</a></div>',
                                unsafe_allow_html=True)

            with t_struct:
                has_struct = not admins.empty or not pis.empty or not shareholders.empty
                if not has_struct:
                    if st.button("\U0001f3e2 Load structure", type="primary", key="load_s"):
                        with st.spinner("Fetching..."):
                            try:
                                from nbb_client import NBBClient
                                from nbb_loader import store_structure_data
                                client = NBBClient()
                                filing = client.get_latest_filing_json(selected_cbe)
                                if filing:
                                    conn2 = _conn()
                                    store_structure_data(conn2, filing, selected_cbe,
                                                        filing.get("ReferenceNumber", ""), None)
                                    conn2.close()
                                    st.cache_data.clear()
                                    st.rerun()
                                else:
                                    st.warning("No filing data available.")
                            except Exception as e:
                                st.error(str(e))
                else:
                    if not shareholders.empty:
                        st.markdown('<div class="section-title">Shareholders</div>', unsafe_allow_html=True)
                        for _, sh in shareholders.drop_duplicates(subset=["name"]).iterrows():
                            st.markdown(f'<div class="struct-card"><span class="struct-name">{sh["name"]}</span></div>',
                                        unsafe_allow_html=True)
                    if not pis.empty:
                        st.markdown('<div class="section-title">Subsidiaries</div>', unsafe_allow_html=True)
                        for _, pi in pis.drop_duplicates(subset=["name"]).iterrows():
                            country = pi.get("country") or ""
                            badge2 = f' <span class="struct-badge">{country}</span>' if country else ""
                            st.markdown(
                                f'<div class="struct-card"><span class="struct-name">{pi["name"]}</span>{badge2}</div>',
                                unsafe_allow_html=True)
                    if not admins.empty:
                        st.markdown('<div class="section-title">Board & administrators</div>', unsafe_allow_html=True)
                        for _, ad in admins.drop_duplicates(subset=["name", "role"]).iterrows():
                            role = ROLE_LABELS.get(ad.get("role", ""), ad.get("role", ""))
                            st.markdown(
                                f'<div class="struct-card"><span class="struct-name">{ad["name"]}</span>'
                                f' <span class="struct-badge">{role}</span></div>',
                                unsafe_allow_html=True)

            with t_legal:
                if sb_pubs.empty:
                    if st.button("\U0001f4f0 Load Staatsblad", type="primary", key="load_sb"):
                        with st.spinner("Fetching..."):
                            try:
                                from staatsblad import load_staatsblad as _lsb
                                conn2 = _conn()
                                cnt = _lsb(conn2, selected_cbe)
                                conn2.close()
                                if cnt:
                                    st.cache_data.clear()
                                    st.rerun()
                                else:
                                    st.warning("No publications found.")
                            except Exception as e:
                                st.error(str(e))
                else:
                    PUB_ICONS = {
                        "ONTSLAGEN - BENOEMINGEN": "\U0001f464", "KAPITAAL - AANDELEN": "\U0001f4b0",
                        "MAATSCHAPPELIJKE ZETEL": "\U0001f4cd", "DOEL": "\U0001f3af", "DIVERSEN": "\U0001f4cb",
                    }
                    for _, pub in sb_pubs.iterrows():
                        ptype = pub["pub_type"] or "Publication"
                        icon = PUB_ICONS.get(ptype, "\U0001f4c4")
                        pdf = pub["pdf_url"]
                        pdf_link = (f' <a href="https://www.ejustice.just.fgov.be{pdf}" target="_blank">PDF \u2197</a>'
                                    if pdf else "")
                        st.markdown(
                            f'<div class="filing-row">{icon} <strong>{pub["pub_date"]}</strong> {ptype}{pdf_link}</div>',
                            unsafe_allow_html=True)
                    st.caption(f"{len(sb_pubs)} publication(s)")

    st.markdown("---")

# ---------------------------------------------------------------------------
# RESULTS TABLE
# ---------------------------------------------------------------------------

if df.empty:
    st.info("No companies match the current filters.")
    st.stop()

# Badge
st.markdown(f'<div class="result-badge">{len(df):,} companies</div>', unsafe_allow_html=True)

# Stats strip
_rev = pd.to_numeric(df["Revenue"], errors="coerce")
_ebit = pd.to_numeric(df["EBIT"], errors="coerce")
_ebitda = pd.to_numeric(df["EBITDA"], errors="coerce")
_margin = pd.to_numeric(df["Margin %"], errors="coerce")
_fte = pd.to_numeric(df["FTE"], errors="coerce")

stats = [
    (fmt_eur(_rev.sum()), "Total Revenue"),
    (fmt_eur(_ebit.median()), "Median EBIT"),
    (fmt_eur(_ebitda.median()), "Median EBITDA"),
    (fmt_pct(_margin.median()), "Median Margin"),
    (f"{_fte.median():.0f}" if _fte.notna().any() else "\u2014", "Median FTE"),
    (f"{_fte.sum():,.0f}" if _fte.notna().any() else "\u2014", "Total FTE"),
]
stats_html = "".join(
    f'<div class="stat-box"><div class="stat-val">{v}</div><div class="stat-lbl">{l}</div></div>'
    for v, l in stats
)
st.markdown(f'<div class="stats-strip">{stats_html}</div>', unsafe_allow_html=True)

# Build display DataFrame
def _trunc(s, n=45):
    s = str(s) if pd.notna(s) else "\u2014"
    return s[:n] + "\u2026" if len(s) > n else s

display_df = pd.DataFrame({
    "Company": df["Name"].fillna(df["CBE"].astype(str)),
    "Sector": df["NACE"].apply(_trunc),
    "City": df["City"].fillna("\u2014"),
    "FY": df["FY"].fillna("").astype(str).str[:4],
    "Revenue": df["Revenue"].apply(lambda v: fmt_eur(v, unit)),
    "EBIT": df["EBIT"].apply(lambda v: fmt_eur(v, unit)),
    "EBITDA": df["EBITDA"].apply(lambda v: fmt_eur(v, unit)),
    "Margin": df["Margin %"].apply(fmt_pct),
    "Net profit": df["Net profit"].apply(lambda v: fmt_eur(v, unit)),
    "FTE": df["FTE"].apply(lambda v: f"{v:.0f}" if pd.notna(v) else "\u2014"),
})

event = st.dataframe(
    display_df,
    use_container_width=True,
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    column_config={
        "Company": st.column_config.TextColumn("Company", width="medium"),
        "Sector": st.column_config.TextColumn("Sector", width="large"),
        "City": st.column_config.TextColumn("City", width="small"),
        "FY": st.column_config.TextColumn("FY", width=45),
        "Revenue": st.column_config.TextColumn("Revenue", width="small"),
        "EBIT": st.column_config.TextColumn("EBIT", width="small"),
        "EBITDA": st.column_config.TextColumn("EBITDA", width="small"),
        "Margin": st.column_config.TextColumn("Margin", width="small"),
        "Net profit": st.column_config.TextColumn("Net profit", width="small"),
        "FTE": st.column_config.TextColumn("FTE", width=50),
    },
)

# Handle row selection → update session state
if event.selection.rows:
    new_cbe = str(df.iloc[event.selection.rows[0]]["CBE"]).zfill(10)
    if new_cbe != selected_cbe:
        st.session_state["selected_cbe"] = new_cbe
        st.rerun()

# Export
excel_buf = io.BytesIO()
df.to_excel(excel_buf, index=False)
st.download_button(
    "\U0001f4e5 Export Excel", data=excel_buf.getvalue(),
    file_name="screener.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
