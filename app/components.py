"""Shared UI components for the Belgian Company DB app."""

import os
import sys
import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from db import get_connection

# Page definitions: (icon, label, route_path, file_path)
PAGES = [
    ("🏠", "Home",      "/",           None),               # main app.py has no pages/ path
    ("🔍", "Screener",  "/screener",   "pages/1_screener.py"),
    ("🏢", "Company",   "/company",    "pages/2_company.py"),
    ("⚖️", "Compare",   "/compare",    "pages/3_compare.py"),
    ("📊", "Stats",     "/stats",      "pages/4_stats.py"),
    ("👤", "People",    "/people",     "pages/5_people.py"),
    ("⭐", "Favourites", "/favourites", "pages/6_favourites.py"),
]


def _send_feedback(email: str, feedback_type: str, description: str, page: str):
    """Store feedback in PostgreSQL and show mailto link."""
    import datetime
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO feedback (type, page, description) VALUES (%s, %s, %s)",
        (feedback_type, page, description),
    )
    conn.commit()
    cur.close()
    conn.close()

    # Show mailto link so user can also send via email
    import urllib.parse
    subject = urllib.parse.quote(f"[Belgian Co DB] {feedback_type.title()} report — {page}")
    body = urllib.parse.quote(f"{description}\n\n---\nPage: {page}\nTime: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    st.markdown(
        f'<a href="mailto:{email}?subject={subject}&body={body}" target="_blank" '
        f'style="font-size:11px">Also send via email &rarr;</a>',
        unsafe_allow_html=True,
    )


def topbar(active=""):
    """Render a horizontal navigation bar using st.page_link for proper Streamlit routing."""
    # Custom CSS for the topbar styling
    st.markdown("""
    <style>
    /* ── Global scale ── */
    .stApp { font-size: 90%; }
    .stApp [data-testid="stMarkdownContainer"] { font-size: inherit; }

    /* ── Topbar container ── */
    .topbar-wrap {
        display: flex; gap: 4px; padding: 6px 0 10px 0;
        border-bottom: 1px solid #e2e8f0; margin-bottom: 14px;
        flex-wrap: wrap;
    }
    /* ── Override st.page_link pill style ── */
    div[data-testid="stPageLink"] a {
        padding: 5px 13px !important;
        border-radius: 8px !important;
        font-size: 13px !important;
        font-weight: 600 !important;
        color: #64748b !important;
        text-decoration: none !important;
        background: transparent !important;
        border: none !important;
    }
    div[data-testid="stPageLink"] a:hover {
        background: #f1f5f9 !important;
        color: #0f172a !important;
    }
    /* Active page link — can't target via Streamlit CSS easily, so we use the heading trick */
    .nav-active-badge {
        display: inline-block;
        padding: 5px 13px;
        border-radius: 8px;
        font-size: 13px;
        font-weight: 700;
        color: #4338ca;
        background: #eef2ff;
    }
    /* Hide sidebar completely */
    section[data-testid="stSidebar"] { display: none !important; }
    [data-testid="collapsedControl"]  { display: none !important; }

    /* ── App header ── */
    .app-brand {
        font-size: 18px; font-weight: 800; color: #4338ca;
        letter-spacing: -0.02em; line-height: 1;
    }
    .app-brand-sub {
        font-size: 9px; color: #94a3b8; font-weight: 500;
        text-transform: uppercase; letter-spacing: 0.08em;
    }
    </style>
    """, unsafe_allow_html=True)

    # App header
    hdr_left, hdr_right = st.columns([6, 2])
    with hdr_left:
        st.markdown(
            '<div class="app-brand">Datasnoop</div>'
            '<div class="app-brand-sub">Belgian company intelligence</div>',
            unsafe_allow_html=True)
    with hdr_right:
        st.markdown(
            '<div style="text-align:right;padding-top:4px">'
            '<span style="font-size:10px;color:#94a3b8">🐛 Bug · 💡 Idea &darr;</span>'
            '</div>',
            unsafe_allow_html=True)

    # Render nav items + feedback buttons
    nav_cols = st.columns([1] * len(PAGES) + [0.7, 0.7])
    for col, (icon, label, route, fpath) in zip(nav_cols, PAGES):
        is_active = label.lower() == active.lower()
        if is_active:
            col.markdown(
                f'<div class="nav-active-badge">{icon} {label}</div>',
                unsafe_allow_html=True)
        elif fpath:
            col.page_link(fpath, label=f"{icon} {label}")
        else:
            # Home — link by route
            col.markdown(
                f'<a href="{route}" style="padding:5px 13px;border-radius:8px;'
                f'font-size:13px;font-weight:600;color:#64748b;text-decoration:none;">'
                f'{icon} {label}</a>',
                unsafe_allow_html=True)

    # Feedback buttons (right side)
    _feedback_email = "albiezerozeroone@gmail.com"
    _page_ctx = active or "Home"

    with nav_cols[-2]:
        with st.popover("🐛 Report bug", use_container_width=True):
            st.markdown("#### 🐛 Report a bug")
            st.caption(f"Page: **{_page_ctx}**")
            bug_desc = st.text_area("What went wrong?", key=f"bug_desc_{_page_ctx}",
                                     placeholder="Describe what happened, what you expected, and steps to reproduce...", height=100)
            if st.button("📩 Send bug report", key=f"bug_send_{_page_ctx}", type="primary", use_container_width=True):
                if bug_desc and bug_desc.strip():
                    _send_feedback(_feedback_email, "bug", bug_desc.strip(), _page_ctx)
                    st.success("Bug report saved & email link generated!")
                else:
                    st.warning("Please describe the bug first.")

    with nav_cols[-1]:
        with st.popover("💡 Suggest idea", use_container_width=True):
            st.markdown("#### 💡 Feature request")
            st.caption(f"Page: **{_page_ctx}**")
            feat_desc = st.text_area("What would you like to see?", key=f"feat_desc_{_page_ctx}",
                                      placeholder="Describe the feature or improvement you'd like...", height=100)
            if st.button("📩 Send suggestion", key=f"feat_send_{_page_ctx}", type="primary", use_container_width=True):
                if feat_desc and feat_desc.strip():
                    _send_feedback(_feedback_email, "feature", feat_desc.strip(), _page_ctx)
                    st.success("Feature request saved & email link generated!")
                else:
                    st.warning("Please describe the feature first.")


def filter_row(label, min_key, max_key, step=100_000, prefix=""):
    """Render a min/max filter pair in two columns. Returns (min_val, max_val) or (None, None)."""
    c1, c2 = st.columns(2)
    min_val = c1.number_input(
        f"{label} ≥", min_value=0, value=0, step=step, format="%d", key=f"{prefix}{min_key}"
    ) or None
    max_val = c2.number_input(
        f"{label} ≤", min_value=0, value=0, step=step, format="%d", key=f"{prefix}{max_key}"
    ) or None
    return min_val, max_val


# ---------------------------------------------------------------------------
# Favourites helpers
# ---------------------------------------------------------------------------

def _ensure_favourite_table():
    """Table already exists in PG schema — no-op."""
    pass


def is_favourite(cbe: str) -> bool:
    """Check if a CBE is in the favourites list."""
    _ensure_favourite_table()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM favourite WHERE enterprise_number = %s",
        (str(cbe).zfill(10),)
    )
    row = cur.fetchone()
    conn.close()
    return row is not None


def toggle_favourite(cbe: str) -> bool:
    """Add if not favourited, remove if already favourited. Returns new state (True=added)."""
    cbe = str(cbe).zfill(10)
    _ensure_favourite_table()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM favourite WHERE enterprise_number = %s", (cbe,)
    )
    exists = cur.fetchone()
    if exists:
        cur.execute("DELETE FROM favourite WHERE enterprise_number = %s", (cbe,))
        conn.commit()
        conn.close()
        return False
    else:
        cur.execute(
            "INSERT INTO favourite (enterprise_number) VALUES (%s)", (cbe,)
        )
        conn.commit()
        conn.close()
        return True


def add_favourite(cbe: str, notes: str = None):
    """Add a company to favourites (no-op if already there)."""
    cbe = str(cbe).zfill(10)
    _ensure_favourite_table()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO favourite (enterprise_number, notes) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (cbe, notes)
    )
    conn.commit()
    conn.close()


def remove_favourite(cbe: str):
    """Remove a company from favourites."""
    cbe = str(cbe).zfill(10)
    _ensure_favourite_table()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM favourite WHERE enterprise_number = %s", (cbe,))
    conn.commit()
    conn.close()


def get_favourites() -> list:
    """Return all favourites with company name, sector, and latest financials."""
    _ensure_favourite_table()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT f.enterprise_number, f.added_at, f.notes,
               d.denomination AS name,
               a.nace_code, fl.revenue, fl.ebitda, fl.fte_total,
               CASE WHEN fl.revenue > 0 THEN ROUND((fl.ebitda / fl.revenue * 100)::numeric, 1) END AS margin
        FROM favourite f
        LEFT JOIN (
            SELECT entity_number, denomination FROM denomination
            WHERE type_of_denomination = '001'
            GROUP BY entity_number, denomination
        ) d ON d.entity_number = f.enterprise_number
        LEFT JOIN (
            SELECT entity_number, nace_code
            FROM activity
            WHERE classification = 'MAIN' AND nace_version = '2008'
            GROUP BY entity_number, nace_code
        ) a ON a.entity_number = f.enterprise_number
        LEFT JOIN financial_latest fl ON fl.enterprise_number = f.enterprise_number
        ORDER BY f.added_at DESC
    """)
    rows = cur.fetchall()
    conn.close()
    return [
        {
            "cbe": r[0], "added_at": r[1], "notes": r[2], "name": r[3],
            "nace": r[4], "revenue": r[5], "ebitda": r[6], "fte": r[7], "margin": r[8],
        }
        for r in rows
    ]


def favourite_star(cbe: str, key: str):
    """Render a star toggle button. Call from any page."""
    is_fav = is_favourite(cbe)
    label = "⭐" if is_fav else "☆"
    if st.button(label, key=key, help="Remove from favourites" if is_fav else "Add to favourites"):
        toggle_favourite(cbe)
        st.rerun()
