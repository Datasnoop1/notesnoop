"""Compare companies — side-by-side financials with aggregate totals."""

import os
import sys

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
from components import topbar
from db import get_connection

load_dotenv()

st.set_page_config(page_title="Compare \u00b7 Belgian Co DB", layout="wide")

topbar(active="Compare")

st.markdown("""
<style>
.page-title { font-size: 28px; font-weight: 800; color: #0f172a; margin-bottom: 2px; }
.page-sub   { font-size: 14px; color: #64748b; margin-bottom: 0; }
.comp-table { width:100%; border-collapse:collapse; font-size:13px; }
.comp-table th { text-align:right; padding:8px 12px; font-weight:600; color:#64748b;
                 border-bottom:2px solid #e2e8f0; font-size:12px; }
.comp-table th:first-child { text-align:left; }
.comp-table td { padding:7px 12px; text-align:right; color:#334155; border-bottom:1px solid #f1f5f9; }
.comp-table td:first-child { text-align:left; color:#0f172a; font-weight:600; }
.comp-table tr.comp-header td { font-weight:700; background:#f8fafc; border-bottom:2px solid #e2e8f0; }
.comp-table tr.comp-total td { font-weight:800; background:#eef2ff; border-top:2px solid #6366f1; }
.comp-table tr.comp-spacer td { border:none; padding:4px 0; }
</style>
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


def fmt_pct(v):
    return f"{float(v):.1f}%" if pd.notna(v) else "\u2014"


def fmt_num(v):
    if pd.isna(v) or v is None:
        return "\u2014"
    return f"{float(v):,.0f}"


def fmt_cbe(n):
    n = str(n).zfill(10)
    return f"{n[:4]}.{n[4:7]}.{n[7:]}"


@st.cache_data(ttl=60)
def search_company(query):
    query = query.strip()
    conn = _conn()
    cur = conn.cursor()
    if query.replace(".", "").isdigit():
        cbe = query.replace(".", "")
        cur.execute(
            "SELECT entity_number, denomination FROM denomination "
            "WHERE entity_number = %s AND type_of_denomination = '001' LIMIT 1", (cbe,))
        rows = cur.fetchall()
        if not rows:
            rows = [(cbe, cbe)]
    else:
        cur.execute(
            "SELECT entity_number, denomination FROM denomination "
            "WHERE denomination ILIKE %s AND type_of_denomination = '001' "
            "ORDER BY denomination LIMIT 10", (f"%{query}%",))
        rows = cur.fetchall()
    conn.close()
    return rows


@st.cache_data(ttl=60)
def load_latest_financials(cbe):
    """Load latest-year financial summary for a company."""
    conn = _conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT fl.*, d.denomination AS name
        FROM financial_latest fl
        LEFT JOIN (
            SELECT entity_number, denomination FROM denomination
            WHERE type_of_denomination = '001' AND language = '2'
            GROUP BY entity_number, denomination
        ) d ON d.entity_number = fl.enterprise_number
        WHERE fl.enterprise_number = %s
    """, (cbe,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    cols = ["enterprise_number", "fiscal_year", "filing_model",
            "revenue", "ebit", "da", "ebitda", "net_profit",
            "equity", "lt_financial_debt", "st_financial_debt",
            "cash", "total_assets", "fte_total", "personnel_costs", "name"]
    return dict(zip(cols, row))


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

st.markdown(
    '<p class="page-title">\u2696\ufe0f Compare</p>'
    '<p class="page-sub">Side-by-side company financials with aggregate totals</p>',
    unsafe_allow_html=True,
)

# Company selection
st.markdown("#### Add companies to compare")
st.caption("Search by name or CBE number. Add up to 10 companies.")

if "compare_cbes" not in st.session_state:
    st.session_state.compare_cbes = []

col_search, col_add = st.columns([3, 1])
with col_search:
    search_q = st.text_input("Search", placeholder="e.g. Automation or 0403101811", label_visibility="collapsed")
with col_add:
    add_clicked = st.button("\u2795 Add", type="primary", use_container_width=True)

if add_clicked and search_q.strip():
    results = search_company(search_q.strip())
    if results:
        cbe = results[0][0]
        if cbe not in st.session_state.compare_cbes:
            st.session_state.compare_cbes.append(cbe)
    else:
        st.warning("Company not found.")

# Show selected companies with remove buttons
if st.session_state.compare_cbes:
    companies_data = []
    cols = st.columns(min(len(st.session_state.compare_cbes), 5))
    to_remove = None
    for i, cbe in enumerate(st.session_state.compare_cbes):
        data = load_latest_financials(cbe)
        if data:
            companies_data.append(data)
            with cols[i % 5]:
                name = data.get("name") or fmt_cbe(cbe)
                st.markdown(f"**{name}**")
                st.caption(f"FY{data['fiscal_year']} \u00b7 {fmt_cbe(cbe)}")
                if st.button("\u274c", key=f"rm_{cbe}"):
                    to_remove = cbe

    if to_remove:
        st.session_state.compare_cbes.remove(to_remove)
        st.rerun()

    if len(companies_data) < 2:
        st.info("Add at least 2 companies to compare.")
        st.stop()

    # ---------------------------------------------------------------------------
    # Comparison table
    # ---------------------------------------------------------------------------

    METRICS = [
        ("Revenue",          "revenue",          "eur"),
        ("EBIT",             "ebit",             "eur"),
        ("D&A",              "da",               "eur"),
        ("EBITDA",           "ebitda",           "eur"),
        ("Net profit",       "net_profit",       "eur"),
        ("spacer1",          None,               "spacer"),
        ("Equity",           "equity",           "eur"),
        ("LT financial debt","lt_financial_debt","eur"),
        ("ST financial debt","st_financial_debt","eur"),
        ("Cash",             "cash",             "eur"),
        ("Total assets",     "total_assets",     "eur"),
        ("spacer2",          None,               "spacer"),
        ("FTE",              "fte_total",        "num"),
        ("Personnel costs",  "personnel_costs",  "eur"),
    ]

    # Build comparison data
    names = [d.get("name") or fmt_cbe(d["enterprise_number"]) for d in companies_data]

    # Header row
    header = "<tr><th>Metric</th>"
    for name in names:
        # Truncate long names
        short = name[:20] + "\u2026" if len(name) > 20 else name
        header += f"<th>{short}</th>"
    header += "<th style='color:#4338ca;'>Combined</th></tr>"

    # Data rows
    rows_html = ""
    for label, key, fmt_type in METRICS:
        if fmt_type == "spacer":
            rows_html += '<tr class="comp-spacer"><td></td>' + "<td></td>" * (len(companies_data) + 1) + "</tr>"
            continue

        cells = ""
        total = 0.0
        all_none = True
        for d in companies_data:
            val = d.get(key)
            if pd.notna(val) and val is not None:
                all_none = False
                total += float(val)
            if fmt_type == "eur":
                cells += f"<td>{fmt_eur(val)}</td>"
            elif fmt_type == "pct":
                cells += f"<td>{fmt_pct(val)}</td>"
            else:
                cells += f"<td>{fmt_num(val)}</td>"

        # Combined column
        if all_none:
            combined = "\u2014"
        elif fmt_type == "eur":
            combined = fmt_eur(total)
        else:
            combined = fmt_num(total)

        rows_html += f"<tr><td>{label}</td>{cells}<td style='font-weight:700;color:#4338ca'>{combined}</td></tr>"

    # Derived metrics row
    rows_html += '<tr class="comp-spacer"><td></td>' + "<td></td>" * (len(companies_data) + 1) + "</tr>"

    # EBITDA margin per company + combined
    cells_margin = ""
    total_rev = sum(float(d.get("revenue") or 0) for d in companies_data)
    total_ebitda = sum(float(d.get("ebitda") or 0) for d in companies_data)
    for d in companies_data:
        rev = d.get("revenue")
        ebitda = d.get("ebitda")
        if pd.notna(rev) and pd.notna(ebitda) and float(rev) > 0:
            cells_margin += f"<td>{float(ebitda)/float(rev)*100:.1f}%</td>"
        else:
            cells_margin += "<td>\u2014</td>"
    combined_margin = f"{total_ebitda/total_rev*100:.1f}%" if total_rev > 0 else "\u2014"
    rows_html += f'<tr class="comp-header"><td>EBITDA margin</td>{cells_margin}<td style="font-weight:700;color:#4338ca">{combined_margin}</td></tr>'

    # Revenue per FTE
    cells_rpf = ""
    total_fte = sum(float(d.get("fte_total") or 0) for d in companies_data)
    for d in companies_data:
        rev = d.get("revenue")
        fte = d.get("fte_total")
        if pd.notna(rev) and pd.notna(fte) and float(fte) > 0:
            cells_rpf += f"<td>{fmt_eur(float(rev)/float(fte))}</td>"
        else:
            cells_rpf += "<td>\u2014</td>"
    combined_rpf = fmt_eur(total_rev / total_fte) if total_fte > 0 else "\u2014"
    rows_html += f'<tr><td>Revenue / FTE</td>{cells_rpf}<td style="font-weight:700;color:#4338ca">{combined_rpf}</td></tr>'

    st.markdown(f'<table class="comp-table">{header}{rows_html}</table>', unsafe_allow_html=True)

    # Export
    st.markdown("---")
    export_rows = []
    for label, key, fmt_type in METRICS:
        if fmt_type == "spacer":
            continue
        row = {"Metric": label}
        for i, d in enumerate(companies_data):
            row[names[i]] = d.get(key)
        total = sum(float(d.get(key) or 0) for d in companies_data)
        row["Combined"] = total
        export_rows.append(row)
    export_df = pd.DataFrame(export_rows)

    import io
    buf = io.BytesIO()
    export_df.to_excel(buf, index=False)
    st.download_button(
        "\U0001f4e5 Download comparison Excel",
        data=buf.getvalue(),
        file_name="company_comparison.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

else:
    st.info("Search and add companies above to start comparing.")
