"""Stats — aggregate analytics across the entire database."""

import os
import sys

import altair as alt
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
from components import topbar
from db import get_connection

load_dotenv()

st.set_page_config(page_title="Stats \u00b7 Belgian Co DB", layout="wide")

st.markdown("""
<style>
.kpi-strip { display:flex; gap:8px; margin:8px 0 16px 0; flex-wrap:wrap; }
.kpi-box { flex:1; min-width:110px; background:#f8fafc; border:1px solid #e2e8f0;
    border-radius:10px; padding:10px 14px; }
.kpi-val { font-size:18px; font-weight:800; color:#0f172a; line-height:1.2; }
.kpi-sub { font-size:10px; color:#94a3b8; text-transform:uppercase; letter-spacing:.05em; margin-top:3px; }
.section-hdr { font-size:13px; font-weight:800; color:#0f172a; border-left:3px solid #6366f1;
    padding-left:9px; margin:24px 0 10px 0; text-transform:uppercase; letter-spacing:.04em; }
.filter-bar { background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px;
    padding:10px 16px; margin-bottom:16px; }
</style>
""", unsafe_allow_html=True)

topbar(active="Stats")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _conn():
    return get_connection()

PROVINCE_SQL = """
    CASE
      WHEN ci.zipcode BETWEEN '1000' AND '1299' THEN 'Brussels'
      WHEN ci.zipcode BETWEEN '1300' AND '1499' THEN 'Brabant Wallon'
      WHEN ci.zipcode BETWEEN '1500' AND '1999' THEN 'Vlaams-Brabant'
      WHEN ci.zipcode BETWEEN '2000' AND '2999' THEN 'Antwerpen'
      WHEN ci.zipcode BETWEEN '3000' AND '3499' THEN 'Vlaams-Brabant'
      WHEN ci.zipcode BETWEEN '3500' AND '3999' THEN 'Limburg'
      WHEN ci.zipcode BETWEEN '4000' AND '4999' THEN 'Liège'
      WHEN ci.zipcode BETWEEN '5000' AND '5999' THEN 'Namur'
      WHEN ci.zipcode BETWEEN '6000' AND '6599' THEN 'Hainaut'
      WHEN ci.zipcode BETWEEN '6600' AND '6999' THEN 'Luxembourg'
      WHEN ci.zipcode BETWEEN '7000' AND '7999' THEN 'Hainaut'
      WHEN ci.zipcode BETWEEN '8000' AND '8999' THEN 'West-Vlaanderen'
      WHEN ci.zipcode BETWEEN '9000' AND '9999' THEN 'Oost-Vlaanderen'
      ELSE 'Other'
    END
"""

def fmt_bn(v):
    if pd.isna(v): return "—"
    v = float(v)
    neg = v < 0
    a = abs(v)
    if a >= 1e9:   s = f"€{a/1e9:,.1f}B"
    elif a >= 1e6: s = f"€{a/1e6:,.0f}M"
    else:          s = f"€{a/1e3:,.0f}K"
    return f"-{s}" if neg else s

CHART_COLORS = ["#6366f1", "#10b981", "#f59e0b", "#ef4444", "#3b82f6",
                "#8b5cf6", "#06b6d4", "#ec4899", "#84cc16", "#f97316"]

# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

with st.container():
    st.markdown('<div class="filter-bar">', unsafe_allow_html=True)
    f1, f2, f3 = st.columns([2, 2, 2])
    year_range = f1.select_slider(
        "Fiscal year range", options=list(range(2021, 2026)),
        value=(2021, 2024), key="stats_years"
    )
    province_filter = f2.selectbox(
        "Province", ["All provinces", "Brussels", "Antwerpen", "Oost-Vlaanderen",
                     "West-Vlaanderen", "Vlaams-Brabant", "Limburg", "Liège",
                     "Hainaut", "Namur", "Brabant Wallon", "Luxembourg"],
        key="stats_prov"
    )
    nace_top_n = f3.select_slider("Top N sectors", options=[5, 10, 15, 20], value=10, key="stats_nace_n")
    st.markdown('</div>', unsafe_allow_html=True)

y_min, y_max = year_range
prov_clause = f"AND {PROVINCE_SQL} = '{province_filter}'" if province_filter != "All provinces" else ""

# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

@st.cache_data(ttl=120)
def load_overview(y_min, y_max, prov_clause):
    conn = _conn()
    # Aggregate totals
    cur = conn.cursor()
    cur.execute(f"""
        SELECT
            COUNT(DISTINCT fl.enterprise_number)  AS n_companies,
            SUM(fl.revenue)                        AS total_rev,
            SUM(fl.ebitda)                         AS total_ebitda,
            SUM(fl.fte_total)                      AS total_fte,
            AVG(fl.fte_total)                      AS avg_fte,
            SUM(COALESCE(fl.lt_financial_debt,0) + COALESCE(fl.st_financial_debt,0)
                - COALESCE(fl.cash,0))             AS total_nfd
        FROM financial_latest fl
        JOIN company_info ci ON ci.enterprise_number = fl.enterprise_number
        WHERE 1=1 {prov_clause}
    """)
    row = cur.fetchone()
    # Median margin computed in Python (SQLite has no MEDIAN)
    margins_raw = pd.read_sql_query(f"""
        SELECT CAST(fl.ebitda AS REAL) / fl.revenue * 100 AS "margin"
        FROM financial_latest fl
        JOIN company_info ci ON ci.enterprise_number = fl.enterprise_number
        WHERE fl.revenue > 500000 AND fl.ebitda IS NOT NULL {prov_clause}
    """, conn)
    conn.close()
    med_margin = float(margins_raw["margin"].median()) if not margins_raw.empty else None
    # Return 7-tuple: (n_co, tot_rev, tot_ebitda, med_margin, tot_fte, avg_fte, tot_nfd)
    return (row[0], row[1], row[2], med_margin, row[3], row[4], row[5])


@st.cache_data(ttl=120)
def load_evolution(y_min, y_max, prov_clause):
    """Load financial evolution. Uses financial_latest for latest-year slice,
    and a light aggregated query on financial_summary for multi-year totals."""
    conn = _conn()
    # Aggregated totals by year — uses materialized financial_by_year (fast)
    agg = pd.read_sql_query(f"""
        SELECT
            fy.fiscal_year,
            COUNT(DISTINCT fy.enterprise_number)              AS "companies",
            SUM(fy.revenue)/1e6                              AS "revenue_m",
            SUM(fy.ebitda)/1e6                               AS "ebitda_m",
            SUM(fy.ebit)/1e6                                 AS "ebit_m",
            SUM(fy.net_profit)/1e6                           AS "net_profit_m",
            SUM(COALESCE(fy.lt_financial_debt,0)+COALESCE(fy.st_financial_debt,0)
                -COALESCE(fy.cash,0))/1e6                    AS "nfd_m"
        FROM financial_by_year fy
        JOIN company_info ci ON ci.enterprise_number = fy.enterprise_number
        WHERE fy.fiscal_year BETWEEN %s AND %s
        {prov_clause.replace('fl.', 'fy.') if prov_clause else ''}
        GROUP BY fy.fiscal_year
        ORDER BY fy.fiscal_year
    """, conn, params=(y_min, y_max))

    # Per-company margin & leverage for median computation
    margins = pd.read_sql_query(f"""
        SELECT
            fy.fiscal_year,
            CASE WHEN fy.revenue > 0 THEN fy.ebitda / fy.revenue * 100 END AS "ebitda_margin",
            CASE WHEN fy.revenue > 0 THEN fy.ebit   / fy.revenue * 100 END AS "ebit_margin",
            CASE WHEN fy.ebitda  > 0
                 THEN (COALESCE(fy.lt_financial_debt,0)+COALESCE(fy.st_financial_debt,0)
                       -COALESCE(fy.cash,0)) / fy.ebitda END                AS "nfd_ebitda"
        FROM financial_by_year fy
        JOIN company_info ci ON ci.enterprise_number = fy.enterprise_number
        WHERE fy.fiscal_year BETWEEN %s AND %s
        {prov_clause.replace('fl.', 'fy.') if prov_clause else ''}
    """, conn, params=(y_min, y_max))
    conn.close()

    if agg.empty:
        return pd.DataFrame()

    med = margins.groupby("fiscal_year").agg(
        med_ebitda_margin=("ebitda_margin", "median"),
        med_ebit_margin=("ebit_margin", "median"),
        med_nfd_ebitda=("nfd_ebitda", "median"),
    ).reset_index()

    return agg.merge(med, on="fiscal_year", how="left")


@st.cache_data(ttl=120)
def load_nace_stats(y_min, y_max, prov_clause, top_n):
    """Load per-company latest data, group by 2-digit NACE, compute medians in Python."""
    conn = _conn()
    raw = pd.read_sql_query(f"""
        SELECT
            SUBSTR(ci.nace_code, 1, 2)                                    AS "nace2",
            COALESCE(nl.description, SUBSTR(ci.nace_code,1,2))            AS "sector",
            fl.enterprise_number,
            fl.revenue, fl.ebitda, fl.fte_total,
            COALESCE(fl.lt_financial_debt,0)+COALESCE(fl.st_financial_debt,0)
                -COALESCE(fl.cash,0)                                      AS "nfd"
        FROM financial_latest fl
        JOIN company_info ci ON ci.enterprise_number = fl.enterprise_number
        LEFT JOIN nace_lookup nl ON nl.nace_code = SUBSTR(ci.nace_code,1,2)
        WHERE ci.nace_code IS NOT NULL
        {prov_clause}
    """, conn)
    conn.close()
    if raw.empty:
        return pd.DataFrame()

    raw["margin"] = raw.apply(
        lambda r: r["ebitda"] / r["revenue"] * 100 if pd.notna(r["revenue"]) and r["revenue"] > 0 else None, axis=1)
    raw["nfd_ebitda"] = raw.apply(
        lambda r: r["nfd"] / r["ebitda"] if pd.notna(r["ebitda"]) and r["ebitda"] > 0 else None, axis=1)

    agg = raw.groupby(["nace2", "sector"]).agg(
        companies=("enterprise_number", "nunique"),
        revenue_m=("revenue", lambda x: x.sum() / 1e6),
        ebitda_m=("ebitda", lambda x: x.sum() / 1e6),
        med_margin=("margin", "median"),
        med_fte=("fte_total", "median"),
        med_nfd_ebitda=("nfd_ebitda", "median"),
    ).reset_index()

    agg = agg[agg["companies"] >= 10].sort_values("companies", ascending=False).head(top_n)
    return agg


@st.cache_data(ttl=120)
def load_province_stats(y_min, y_max):
    """Load per-company province data, compute medians in Python."""
    conn = _conn()
    raw = pd.read_sql_query(f"""
        SELECT
            {PROVINCE_SQL}                                                 AS "province",
            fl.enterprise_number,
            fl.revenue, fl.ebitda, fl.fte_total
        FROM financial_latest fl
        JOIN company_info ci ON ci.enterprise_number = fl.enterprise_number
        WHERE ci.zipcode IS NOT NULL AND {PROVINCE_SQL} != 'Other'
    """, conn)
    conn.close()
    if raw.empty:
        return pd.DataFrame()

    raw["margin"] = raw.apply(
        lambda r: r["ebitda"] / r["revenue"] * 100 if pd.notna(r["revenue"]) and r["revenue"] > 0 else None, axis=1)

    agg = raw.groupby("province").agg(
        companies=("enterprise_number", "nunique"),
        revenue_m=("revenue", lambda x: x.sum() / 1e6),
        ebitda_m=("ebitda", lambda x: x.sum() / 1e6),
        med_margin=("margin", "median"),
        total_fte=("fte_total", "sum"),
        med_fte=("fte_total", "median"),
    ).reset_index().sort_values("companies", ascending=False)
    return agg


@st.cache_data(ttl=120)
def load_nfd_by_nace(y_min, y_max, prov_clause, top_n):
    """Load per-company annual data by sector, compute median NFD/EBITDA in Python."""
    conn = _conn()
    raw = pd.read_sql_query(f"""
        SELECT
            fy.fiscal_year,
            SUBSTR(ci.nace_code,1,2)                                      AS "nace2",
            COALESCE(nl.description, SUBSTR(ci.nace_code,1,2))            AS "sector",
            fy.enterprise_number,
            fy.ebitda,
            COALESCE(fy.lt_financial_debt,0)+COALESCE(fy.st_financial_debt,0)
                -COALESCE(fy.cash,0)                                      AS "nfd"
        FROM financial_by_year fy
        JOIN company_info ci ON ci.enterprise_number = fy.enterprise_number
        LEFT JOIN nace_lookup nl ON nl.nace_code = SUBSTR(ci.nace_code,1,2)
        WHERE fy.fiscal_year BETWEEN %s AND %s
          AND ci.nace_code IS NOT NULL
          {prov_clause.replace('fl.', 'fy.') if prov_clause else ''}
    """, conn, params=(y_min, y_max))
    conn.close()
    if raw.empty:
        return pd.DataFrame()

    raw["nfd_ebitda"] = raw.apply(
        lambda r: r["nfd"] / r["ebitda"] if pd.notna(r["ebitda"]) and r["ebitda"] > 0 else None, axis=1)

    agg = raw.groupby(["fiscal_year", "nace2", "sector"]).agg(
        med_nfd_ebitda=("nfd_ebitda", "median"),
        n=("enterprise_number", "nunique"),
    ).reset_index()

    agg = agg[agg["n"] >= 20]
    top_sectors = (agg.groupby("nace2")["n"].sum()
                   .nlargest(min(top_n, 8)).index.tolist())
    return agg[agg["nace2"].isin(top_sectors)].copy()


@st.cache_data(ttl=120)
def load_margin_distribution(y_min, y_max, prov_clause):
    conn = _conn()
    df = pd.read_sql_query(f"""
        SELECT
            ROUND((fl.ebitda / fl.revenue * 100)::numeric) AS "margin_bucket",
            COUNT(*) AS "n"
        FROM financial_latest fl
        JOIN company_info ci ON ci.enterprise_number = fl.enterprise_number
        WHERE fl.revenue > 100000
          AND fl.ebitda / fl.revenue * 100 BETWEEN -50 AND 80
          {prov_clause}
        GROUP BY margin_bucket
        ORDER BY margin_bucket
    """, conn)
    conn.close()
    return df


@st.cache_data(ttl=120)
def load_size_distribution(prov_clause):
    conn = _conn()
    df = pd.read_sql_query(f"""
        SELECT
            CASE
                WHEN fl.revenue < 1e6    THEN '< €1M'
                WHEN fl.revenue < 5e6    THEN '€1–5M'
                WHEN fl.revenue < 10e6   THEN '€5–10M'
                WHEN fl.revenue < 25e6   THEN '€10–25M'
                WHEN fl.revenue < 50e6   THEN '€25–50M'
                WHEN fl.revenue < 100e6  THEN '€50–100M'
                WHEN fl.revenue < 250e6  THEN '€100–250M'
                ELSE '> €250M'
            END AS "size_bucket",
            CASE
                WHEN fl.revenue < 1e6    THEN 1
                WHEN fl.revenue < 5e6    THEN 2
                WHEN fl.revenue < 10e6   THEN 3
                WHEN fl.revenue < 25e6   THEN 4
                WHEN fl.revenue < 50e6   THEN 5
                WHEN fl.revenue < 100e6  THEN 6
                WHEN fl.revenue < 250e6  THEN 7
                ELSE 8
            END AS "sort_key",
            COUNT(*) AS "companies",
            SUM(fl.revenue)/1e6 AS "revenue_m"
        FROM financial_latest fl
        JOIN company_info ci ON ci.enterprise_number = fl.enterprise_number
        WHERE fl.revenue > 0 {prov_clause}
        GROUP BY size_bucket, sort_key
        ORDER BY sort_key
    """, conn)
    conn.close()
    return df


# ---------------------------------------------------------------------------
# Load all data
# ---------------------------------------------------------------------------

ov       = load_overview(y_min, y_max, prov_clause)
evo      = load_evolution(y_min, y_max, prov_clause)
nace_df  = load_nace_stats(y_min, y_max, prov_clause, nace_top_n)
prov_df  = load_province_stats(y_min, y_max)
nfd_nace = load_nfd_by_nace(y_min, y_max, prov_clause, nace_top_n)
margin_d = load_margin_distribution(y_min, y_max, prov_clause)
size_d   = load_size_distribution(prov_clause)

n_co, tot_rev, tot_ebitda, med_margin, tot_fte, avg_fte, tot_nfd = ov

# ---------------------------------------------------------------------------
# OVERVIEW KPIs
# ---------------------------------------------------------------------------

st.markdown('<div class="section-hdr">Database overview</div>', unsafe_allow_html=True)
kpis = [
    (f"{int(n_co):,}", "Companies"),
    (fmt_bn(tot_rev), "Total revenue"),
    (fmt_bn(tot_ebitda), "Total EBITDA"),
    (f"{med_margin:.1f}%" if med_margin is not None else "—", "Median margin"),
    (f"{int(tot_fte or 0):,}", "Total FTE"),
    (f"{avg_fte:.0f}" if avg_fte else "—", "Avg FTE / co"),
    (fmt_bn(tot_nfd), "Total NFD"),
]
kpi_html = "".join(
    f'<div class="kpi-box"><div class="kpi-val">{v}</div>'
    f'<div class="kpi-sub">{l}</div></div>'
    for v, l in kpis
)
st.markdown(f'<div class="kpi-strip">{kpi_html}</div>', unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# FINANCIAL EVOLUTION
# ---------------------------------------------------------------------------

if not evo.empty:
    st.markdown('<div class="section-hdr">Financial evolution by year</div>', unsafe_allow_html=True)

    tab_abs, tab_margin, tab_nfd = st.tabs(
        ["💶 Revenue & EBITDA", "📊 Margins", "⚖️ Leverage (NFD)"]
    )

    with tab_abs:
        col_l, col_r = st.columns(2)

        # Revenue + EBITDA bar
        rev_ebitda = evo[["fiscal_year", "revenue_m", "ebitda_m"]].copy()
        rev_ebitda["fiscal_year"] = rev_ebitda["fiscal_year"].astype(str)
        rev_long = rev_ebitda.melt("fiscal_year", var_name="metric", value_name="value")
        rev_long["metric"] = rev_long["metric"].map({"revenue_m": "Revenue", "ebitda_m": "EBITDA"})

        chart_rev = (
            alt.Chart(rev_long)
            .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
            .encode(
                x=alt.X("fiscal_year:N", title="Fiscal year", axis=alt.Axis(labelAngle=0)),
                y=alt.Y("value:Q", title="€M", stack=False),
                color=alt.Color("metric:N",
                    scale=alt.Scale(domain=["Revenue", "EBITDA"],
                                    range=["#6366f1", "#10b981"]),
                    legend=alt.Legend(orient="top", title=None)),
                xOffset="metric:N",
                tooltip=["fiscal_year:N", "metric:N",
                         alt.Tooltip("value:Q", title="€M", format=",.0f")],
            )
            .properties(title="Revenue & EBITDA (€M)", height=260)
        )
        col_l.altair_chart(chart_rev, use_container_width=True)

        # Company count + net profit
        cp_np = evo[["fiscal_year", "companies", "net_profit_m"]].copy()
        cp_np["fiscal_year"] = cp_np["fiscal_year"].astype(str)

        base = alt.Chart(cp_np).encode(x=alt.X("fiscal_year:N", title="Fiscal year", axis=alt.Axis(labelAngle=0)))
        bar_np = base.mark_bar(color="#f59e0b", cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
            y=alt.Y("net_profit_m:Q", title="Net profit (€M)"),
            tooltip=["fiscal_year:N", alt.Tooltip("net_profit_m:Q", title="Net profit €M", format=",.0f")]
        )
        line_co = base.mark_line(color="#64748b", strokeDash=[4, 3], strokeWidth=2).encode(
            y=alt.Y("companies:Q", title="Companies", axis=alt.Axis(titleColor="#64748b")),
            tooltip=["fiscal_year:N", alt.Tooltip("companies:Q", title="Companies", format=",")]
        )
        chart_np = alt.layer(bar_np, line_co).resolve_scale(y="independent").properties(
            title="Net profit (bars) & company coverage (line)", height=260
        )
        col_r.altair_chart(chart_np, use_container_width=True)

    with tab_margin:
        col_l, col_r = st.columns(2)

        m_df = evo[["fiscal_year", "med_ebitda_margin", "med_ebit_margin"]].copy()
        m_df["fiscal_year"] = m_df["fiscal_year"].astype(str)
        m_long = m_df.melt("fiscal_year", var_name="metric", value_name="pct")
        m_long["metric"] = m_long["metric"].map({
            "med_ebitda_margin": "EBITDA margin",
            "med_ebit_margin": "EBIT margin"
        })

        chart_m = (
            alt.Chart(m_long)
            .mark_line(point=True, strokeWidth=2)
            .encode(
                x=alt.X("fiscal_year:N", title="Fiscal year", axis=alt.Axis(labelAngle=0)),
                y=alt.Y("pct:Q", title="Median margin (%)"),
                color=alt.Color("metric:N",
                    scale=alt.Scale(domain=["EBITDA margin", "EBIT margin"],
                                    range=["#10b981", "#6366f1"]),
                    legend=alt.Legend(orient="top", title=None)),
                tooltip=["fiscal_year:N", "metric:N",
                         alt.Tooltip("pct:Q", title="%", format=".1f")],
            )
            .properties(title="Median EBITDA & EBIT margin by year", height=260)
        )
        col_l.altair_chart(chart_m, use_container_width=True)

        # Margin distribution histogram
        if not margin_d.empty:
            chart_hist = (
                alt.Chart(margin_d)
                .mark_bar(color="#6366f1", opacity=0.8, cornerRadiusTopLeft=2, cornerRadiusTopRight=2)
                .encode(
                    x=alt.X("margin_bucket:Q", title="EBITDA margin %", bin=False),
                    y=alt.Y("n:Q", title="Companies"),
                    tooltip=[alt.Tooltip("margin_bucket:Q", title="Margin %", format=".0f"),
                             alt.Tooltip("n:Q", title="Companies", format=",")],
                )
                .properties(title="EBITDA margin distribution (latest year)", height=260)
            )
            col_r.altair_chart(chart_hist, use_container_width=True)

    with tab_nfd:
        col_l, col_r = st.columns(2)

        nfd_df = evo[["fiscal_year", "nfd_m", "med_nfd_ebitda"]].copy()
        nfd_df["fiscal_year"] = nfd_df["fiscal_year"].astype(str)

        chart_nfd = (
            alt.Chart(nfd_df)
            .mark_bar(color="#ef4444", cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
            .encode(
                x=alt.X("fiscal_year:N", title="Fiscal year", axis=alt.Axis(labelAngle=0)),
                y=alt.Y("nfd_m:Q", title="Total NFD (€M)"),
                tooltip=["fiscal_year:N", alt.Tooltip("nfd_m:Q", title="NFD €M", format=",.0f")],
            )
            .properties(title="Total Net Financial Debt (€M)", height=260)
        )
        col_l.altair_chart(chart_nfd, use_container_width=True)

        chart_nfd_e = (
            alt.Chart(nfd_df.dropna(subset=["med_nfd_ebitda"]))
            .mark_line(point=True, color="#f59e0b", strokeWidth=2)
            .encode(
                x=alt.X("fiscal_year:N", title="Fiscal year", axis=alt.Axis(labelAngle=0)),
                y=alt.Y("med_nfd_ebitda:Q", title="Median NFD / EBITDA (x)"),
                tooltip=["fiscal_year:N",
                         alt.Tooltip("med_nfd_ebitda:Q", title="NFD/EBITDA", format=".2f")],
            )
            .properties(title="Median NFD / EBITDA ratio by year", height=260)
        )
        # Add a reference line at 3x
        ref = alt.Chart(pd.DataFrame({"y": [3]})).mark_rule(
            color="#ef4444", strokeDash=[6, 3], strokeWidth=1.5
        ).encode(y="y:Q")
        col_r.altair_chart(chart_nfd_e + ref, use_container_width=True)
        col_r.caption("Red dashed line = 3× leverage threshold")

# ---------------------------------------------------------------------------
# SECTOR PERFORMANCE
# ---------------------------------------------------------------------------

if not nace_df.empty:
    st.markdown('<div class="section-hdr">Sector performance (latest year)</div>', unsafe_allow_html=True)

    tab_rev, tab_marg, tab_nfd2, tab_table = st.tabs(
        ["💶 Revenue by sector", "📊 Margin by sector", "⚖️ NFD/EBITDA by sector", "📋 Full table"]
    )

    def _short(s, n=40):
        return s[:n] + "…" if isinstance(s, str) and len(s) > n else s

    nace_plot = nace_df.copy()
    nace_plot["sector_short"] = nace_plot["sector"].apply(lambda s: _short(s, 38))
    nace_plot = nace_plot.sort_values("revenue_m", ascending=False)

    with tab_rev:
        chart_nrev = (
            alt.Chart(nace_plot)
            .mark_bar(color="#6366f1", cornerRadiusTopRight=3, cornerRadiusBottomRight=3)
            .encode(
                y=alt.Y("sector_short:N", sort="-x", title=None,
                        axis=alt.Axis(labelLimit=280)),
                x=alt.X("revenue_m:Q", title="Revenue (€M)"),
                tooltip=["sector:N", "companies:Q",
                         alt.Tooltip("revenue_m:Q", title="Revenue €M", format=",.0f"),
                         alt.Tooltip("ebitda_m:Q", title="EBITDA €M", format=",.0f")],
            )
            .properties(height=max(300, nace_top_n * 30))
        )
        st.altair_chart(chart_nrev, use_container_width=True)

    with tab_marg:
        margin_plot = nace_plot.dropna(subset=["med_margin"]).sort_values("med_margin", ascending=False)
        color_expr = alt.condition(
            alt.datum.med_margin >= 0,
            alt.value("#10b981"),
            alt.value("#ef4444")
        )
        chart_nmarg = (
            alt.Chart(margin_plot)
            .mark_bar(cornerRadiusTopRight=3, cornerRadiusBottomRight=3)
            .encode(
                y=alt.Y("sector_short:N", sort="-x", title=None,
                        axis=alt.Axis(labelLimit=280)),
                x=alt.X("med_margin:Q", title="Median EBITDA margin (%)"),
                color=color_expr,
                tooltip=["sector:N", "companies:Q",
                         alt.Tooltip("med_margin:Q", title="Median margin %", format=".1f"),
                         alt.Tooltip("med_fte:Q", title="Median FTE", format=".0f")],
            )
            .properties(height=max(300, nace_top_n * 30))
        )
        ref0 = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(color="#334155", strokeWidth=1).encode(x="x:Q")
        st.altair_chart(chart_nmarg + ref0, use_container_width=True)

    with tab_nfd2:
        nfd2_plot = nace_plot.dropna(subset=["med_nfd_ebitda"]).sort_values("med_nfd_ebitda")
        chart_nnfd = (
            alt.Chart(nfd2_plot)
            .mark_bar(color="#f59e0b", cornerRadiusTopRight=3, cornerRadiusBottomRight=3)
            .encode(
                y=alt.Y("sector_short:N", sort="x", title=None,
                        axis=alt.Axis(labelLimit=280)),
                x=alt.X("med_nfd_ebitda:Q", title="Median NFD / EBITDA (x)"),
                tooltip=["sector:N", "companies:Q",
                         alt.Tooltip("med_nfd_ebitda:Q", title="NFD/EBITDA", format=".2f")],
            )
            .properties(height=max(300, nace_top_n * 30))
        )
        ref3 = alt.Chart(pd.DataFrame({"x": [3]})).mark_rule(
            color="#ef4444", strokeDash=[6, 3], strokeWidth=1.5
        ).encode(x="x:Q")
        st.altair_chart(chart_nnfd + ref3, use_container_width=True)
        st.caption("Red dashed = 3× threshold")

    with tab_table:
        tbl = nace_df[["sector", "nace2", "companies", "revenue_m",
                       "ebitda_m", "med_margin", "med_fte", "med_nfd_ebitda"]].copy()
        tbl.columns = ["Sector", "NACE", "Companies", "Revenue €M",
                       "EBITDA €M", "Median margin %", "Median FTE", "Median NFD/EBITDA"]
        for col in ["Revenue €M", "EBITDA €M"]:
            tbl[col] = tbl[col].apply(lambda v: f"{v:,.0f}" if pd.notna(v) else "—")
        tbl["Median margin %"] = tbl["Median margin %"].apply(lambda v: f"{v:.1f}%" if pd.notna(v) else "—")
        tbl["Median FTE"] = tbl["Median FTE"].apply(lambda v: f"{v:.0f}" if pd.notna(v) else "—")
        tbl["Median NFD/EBITDA"] = tbl["Median NFD/EBITDA"].apply(lambda v: f"{v:.2f}×" if pd.notna(v) else "—")
        st.dataframe(tbl, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# NFD EVOLUTION BY SECTOR
# ---------------------------------------------------------------------------

if not nfd_nace.empty:
    st.markdown('<div class="section-hdr">NFD / EBITDA evolution by sector</div>', unsafe_allow_html=True)

    nfd_nace["fiscal_year"] = nfd_nace["fiscal_year"].astype(str)
    nfd_nace["sector_short"] = nfd_nace["sector"].apply(lambda s: _short(s, 35))

    chart_nfd_lines = (
        alt.Chart(nfd_nace.dropna(subset=["med_nfd_ebitda"]))
        .mark_line(point=True, strokeWidth=2)
        .encode(
            x=alt.X("fiscal_year:N", title="Fiscal year", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("med_nfd_ebitda:Q", title="Median NFD / EBITDA (x)"),
            color=alt.Color("sector_short:N",
                            legend=alt.Legend(orient="right", title="Sector", labelLimit=200)),
            tooltip=["fiscal_year:N", "sector:N",
                     alt.Tooltip("med_nfd_ebitda:Q", title="NFD/EBITDA", format=".2f"),
                     alt.Tooltip("n:Q", title="Companies", format=",")],
        )
        .properties(height=340)
    )
    ref3b = alt.Chart(pd.DataFrame({"y": [3]})).mark_rule(
        color="#ef4444", strokeDash=[6, 3], strokeWidth=1.5
    ).encode(y="y:Q")
    st.altair_chart(chart_nfd_lines + ref3b, use_container_width=True)
    st.caption("Median NFD/EBITDA per sector · red dashed = 3× threshold")

# ---------------------------------------------------------------------------
# GEOGRAPHY
# ---------------------------------------------------------------------------

if not prov_df.empty:
    st.markdown('<div class="section-hdr">Geography (latest year per company)</div>', unsafe_allow_html=True)

    col_l, col_r = st.columns(2)

    prov_sorted = prov_df.sort_values("companies", ascending=False)

    chart_pco = (
        alt.Chart(prov_sorted)
        .mark_bar(color="#6366f1", cornerRadiusTopRight=3, cornerRadiusBottomRight=3)
        .encode(
            y=alt.Y("province:N", sort="-x", title=None),
            x=alt.X("companies:Q", title="Companies"),
            tooltip=["province:N", alt.Tooltip("companies:Q", format=","),
                     alt.Tooltip("revenue_m:Q", title="Revenue €M", format=",.0f")],
        )
        .properties(title="Companies by province", height=320)
    )
    col_l.altair_chart(chart_pco, use_container_width=True)

    chart_prev = (
        alt.Chart(prov_sorted)
        .mark_bar(color="#10b981", cornerRadiusTopRight=3, cornerRadiusBottomRight=3)
        .encode(
            y=alt.Y("province:N", sort="-x", title=None),
            x=alt.X("revenue_m:Q", title="Revenue (€M)"),
            tooltip=["province:N",
                     alt.Tooltip("revenue_m:Q", title="Revenue €M", format=",.0f"),
                     alt.Tooltip("med_margin:Q", title="Median margin %", format=".1f"),
                     alt.Tooltip("total_fte:Q", title="Total FTE", format=",")],
        )
        .properties(title="Revenue by province (€M)", height=320)
    )
    col_r.altair_chart(chart_prev, use_container_width=True)

    # Province margin comparison
    prov_marg = prov_df.dropna(subset=["med_margin"]).sort_values("med_margin", ascending=False)
    color_prov = alt.condition(
        alt.datum.med_margin >= 0, alt.value("#10b981"), alt.value("#ef4444")
    )
    chart_pmarg = (
        alt.Chart(prov_marg)
        .mark_bar(cornerRadiusTopRight=3, cornerRadiusBottomRight=3)
        .encode(
            y=alt.Y("province:N", sort="-x", title=None),
            x=alt.X("med_margin:Q", title="Median EBITDA margin (%)"),
            color=color_prov,
            tooltip=["province:N",
                     alt.Tooltip("med_margin:Q", title="Median margin %", format=".1f"),
                     alt.Tooltip("med_fte:Q", title="Median FTE", format=".0f")],
        )
        .properties(title="Median EBITDA margin by province (%)", height=320)
    )
    st.altair_chart(chart_pmarg, use_container_width=True)

# ---------------------------------------------------------------------------
# COMPANY SIZE DISTRIBUTION
# ---------------------------------------------------------------------------

if not size_d.empty:
    st.markdown('<div class="section-hdr">Company size distribution (by revenue, latest year)</div>',
                unsafe_allow_html=True)

    col_l, col_r = st.columns(2)

    chart_size_n = (
        alt.Chart(size_d)
        .mark_bar(color="#6366f1", cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X("size_bucket:N", sort=None, title="Revenue band", axis=alt.Axis(labelAngle=-30)),
            y=alt.Y("companies:Q", title="Number of companies"),
            tooltip=["size_bucket:N", alt.Tooltip("companies:Q", format=","),
                     alt.Tooltip("revenue_m:Q", title="Total revenue €M", format=",.0f")],
        )
        .properties(title="Companies by revenue band", height=260)
    )
    col_l.altair_chart(chart_size_n, use_container_width=True)

    chart_size_r = (
        alt.Chart(size_d)
        .mark_bar(color="#10b981", cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X("size_bucket:N", sort=None, title="Revenue band", axis=alt.Axis(labelAngle=-30)),
            y=alt.Y("revenue_m:Q", title="Total revenue (€M)"),
            tooltip=["size_bucket:N", alt.Tooltip("companies:Q", format=","),
                     alt.Tooltip("revenue_m:Q", title="Total revenue €M", format=",.0f")],
        )
        .properties(title="Total revenue by band (€M)", height=260)
    )
    col_r.altair_chart(chart_size_r, use_container_width=True)

# ---------------------------------------------------------------------------
# TOP COMPANIES
# ---------------------------------------------------------------------------

@st.cache_data(ttl=120)
def load_top_companies(prov_clause, limit=15):
    conn = _conn()
    cur = conn.cursor()
    cur.execute(f"""
        SELECT fl.enterprise_number, COALESCE(d.denomination, fl.enterprise_number) AS name,
               fl.revenue, fl.ebitda,
               CASE WHEN fl.revenue > 0 THEN ROUND((fl.ebitda/fl.revenue*100)::numeric,1) END AS margin,
               fl.fte_total, fl.fiscal_year,
               COALESCE(nl.description, ci.nace_code) AS sector, ci.city
        FROM financial_latest fl
        JOIN company_info ci ON ci.enterprise_number = fl.enterprise_number
        LEFT JOIN denomination d ON d.entity_number = fl.enterprise_number
             AND d.type_of_denomination = '001' AND d.language IN ('2','1')
        LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
        WHERE fl.revenue IS NOT NULL AND fl.revenue > 0
        {prov_clause}
        ORDER BY fl.revenue DESC
        LIMIT %s
    """, (limit,))
    rows = cur.fetchall()
    conn.close()
    return rows

st.markdown('<div class="section-hdr">Top companies by revenue (latest year)</div>', unsafe_allow_html=True)

top_cos = load_top_companies(prov_clause, limit=15)
if top_cos:
    def fmt_eur_stat(v):
        if not v or pd.isna(v): return "—"
        v = float(v)
        neg = v < 0
        a = abs(v)
        if a >= 1e9:   s = f"€{a/1e9:,.1f}B"
        elif a >= 1e6: s = f"€{a/1e6:,.1f}M"
        elif a >= 1e3: s = f"€{a/1e3:,.0f}K"
        else:          s = f"€{a:,.0f}"
        return f"-{s}" if neg else s

    h1, h2, h3, h4, h5, h6 = st.columns([4, 3, 2, 2, 1.5, 1.5])
    for col, lbl in zip([h1, h2, h3, h4, h5, h6],
                        ["Company", "Sector", "Revenue", "EBITDA", "Margin", "FTE"]):
        col.markdown(f'<span style="font-size:10px;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:.05em">{lbl}</span>', unsafe_allow_html=True)

    for row in top_cos:
        cbe, cname, revenue, ebitda, margin, fte, fy, sector, city = row
        cbe_str = str(cbe).zfill(10)
        c1, c2, c3, c4, c5, c6 = st.columns([4, 3, 2, 2, 1.5, 1.5])
        with c1:
            if st.button(
                f"🏢 {(cname or '')[:38]}",
                key=f"stats_top_{cbe_str}",
                use_container_width=True,
            ):
                st.session_state["company_cbe"] = cbe_str
                st.session_state["_clear_search"] = True
                st.switch_page("pages/2_company.py")
        c2.caption((sector or "—")[:45])
        c3.caption(fmt_eur_stat(revenue))
        c4.caption(fmt_eur_stat(ebitda))
        c5.caption(f"{margin:.1f}%" if margin else "—")
        c6.caption(f"{int(fte):,}" if fte else "—")
