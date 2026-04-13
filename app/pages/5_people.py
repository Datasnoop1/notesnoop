"""People — search for administrators, directors and shareholders by name."""

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

st.set_page_config(page_title="People · Belgian Co DB", layout="wide")

st.markdown("""
<style>
.page-title { font-size:26px; font-weight:800; color:#0f172a; margin-bottom:2px; }
.page-sub   { font-size:13px; color:#64748b; margin-bottom:0; }

.person-card {
    background:#fff; border:1px solid #e2e8f0; border-radius:12px;
    padding:14px 18px; margin-bottom:8px;
    box-shadow:0 1px 4px rgba(99,102,241,0.05);
}
.person-name  { font-size:16px; font-weight:800; color:#0f172a; }
.person-meta  { font-size:11px; color:#64748b; margin-top:3px; }

.role-badge {
    display:inline-block; padding:2px 8px; border-radius:6px;
    font-size:10px; font-weight:700; margin-right:4px;
}
.role-admin   { background:#eef2ff; color:#4338ca; }
.role-sh      { background:#f0fdf4; color:#166534; }
.role-sub     { background:#fff7ed; color:#9a3412; }

.section-hdr {
    font-size:11px; font-weight:700; color:#334155;
    border-left:3px solid #6366f1; padding-left:8px;
    margin:14px 0 6px 0; text-transform:uppercase; letter-spacing:.04em;
}

.co-row {
    display:flex; align-items:center; gap:8px; padding:5px 10px;
    border:1px solid #e2e8f0; border-radius:7px; margin:2px 0;
    background:#fafbff; font-size:12px;
}
.co-name  { font-weight:600; color:#0f172a; flex:1; }
.co-meta  { color:#64748b; font-size:11px; white-space:nowrap; }
.co-badge { background:#eef2ff; color:#4338ca; padding:1px 6px; border-radius:4px;
    font-size:10px; font-weight:700; white-space:nowrap; }

/* Search result headers */
.sr-header { font-size:10px; font-weight:700; color:#94a3b8;
    text-transform:uppercase; letter-spacing:.05em; padding:2px 4px; }
</style>
""", unsafe_allow_html=True)

topbar(active="People")

st.markdown(
    '<p class="page-title">👤 People search</p>'
    '<p class="page-sub">Find administrators, directors and shareholders by name</p>',
    unsafe_allow_html=True,
)


def _conn():
    return get_connection()


def fmt_cbe(n):
    n = str(n).zfill(10)
    return f"{n[:4]}.{n[4:7]}.{n[7:]}"


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


ROLE_LABELS = {
    "fct:m10": "Director", "fct:m11": "Managing director",
    "fct:m12": "Chairman", "fct:m13": "Administrator",
    "fct:m14": "Secretary", "fct:m15": "Treasurer",
    "fct:m20": "Statutory auditor", "fct:m30": "Liquidator",
    "fct:m40": "Daily management",
}


@st.cache_data(ttl=60)
def search_people(query: str):
    """Return list of distinct names matching the query, with connection counts."""
    q = f"%{query.strip()}%"
    conn = _conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT name, COUNT(DISTINCT enterprise_number) AS n_admin_cos
        FROM administrator
        WHERE name ILIKE %s
        GROUP BY name
        UNION
        SELECT name, COUNT(DISTINCT enterprise_number) AS n_sh_cos
        FROM shareholder
        WHERE name ILIKE %s
        GROUP BY name
        ORDER BY n_admin_cos DESC, name
        LIMIT 50
    """, (q, q))
    rows = cur.fetchall()
    conn.close()
    # Aggregate by name
    agg = {}
    for name, cnt in rows:
        agg[name] = agg.get(name, 0) + cnt
    return sorted(agg.items(), key=lambda x: (-x[1], x[0]))


@st.cache_data(ttl=60)
def load_person_connections(person_name: str):
    """Load all company connections for a person/entity name."""
    conn = _conn()

    # Administrator roles
    admins = pd.read_sql_query("""
        SELECT
            a.enterprise_number,
            COALESCE(d.denomination, a.enterprise_number) AS "company_name",
            a.role,
            a.mandate_start,
            a.mandate_end,
            a.representative_name,
            fl.revenue,
            fl.ebitda,
            fl.fte_total,
            fl.fiscal_year
        FROM administrator a
        LEFT JOIN denomination d ON d.entity_number = a.enterprise_number
            AND d.type_of_denomination = '001' AND d.language IN ('2','1')
        LEFT JOIN financial_latest fl ON fl.enterprise_number = a.enterprise_number
        WHERE a.name = %s
        ORDER BY a.mandate_start DESC
    """, conn, params=(person_name,))

    # Shareholdings (companies this person/entity owns shares in)
    holdings = pd.read_sql_query("""
        SELECT
            s.enterprise_number,
            COALESCE(d.denomination, s.enterprise_number) AS "company_name",
            s.ownership_pct,
            s.shares_held,
            fl.revenue,
            fl.ebitda,
            fl.fte_total,
            fl.fiscal_year
        FROM shareholder s
        LEFT JOIN denomination d ON d.entity_number = s.enterprise_number
            AND d.type_of_denomination = '001' AND d.language IN ('2','1')
        LEFT JOIN financial_latest fl ON fl.enterprise_number = s.enterprise_number
        WHERE s.name = %s
        ORDER BY s.ownership_pct DESC NULLS LAST
    """, conn, params=(person_name,))

    conn.close()
    return admins, holdings


def navigate_to(cbe):
    """Navigate to company page."""
    st.session_state["company_cbe"] = str(cbe).zfill(10)
    st.session_state["_clear_search"] = True
    st.switch_page("pages/2_company.py")


# ---------------------------------------------------------------------------
# Search bar
# ---------------------------------------------------------------------------

col_q, col_btn = st.columns([5, 1])
with col_q:
    query = st.text_input(
        "Search", placeholder="e.g. Jan Janssen, AB InBev, Sofina…",
        label_visibility="collapsed",
        key="people_search_q",
    )
with col_btn:
    do_search = st.button("🔍 Search", type="primary", use_container_width=True)

selected_person = st.session_state.get("selected_person", "")

# ---------------------------------------------------------------------------
# Search results — list of distinct names
# ---------------------------------------------------------------------------

if query and query.strip() and not selected_person:
    try:
        results = search_people(query.strip())
        if not results:
            st.info("No administrators or shareholders found with that name.")
        else:
            st.caption(f"{len(results)} distinct name(s) found")

            # Column headers
            h1, h2 = st.columns([6, 2])
            h1.markdown('<span class="sr-header">Name</span>', unsafe_allow_html=True)
            h2.markdown('<span class="sr-header">Connected to N companies</span>', unsafe_allow_html=True)

            for i, (pname, n_cos) in enumerate(results[:30]):
                c1, c2 = st.columns([6, 2])
                with c1:
                    if st.button(f"👤 {pname}", key=f"per_{i}",
                                 use_container_width=True):
                        st.session_state["selected_person"] = pname
                        st.rerun()
                c2.caption(f"{n_cos} company connection(s)")
    except Exception as e:
        st.error(str(e))

elif selected_person:
    # ── Person detail ────────────────────────────────────────────────────────
    # Also allow clearing by typing a new search query
    if query and query.strip() != st.session_state.get("_last_people_query", ""):
        st.session_state.pop("selected_person", None)
        st.session_state["_last_people_query"] = query.strip()
        st.rerun()

    if st.button("← Back to results"):
        st.session_state.pop("selected_person", None)
        st.session_state.pop("_last_people_query", None)
        st.rerun()

    try:
        admins_df, holdings_df = load_person_connections(selected_person)

        n_admin  = len(admins_df.drop_duplicates(subset=["enterprise_number"]))
        n_holds  = len(holdings_df.drop_duplicates(subset=["enterprise_number"]))
        total_co = len(set(
            list(admins_df["enterprise_number"]) + list(holdings_df["enterprise_number"])
        ))

        # Summary card
        st.markdown(f"""
        <div class="person-card">
          <div class="person-name">👤 {selected_person}</div>
          <div class="person-meta">
            Connected to <strong>{total_co}</strong> company/companies
            {"&nbsp;·&nbsp;" + f"<strong>{n_admin}</strong> board roles" if n_admin else ""}
            {"&nbsp;·&nbsp;" + f"<strong>{n_holds}</strong> shareholding(s)" if n_holds else ""}
          </div>
        </div>
        """, unsafe_allow_html=True)

        # ── Board roles ────────────────────────────────────────────────────────────
        if not admins_df.empty:
            unique_admin = admins_df.drop_duplicates(subset=["enterprise_number", "role"])
            st.markdown(
                f'<div class="section-hdr">Board roles ({len(unique_admin)})</div>',
                unsafe_allow_html=True)

            # Column headers
            h1, h2, h3, h4, h5 = st.columns([4, 2, 2, 2, 1.5])
            h1.markdown('<span class="sr-header">Company</span>', unsafe_allow_html=True)
            h2.markdown('<span class="sr-header">Role</span>', unsafe_allow_html=True)
            h3.markdown('<span class="sr-header">Revenue</span>', unsafe_allow_html=True)
            h4.markdown('<span class="sr-header">EBITDA</span>', unsafe_allow_html=True)
            h5.markdown('<span class="sr-header">FTE</span>', unsafe_allow_html=True)

            for _, row in unique_admin.iterrows():
                cbe    = str(row["enterprise_number"]).zfill(10)
                cname  = (row["company_name"] or fmt_cbe(cbe))[:40]
                role   = ROLE_LABELS.get(row["role"] or "", row["role"] or "Administrator")
                rev    = fmt_eur(row["revenue"])
                ebitda = fmt_eur(row["ebitda"])
                fte    = f"{int(row['fte_total']):,}" if pd.notna(row.get("fte_total")) else "—"
                mstart = (row.get("mandate_start") or "")[:7]
                mend   = (row.get("mandate_end") or "")[:7]
                period = f"{mstart}–{mend}" if mstart and mend else mstart

                c1, c2, c3, c4, c5 = st.columns([4, 2, 2, 2, 1.5])
                with c1:
                    if st.button(f"🏢 {cname}", key=f"adm_{cbe}_{role[:8].replace(' ','_')}",
                                 use_container_width=True):
                        navigate_to(cbe)
                c2.caption(f"{role}{' · ' + period if period else ''}")
                c3.caption(rev)
                c4.caption(ebitda)
                c5.caption(fte)

        # ── Shareholdings ───────────────────────────────────────────────────────────
        if not holdings_df.empty:
            unique_hold = holdings_df.drop_duplicates(subset=["enterprise_number"])
            st.markdown(
                f'<div class="section-hdr">Shareholdings ({len(unique_hold)})</div>',
                unsafe_allow_html=True)

            # Column headers
            h1, h2, h3, h4, h5 = st.columns([4, 1.5, 2, 2, 1.5])
            h1.markdown('<span class="sr-header">Company</span>', unsafe_allow_html=True)
            h2.markdown('<span class="sr-header">Ownership</span>', unsafe_allow_html=True)
            h3.markdown('<span class="sr-header">Revenue</span>', unsafe_allow_html=True)
            h4.markdown('<span class="sr-header">EBITDA</span>', unsafe_allow_html=True)
            h5.markdown('<span class="sr-header">FTE</span>', unsafe_allow_html=True)

            for _, row in unique_hold.sort_values("ownership_pct", ascending=False, na_position="last").iterrows():
                cbe    = str(row["enterprise_number"]).zfill(10)
                cname  = (row["company_name"] or fmt_cbe(cbe))[:40]
                pct    = f"{row['ownership_pct']:.1f}%" if pd.notna(row.get("ownership_pct")) else "—"
                rev    = fmt_eur(row["revenue"])
                ebitda = fmt_eur(row["ebitda"])
                fte    = f"{int(row['fte_total']):,}" if pd.notna(row.get("fte_total")) else "—"

                c1, c2, c3, c4, c5 = st.columns([4, 1.5, 2, 2, 1.5])
                with c1:
                    if st.button(f"🏢 {cname}", key=f"hold_{cbe}",
                                 use_container_width=True):
                        navigate_to(cbe)
                c2.caption(pct)
                c3.caption(rev)
                c4.caption(ebitda)
                c5.caption(fte)

    except Exception as e:
        st.error(str(e))

elif not query:
    st.markdown(
        "<div style='color:#94a3b8;font-size:13px;margin-top:32px;text-align:center'>"
        "Search for a person or company name to find their board roles and shareholdings."
        "</div>",
        unsafe_allow_html=True,
    )
