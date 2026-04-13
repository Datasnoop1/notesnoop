"""Favourites — track companies of interest for deal sourcing."""

import os
import sys

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
from components import topbar, get_favourites, add_favourite, remove_favourite, is_favourite
from db import get_connection

load_dotenv()

st.set_page_config(page_title="Favourites - Belgian Co DB", layout="wide")

st.markdown("""
<style>
section[data-testid="stSidebar"] { display: none !important; }
[data-testid="collapsedControl"]  { display: none !important; }
div.block-container { max-width: 1300px; }
.fav-header { font-size: 11px; font-weight: 700; color: #64748b; text-transform: uppercase;
              letter-spacing: .04em; padding: 4px 0; border-bottom: 2px solid #e2e8f0; margin-bottom: 4px; }
.section-title { font-size: 11px; font-weight: 700; color: #334155; border-left: 3px solid #6366f1;
    padding-left: 8px; margin: 16px 0 8px 0; text-transform: uppercase; letter-spacing: .04em; }
</style>
""", unsafe_allow_html=True)

topbar(active="Favourites")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fmt_eur(v):
    if v is None or pd.isna(v):
        return "---"
    v = float(v)
    if abs(v) >= 1e9:
        return f"\u20ac{v/1e9:,.1f}B"
    if abs(v) >= 1e6:
        return f"\u20ac{v/1e6:,.1f}M"
    if abs(v) >= 1e3:
        return f"\u20ac{v/1e3:,.0f}K"
    return f"\u20ac{v:,.0f}"


def fmt_cbe(n):
    n = str(n).zfill(10)
    return f"{n[:4]}.{n[4:7]}.{n[7:]}"


def search_companies(query, limit=20):
    """Search companies by name or CBE."""
    conn = get_connection()
    cur = conn.cursor()
    q = query.strip()
    cbe_q = q.replace(".", "").replace(" ", "")
    if cbe_q.isdigit() and len(cbe_q) >= 4:
        cur.execute("""
            SELECT e.enterprise_number,
                   d.denomination AS name,
                   ad.zipcode, ad.municipality_nl
            FROM enterprise e
            LEFT JOIN denomination d ON d.entity_number = e.enterprise_number
                AND d.type_of_denomination = '001'
            LEFT JOIN address ad ON ad.entity_number = e.enterprise_number
                AND ad.type_of_address = 'REGO'
            WHERE e.enterprise_number LIKE %s AND e.status = 'AC'
            GROUP BY e.enterprise_number, d.denomination, ad.zipcode, ad.municipality_nl
            LIMIT %s
        """, (f"{cbe_q}%", limit))
        rows = cur.fetchall()
    else:
        cur.execute("""
            SELECT e.enterprise_number,
                   d.denomination AS name,
                   ad.zipcode, ad.municipality_nl
            FROM denomination d
            JOIN enterprise e ON e.enterprise_number = d.entity_number AND e.status = 'AC'
            LEFT JOIN address ad ON ad.entity_number = e.enterprise_number
                AND ad.type_of_address = 'REGO'
            WHERE d.denomination ILIKE %s AND d.type_of_denomination = '001'
            GROUP BY e.enterprise_number, d.denomination, ad.zipcode, ad.municipality_nl
            ORDER BY d.denomination
            LIMIT %s
        """, (f"%{q}%", limit))
        rows = cur.fetchall()
    conn.close()
    return [{"cbe": r[0], "name": r[1], "zipcode": r[2], "city": r[3]} for r in rows]


# ---------------------------------------------------------------------------
# Add companies section
# ---------------------------------------------------------------------------

st.markdown('<div class="section-title">Add companies to favourites</div>', unsafe_allow_html=True)

add_query = st.text_input("Search by company name or CBE number", key="fav_search",
                           placeholder="e.g. Colruyt, Delhaize, 0400710265...")

if add_query and add_query.strip():
    results = search_companies(add_query)
    if not results:
        st.caption("No matching companies found.")
    else:
        for i, r in enumerate(results):
            cbe = r["cbe"]
            rname = r["name"] or fmt_cbe(cbe)
            city = r["city"] or ""
            already = is_favourite(cbe)

            c_star, c_name, c_cbe, c_city = st.columns([0.5, 4, 2, 2])
            with c_star:
                if already:
                    st.markdown("⭐")
                else:
                    if st.button("+ Add", key=f"add_{i}_{cbe}", type="primary"):
                        add_favourite(cbe)
                        st.rerun()
            c_name.markdown(f"**{rname}**")
            c_cbe.caption(fmt_cbe(cbe))
            c_city.caption(city)

st.divider()

# ---------------------------------------------------------------------------
# Favourites list
# ---------------------------------------------------------------------------

st.markdown('<div class="section-title">Your favourites</div>', unsafe_allow_html=True)

favs = get_favourites()

if not favs:
    st.info("No favourites yet. Search above or star companies from the Company page.")
else:
    st.caption(f"{len(favs)} companies tracked")

    # Header row
    hdr = st.columns([0.5, 3.5, 1.5, 1.5, 1.5, 1, 1, 2])
    hdr_labels = ["", "Company", "CBE", "Revenue", "EBITDA", "Margin", "FTE", "Added"]
    for c, lbl in zip(hdr, hdr_labels):
        c.markdown(f"<span class='fav-header'>{lbl}</span>", unsafe_allow_html=True)

    for i, fav in enumerate(favs):
        cbe = fav["cbe"]
        fname = fav["name"] or fmt_cbe(cbe)

        cols = st.columns([0.5, 3.5, 1.5, 1.5, 1.5, 1, 1, 2])

        # Remove button
        with cols[0]:
            if st.button("x", key=f"rem_{i}_{cbe}", help="Remove from favourites"):
                remove_favourite(cbe)
                st.rerun()

        # Company name — clickable
        with cols[1]:
            if st.button(f"🏢 {fname}", key=f"fav_nav_{i}_{cbe}", use_container_width=True):
                st.session_state["company_cbe"] = cbe
                st.session_state["_clear_search"] = True
                st.switch_page("pages/2_company.py")

        cols[2].caption(fmt_cbe(cbe))
        cols[3].caption(fmt_eur(fav.get("revenue")))
        cols[4].caption(fmt_eur(fav.get("ebitda")))
        m = fav.get("margin")
        cols[5].caption(f"{m:.1f}%" if m and pd.notna(m) else "---")
        fte = fav.get("fte")
        cols[6].caption(f"{fte:,.0f}" if fte and pd.notna(fte) else "---")
        added = (fav.get("added_at") or "")[:10]
        cols[7].caption(added)

    # Export
    st.divider()
    if st.button("Download favourites as Excel", type="secondary", key="export_favs"):
        df = pd.DataFrame(favs)
        df.columns = ["CBE", "Added", "Notes", "Company", "NACE", "Revenue", "EBITDA", "FTE", "Margin"]
        df = df[["Company", "CBE", "NACE", "Revenue", "EBITDA", "Margin", "FTE", "Added", "Notes"]]
        import io
        buf = io.BytesIO()
        df.to_excel(buf, index=False, sheet_name="Favourites")
        st.download_button(
            label="Save Excel file",
            data=buf.getvalue(),
            file_name="favourites.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="dl_favs",
        )
