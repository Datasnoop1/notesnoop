"""Admin router — user management, usage stats, feedback review."""

import json
import os
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

import stripe

from db import fetch_all, fetch_one, execute, refresh_all_normalized_names
from auth import get_current_user

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"])

_feedback_columns_migrated = False


def _ensure_feedback_columns():
    """Add reply and replied_at columns to feedback table if missing (migration-style)."""
    global _feedback_columns_migrated
    if _feedback_columns_migrated:
        return
    try:
        execute("ALTER TABLE feedback ADD COLUMN IF NOT EXISTS reply TEXT")
        execute("ALTER TABLE feedback ADD COLUMN IF NOT EXISTS replied_at TIMESTAMP")
        _feedback_columns_migrated = True
        logger.info("Feedback table columns ensured (reply, replied_at)")
    except Exception:
        logger.debug("Feedback columns already exist or migration skipped")
        _feedback_columns_migrated = True


def _require_admin(user=Depends(get_current_user)):
    """Dependency: require admin role."""
    email = user.get("email", "")
    user_id = user.get("id", "")
    logger.info("Admin check: email=%s id=%s", email, user_id)

    role_row = fetch_one(
        "SELECT role FROM user_roles WHERE email = %s OR email = %s",
        (email, user_id),
    )
    if not role_row or role_row["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")
    return user


@router.get("/stats")
async def admin_stats(user=Depends(_require_admin)):
    """Platform stats including data loading progress."""
    # Migrate feedback table columns if needed (adds reply + replied_at)
    _ensure_feedback_columns()

    try:
        stats = fetch_one("""
            SELECT
                (SELECT reltuples::bigint FROM pg_class WHERE relname = 'enterprise') AS total_enterprises,
                (SELECT reltuples::bigint FROM pg_class WHERE relname = 'financial_latest') AS companies_with_financials,
                (SELECT reltuples::bigint FROM pg_class WHERE relname = 'administrator') AS admin_records,
                (SELECT reltuples::bigint FROM pg_class WHERE relname = 'financial_data') AS financial_rows,
                (SELECT reltuples::bigint FROM pg_class WHERE relname = 'activity') AS activity_rows,
                (SELECT COUNT(*) FROM user_roles) AS total_users,
                (SELECT COUNT(*) FROM user_roles WHERE role = 'admin') AS admin_users,
                (SELECT COUNT(*) FROM user_roles WHERE role = 'blocked') AS blocked_users,
                (SELECT COUNT(*) FROM favourite) AS total_favourites,
                (SELECT COUNT(*) FROM feedback) AS total_feedback,
                (SELECT COUNT(*) FROM feedback WHERE type = 'bug') AS bug_count,
                (SELECT COUNT(*) FROM feedback WHERE type = 'suggestion') AS suggestion_count,
                (SELECT COUNT(*) FROM feedback WHERE type = 'survey') AS survey_count,
                (SELECT pg_size_pretty(pg_database_size(current_database()))) AS db_size,
                (SELECT COUNT(DISTINCT user_email) FROM activity_log
                 WHERE created_at > NOW() - INTERVAL '24 hours') AS daily_active_users,
                (SELECT endpoint FROM activity_log
                 WHERE created_at > NOW() - INTERVAL '7 days'
                   AND endpoint != '/api/health'
                 GROUP BY endpoint ORDER BY COUNT(*) DESC LIMIT 1) AS most_visited_page,
                (SELECT COUNT(DISTINCT enterprise_number) FROM staatsblad_publication) AS companies_with_staatsblad,

                -- Dataset coverage KPIs
                (SELECT COUNT(DISTINCT fl.enterprise_number) FROM financial_latest fl) AS companies_with_latest_financials,
                (SELECT COUNT(DISTINCT fby.enterprise_number) FROM financial_by_year fby) AS companies_with_history,
                (SELECT COUNT(DISTINCT sp.enterprise_number) FROM staatsblad_publication sp WHERE sp.reference != 'NO_DATA') AS companies_with_publications,
                (SELECT COUNT(DISTINCT a.enterprise_number) FROM administrator a) AS companies_with_admins,
                (SELECT COUNT(DISTINCT sh.enterprise_number) FROM shareholder sh) AS companies_with_shareholders,
                (SELECT COUNT(DISTINCT pi.enterprise_number) FROM participating_interest pi) AS companies_with_subsidiaries,

                -- Data completeness: companies with ALL data types loaded
                (SELECT COUNT(*) FROM (
                    SELECT ci.enterprise_number
                    FROM company_info ci
                    JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
                    JOIN (SELECT DISTINCT enterprise_number FROM administrator) a ON a.enterprise_number = ci.enterprise_number
                    JOIN (SELECT DISTINCT enterprise_number FROM staatsblad_publication WHERE reference != 'NO_DATA') sp ON sp.enterprise_number = ci.enterprise_number
                ) complete) AS fully_loaded_companies,

                -- Conservative target: all active legal-person enterprises
                (SELECT COUNT(*) FROM enterprise WHERE type_of_enterprise = '1' AND status = 'AC') AS target_universe
        """)
        # Add target totals for progress bars
        stats["target_enterprises"] = 1941155
        stats["target_financial_rows"] = 61714163
        stats["target_activity_rows"] = 34874572
        stats["target_companies"] = stats.get("target_universe") or 170000  # active legal-person enterprises
        return stats
    except Exception as e:
        logger.exception("Admin stats failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/financials-by-year")
async def financials_by_year(user=Depends(_require_admin)):
    """Breakdown of companies with financials per fiscal year."""
    try:
        rows = fetch_all("""
            SELECT fiscal_year,
                   COUNT(DISTINCT enterprise_number) AS companies,
                   COUNT(*) AS filings
            FROM financial_by_year
            WHERE fiscal_year >= 2020
            GROUP BY fiscal_year
            ORDER BY fiscal_year DESC
        """)
        return rows
    except Exception as e:
        logger.exception("Financials by year query failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users")
async def list_users(user=Depends(_require_admin)):
    """List all known users."""
    try:
        users = fetch_all("""
            SELECT ur.email, ur.role, ur.created_at,
                   (SELECT COUNT(*) FROM favourite f WHERE f.user_id = ur.email) AS favourites_count,
                   (SELECT COUNT(*) FROM feedback fb WHERE fb.user_email = ur.email) AS feedback_count
            FROM user_roles ur
            ORDER BY ur.created_at DESC
        """)
        for u in users:
            if u.get("created_at"):
                u["created_at"] = str(u["created_at"])
        return users
    except Exception as e:
        logger.exception("List users failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/feedback")
async def list_feedback(user=Depends(_require_admin)):
    """List all feedback."""
    try:
        rows = fetch_all("""
            SELECT id, type, page, description, user_email, created_at, reply, replied_at
            FROM feedback ORDER BY created_at DESC LIMIT 200
        """)
        for r in rows:
            if r.get("created_at"):
                r["created_at"] = str(r["created_at"])
            if r.get("replied_at"):
                r["replied_at"] = str(r["replied_at"])
        return rows
    except Exception as e:
        logger.exception("List feedback failed")
        raise HTTPException(status_code=500, detail=str(e))


class ReplyBody(BaseModel):
    message: str


@router.post("/feedback/{feedback_id}/reply")
async def reply_feedback(feedback_id: int, body: ReplyBody, user=Depends(_require_admin)):
    """Store a reply to feedback."""
    try:
        execute(
            "UPDATE feedback SET reply = %s, replied_at = NOW() WHERE id = %s",
            (body.message, feedback_id),
        )
        return {"status": "replied"}
    except Exception as e:
        logger.exception("Reply failed")
        raise HTTPException(status_code=500, detail=str(e))


class RoleUpdate(BaseModel):
    role: str


@router.post("/users/{email}/role")
async def set_user_role(email: str, body: RoleUpdate, user=Depends(_require_admin)):
    """Set a user's role (admin/user/pro/blocked)."""
    if body.role not in ("admin", "user", "pro", "blocked"):
        raise HTTPException(status_code=400, detail="Role must be admin, user, pro, or blocked")
    try:
        execute(
            """INSERT INTO user_roles (email, role) VALUES (%s, %s)
               ON CONFLICT (email) DO UPDATE SET role = %s""",
            (email, body.role, body.role),
        )
        return {"email": email, "role": body.role}
    except Exception as e:
        logger.exception("Set role failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/users/{email}")
async def delete_user(email: str, user=Depends(_require_admin)):
    """Remove a user entirely."""
    if email == user.get("email"):
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    try:
        execute("DELETE FROM user_roles WHERE email = %s", (email,))
        execute("DELETE FROM favourite WHERE user_id = %s", (email,))
        return {"email": email, "status": "deleted"}
    except Exception as e:
        logger.exception("Delete user failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/feedback/{feedback_id}")
async def delete_feedback(feedback_id: int, user=Depends(_require_admin)):
    """Delete a single feedback entry."""
    try:
        execute("DELETE FROM feedback WHERE id = %s", (feedback_id,))
        return {"id": feedback_id, "status": "deleted"}
    except Exception as e:
        logger.exception("Delete feedback failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/feedback")
async def clear_feedback(user=Depends(_require_admin)):
    """Clear all feedback."""
    try:
        execute("DELETE FROM feedback")
        return {"status": "cleared"}
    except Exception as e:
        logger.exception("Clear feedback failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/insights")
async def admin_insights(user=Depends(_require_admin)):
    """Actionable platform insights: user engagement, data coverage, load health, top companies."""
    try:
        row = fetch_one("""
            SELECT
                -- User engagement
                (SELECT COUNT(*) FROM user_roles) AS total_users,
                (SELECT COUNT(DISTINCT user_email) FROM activity_log
                 WHERE created_at > NOW() - INTERVAL '7 days'
                   AND user_email NOT LIKE 'anon:%%') AS active_users_7d,
                (SELECT COUNT(*) FROM user_roles
                 WHERE created_at > NOW() - INTERVAL '7 days') AS new_users_7d,

                -- Anonymous vs registered traffic (7d)
                (SELECT COUNT(*) FROM activity_log
                 WHERE created_at > NOW() - INTERVAL '7 days'
                   AND user_email LIKE 'anon:%%') AS anon_requests_7d,
                (SELECT COUNT(*) FROM activity_log
                 WHERE created_at > NOW() - INTERVAL '7 days'
                   AND user_email NOT LIKE 'anon:%%') AS auth_requests_7d,

                -- Data coverage
                (SELECT COUNT(DISTINCT enterprise_number) FROM financial_latest) AS companies_with_financials,
                (SELECT COUNT(*) FROM enterprise
                 WHERE type_of_enterprise = '1' AND status = 'AC') AS total_companies,

                -- Load health from nbb_load_log
                (SELECT COUNT(*) FROM nbb_load_log
                 WHERE rubric_count > 0) AS load_success_count,
                (SELECT COUNT(*) FROM nbb_load_log
                 WHERE rubric_count IS NULL OR rubric_count = 0) AS load_error_count,

                -- Previous period comparisons for trend indicators
                (SELECT COUNT(DISTINCT user_email) FROM activity_log
                 WHERE created_at > NOW() - INTERVAL '14 days'
                   AND created_at <= NOW() - INTERVAL '7 days'
                   AND user_email NOT LIKE 'anon:%%') AS active_users_prev_7d,
                (SELECT COUNT(*) FROM user_roles
                 WHERE created_at > NOW() - INTERVAL '14 days'
                   AND created_at <= NOW() - INTERVAL '7 days') AS new_users_prev_7d
        """)

        result = dict(row) if row else {}

        # Compute coverage percentage
        total_co = result.get("total_companies") or 1
        with_fin = result.get("companies_with_financials") or 0
        result["coverage_pct"] = round((with_fin / total_co) * 100, 1)

        # Compute success rate
        success = result.get("load_success_count") or 0
        errors = result.get("load_error_count") or 0
        total_loads = success + errors
        result["success_rate"] = round((success / total_loads) * 100, 1) if total_loads > 0 else 100.0

        # Top 10 most viewed companies
        top_rows = fetch_all("""
            SELECT
                REPLACE(REPLACE(al.endpoint, '/api/company/', ''), '/financials', '') AS cbe,
                COUNT(*) AS view_count
            FROM activity_log al
            WHERE al.endpoint LIKE '/api/company/0%%'
              AND al.created_at > NOW() - INTERVAL '30 days'
            GROUP BY cbe
            ORDER BY view_count DESC
            LIMIT 10
        """)

        # Enrich with company names — single query instead of N+1.
        cleaned = []
        for r in top_rows:
            cbe = r.get("cbe", "")
            if "/" in cbe:
                cbe = cbe.split("/")[0]
            cleaned.append((cbe, r["view_count"]))

        name_by_cbe = {}
        if cleaned:
            cbes = [c for c, _ in cleaned]
            placeholders = ",".join(["%s"] * len(cbes))
            name_rows = fetch_all(
                f"SELECT enterprise_number, name FROM company_info "
                f"WHERE enterprise_number IN ({placeholders})",
                tuple(cbes),
            )
            name_by_cbe = {row["enterprise_number"]: row["name"] for row in name_rows}

        top_companies = [
            {"cbe": cbe, "name": name_by_cbe.get(cbe, cbe), "view_count": vc}
            for cbe, vc in cleaned
        ]
        result["top_companies"] = top_companies

        return result
    except Exception as e:
        logger.exception("Admin insights failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/activity")
async def get_activity(user=Depends(_require_admin)):
    """Recent user activity across the platform."""
    try:
        rows = fetch_all("""
            SELECT user_email, endpoint, method, created_at
            FROM activity_log
            ORDER BY created_at DESC
            LIMIT 200
        """)
        for r in rows:
            if r.get("created_at"):
                r["created_at"] = str(r["created_at"])
        return rows
    except Exception as e:
        logger.exception("Activity log failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/activity/summary")
async def activity_summary(user=Depends(_require_admin)):
    """Activity summary: requests per user in last 24h."""
    try:
        rows = fetch_all("""
            SELECT user_email,
                   COUNT(*) AS total_requests,
                   COUNT(DISTINCT endpoint) AS unique_pages,
                   MAX(created_at) AS last_active
            FROM activity_log
            WHERE created_at > NOW() - INTERVAL '7 days'
            GROUP BY user_email
            ORDER BY total_requests DESC
        """)
        for r in rows:
            if r.get("last_active"):
                r["last_active"] = str(r["last_active"])
        return rows
    except Exception as e:
        logger.exception("Activity summary failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/usage")
async def platform_usage(user=Depends(_require_admin)):
    """Detailed platform usage analytics: daily breakdown, registered vs guest, top pages, top users."""
    try:
        import decimal, datetime

        # Daily request counts (last 30 days), split by registered/guest
        daily = fetch_all("""
            SELECT
                created_at::date AS day,
                COUNT(*) FILTER (WHERE user_email NOT LIKE 'anon:%%') AS registered_requests,
                COUNT(*) FILTER (WHERE user_email LIKE 'anon:%%') AS guest_requests,
                COUNT(DISTINCT user_email) FILTER (WHERE user_email NOT LIKE 'anon:%%') AS unique_registered,
                COUNT(DISTINCT user_email) FILTER (WHERE user_email LIKE 'anon:%%') AS unique_guests
            FROM activity_log
            WHERE created_at > NOW() - INTERVAL '30 days'
            GROUP BY created_at::date
            ORDER BY day DESC
        """)

        # Top pages (last 7 days)
        top_pages = fetch_all("""
            SELECT
                CASE
                    WHEN endpoint LIKE '%%/financials' THEN 'Company Financials'
                    WHEN endpoint LIKE '%%/structure' THEN 'Company Structure'
                    WHEN endpoint LIKE '%%/sector-benchmark' THEN 'Sector Benchmark'
                    WHEN endpoint LIKE '%%/network' THEN 'Company Network'
                    WHEN endpoint LIKE '/api/companies/search%%' THEN 'Company Search'
                    WHEN endpoint LIKE '/api/people/search%%' THEN 'People Search'
                    WHEN endpoint LIKE '/api/screener%%' THEN 'Screener'
                    WHEN endpoint LIKE '/api/companies/%%/load' THEN 'NBB Data Load'
                    WHEN endpoint LIKE '/api/staatsblad/%%' THEN 'Publications Load'
                    WHEN endpoint LIKE '/api/favourites%%' THEN 'Favourites'
                    WHEN endpoint = '/api/dashboard' THEN 'Homepage'
                    ELSE endpoint
                END AS page,
                COUNT(*) AS requests,
                COUNT(DISTINCT user_email) AS unique_users
            FROM activity_log
            WHERE created_at > NOW() - INTERVAL '7 days'
            GROUP BY 1
            ORDER BY requests DESC
            LIMIT 15
        """)

        # Top registered users (last 7 days)
        top_registered = fetch_all("""
            SELECT user_email, COUNT(*) AS requests,
                   COUNT(DISTINCT endpoint) AS unique_pages,
                   MAX(created_at) AS last_seen
            FROM activity_log
            WHERE created_at > NOW() - INTERVAL '7 days'
              AND user_email NOT LIKE 'anon:%%'
            GROUP BY user_email
            ORDER BY requests DESC
            LIMIT 20
        """)

        # Top guest IPs (last 7 days)
        top_guests = fetch_all("""
            SELECT user_email AS ip, COUNT(*) AS requests,
                   COUNT(DISTINCT endpoint) AS unique_pages,
                   MAX(created_at) AS last_seen
            FROM activity_log
            WHERE created_at > NOW() - INTERVAL '7 days'
              AND user_email LIKE 'anon:%%'
            GROUP BY user_email
            ORDER BY requests DESC
            LIMIT 20
        """)

        # Summary totals
        totals = fetch_one("""
            SELECT
                COUNT(*) AS total_requests_30d,
                COUNT(*) FILTER (WHERE user_email LIKE 'anon:%%') AS guest_requests_30d,
                COUNT(*) FILTER (WHERE user_email NOT LIKE 'anon:%%') AS registered_requests_30d,
                COUNT(DISTINCT user_email) FILTER (WHERE user_email NOT LIKE 'anon:%%') AS unique_registered_30d,
                COUNT(DISTINCT user_email) FILTER (WHERE user_email LIKE 'anon:%%') AS unique_guests_30d
            FROM activity_log
            WHERE created_at > NOW() - INTERVAL '30 days'
        """)

        def serialize(rows):
            result = []
            for r in rows:
                row = {}
                for k, v in r.items():
                    if isinstance(v, decimal.Decimal):
                        row[k] = float(v)
                    elif isinstance(v, (datetime.date, datetime.datetime)):
                        row[k] = str(v)
                    else:
                        row[k] = v
                result.append(row)
            return result

        return {
            "daily": serialize(daily),
            "top_pages": serialize(top_pages),
            "top_registered": serialize(top_registered),
            "top_guests": serialize(top_guests),
            "totals": {k: (float(v) if isinstance(v, decimal.Decimal) else v) for k, v in (totals or {}).items()},
        }
    except Exception as e:
        logger.exception("Usage analytics failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/traction")
async def traction_dashboard(user=Depends(_require_admin)):
    """Platform traction dashboard: unique guests, engagement depth, conversion signals, feature adoption."""
    try:
        import decimal, datetime as dt

        def _ser(rows):
            out = []
            for r in rows:
                row = {}
                for k, v in r.items():
                    if isinstance(v, decimal.Decimal): row[k] = float(v)
                    elif isinstance(v, (dt.date, dt.datetime)): row[k] = str(v)
                    else: row[k] = v
                out.append(row)
            return out

        def _ser1(r):
            if not r: return {}
            return {k: (float(v) if isinstance(v, decimal.Decimal) else str(v) if isinstance(v, (dt.date, dt.datetime)) else v) for k, v in r.items()}

        # Admin emails to exclude from traction metrics
        admin_rows = fetch_all("SELECT email FROM user_roles WHERE role = 'admin'")
        admin_emails = [r["email"] for r in admin_rows] if admin_rows else []
        admin_filter = ""
        admin_params: list = []
        if admin_emails:
            placeholders = ",".join(["%s"] * len(admin_emails))
            admin_filter = f" AND user_email NOT IN ({placeholders})"
            admin_params = list(admin_emails)

        # KPIs: unique guests and registered users across time windows (excl admins)
        kpis = _ser1(fetch_one(f"""
            SELECT
                COUNT(DISTINCT user_email) FILTER (WHERE user_email LIKE 'anon:%%' AND created_at > NOW() - INTERVAL '1 day') AS guests_today,
                COUNT(DISTINCT user_email) FILTER (WHERE user_email LIKE 'anon:%%' AND created_at > NOW() - INTERVAL '7 days') AS guests_7d,
                COUNT(DISTINCT user_email) FILTER (WHERE user_email LIKE 'anon:%%' AND created_at > NOW() - INTERVAL '30 days') AS guests_30d,
                COUNT(DISTINCT user_email) FILTER (WHERE user_email NOT LIKE 'anon:%%' AND created_at > NOW() - INTERVAL '1 day') AS registered_today,
                COUNT(DISTINCT user_email) FILTER (WHERE user_email NOT LIKE 'anon:%%' AND created_at > NOW() - INTERVAL '7 days') AS registered_7d,
                COUNT(DISTINCT user_email) FILTER (WHERE user_email NOT LIKE 'anon:%%' AND created_at > NOW() - INTERVAL '30 days') AS registered_30d,
                COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '1 day') AS requests_today,
                COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '7 days') AS requests_7d,
                COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '30 days') AS requests_30d
            FROM activity_log
            WHERE 1=1 {admin_filter}
        """, tuple(admin_params) or None))

        # Engagement: avg pages per guest per day (7d)
        engagement = _ser1(fetch_one(f"""
            SELECT
                ROUND(AVG(pages)::numeric, 1) AS avg_pages_per_guest,
                ROUND(AVG(reqs)::numeric, 1) AS avg_requests_per_guest,
                MAX(pages) AS max_pages_guest
            FROM (
                SELECT user_email, COUNT(DISTINCT endpoint) AS pages, COUNT(*) AS reqs
                FROM activity_log
                WHERE user_email LIKE 'anon:%%' AND created_at > NOW() - INTERVAL '7 days' {admin_filter}
                GROUP BY user_email
            ) sub
        """, tuple(admin_params) or None))

        # Daily trend: unique guests + registered (30d, excl admins)
        daily_trend = _ser(fetch_all(f"""
            SELECT
                created_at::date AS day,
                COUNT(DISTINCT user_email) FILTER (WHERE user_email LIKE 'anon:%%') AS unique_guests,
                COUNT(DISTINCT user_email) FILTER (WHERE user_email NOT LIKE 'anon:%%') AS unique_registered,
                COUNT(*) AS total_requests
            FROM activity_log
            WHERE created_at > NOW() - INTERVAL '30 days' {admin_filter}
            GROUP BY created_at::date
            ORDER BY day ASC
        """, tuple(admin_params) or None))

        # Hourly usage today in Belgian time (excl admins).
        # Use a half-open timestamp range against Brussels midnight so the
        # filter works regardless of DB session timezone. The earlier
        # (created_at AT TIME ZONE 'Europe/Brussels')::date = today version
        # silently dropped rows around timezone boundaries.
        hourly_today = _ser(fetch_all(f"""
            SELECT
                EXTRACT(HOUR FROM created_at AT TIME ZONE 'Europe/Brussels')::int AS hour,
                COUNT(*) AS requests,
                COUNT(DISTINCT user_email) FILTER (WHERE user_email LIKE 'anon:%%') AS guests,
                COUNT(DISTINCT user_email) FILTER (WHERE user_email NOT LIKE 'anon:%%') AS registered
            FROM activity_log
            WHERE created_at >= date_trunc('day', NOW() AT TIME ZONE 'Europe/Brussels') AT TIME ZONE 'Europe/Brussels'
              AND created_at <  (date_trunc('day', NOW() AT TIME ZONE 'Europe/Brussels') + INTERVAL '1 day') AT TIME ZONE 'Europe/Brussels'
              {admin_filter}
            GROUP BY 1
            ORDER BY 1
        """, tuple(admin_params) or None))

        # Guest behavior: top pages visited by guests (7d, excl admins)
        guest_pages = _ser(fetch_all(f"""
            SELECT
                CASE
                    WHEN endpoint LIKE '%%/search%%' THEN 'Search'
                    WHEN endpoint LIKE '%%/screener%%' THEN 'Screener'
                    WHEN endpoint LIKE '%%/financials' THEN 'Company Financials'
                    WHEN endpoint LIKE '%%/structure' THEN 'Company Structure'
                    WHEN endpoint LIKE '%%/similar' THEN 'Similar Companies'
                    WHEN endpoint LIKE '%%/sector-benchmark' THEN 'Sector Benchmark'
                    WHEN endpoint LIKE '%%/load' THEN 'NBB Data Load'
                    WHEN endpoint LIKE '%%/ai-insights' THEN 'AI Insights'
                    WHEN endpoint LIKE '%%/enrich%%' THEN 'AI Enrichment'
                    WHEN endpoint LIKE '%%/staatsblad%%' THEN 'Publications'
                    WHEN endpoint LIKE '%%/favourites%%' THEN 'Favourites'
                    WHEN endpoint LIKE '/api/people%%' THEN 'People Search'
                    WHEN endpoint ~ '^/api/companies/[0-9]{10}$' THEN 'Company Detail'
                    ELSE endpoint
                END AS feature,
                COUNT(*) AS requests,
                COUNT(DISTINCT user_email) AS unique_guests
            FROM activity_log
            WHERE user_email LIKE 'anon:%%' AND created_at > NOW() - INTERVAL '7 days' {admin_filter}
            GROUP BY 1
            ORDER BY unique_guests DESC
            LIMIT 15
        """, tuple(admin_params) or None))

        # Registered user behavior: same breakdown (excl admins)
        registered_pages = _ser(fetch_all(f"""
            SELECT
                CASE
                    WHEN endpoint LIKE '%%/search%%' THEN 'Search'
                    WHEN endpoint LIKE '%%/screener%%' THEN 'Screener'
                    WHEN endpoint LIKE '%%/financials' THEN 'Company Financials'
                    WHEN endpoint LIKE '%%/structure' THEN 'Company Structure'
                    WHEN endpoint LIKE '%%/similar' THEN 'Similar Companies'
                    WHEN endpoint LIKE '%%/sector-benchmark' THEN 'Sector Benchmark'
                    WHEN endpoint LIKE '%%/load' THEN 'NBB Data Load'
                    WHEN endpoint LIKE '%%/ai-insights' THEN 'AI Insights'
                    WHEN endpoint LIKE '%%/enrich%%' THEN 'AI Enrichment'
                    WHEN endpoint LIKE '%%/staatsblad%%' THEN 'Publications'
                    WHEN endpoint LIKE '%%/favourites%%' THEN 'Favourites'
                    WHEN endpoint LIKE '/api/people%%' THEN 'People Search'
                    WHEN endpoint ~ '^/api/companies/[0-9]{10}$' THEN 'Company Detail'
                    ELSE endpoint
                END AS feature,
                COUNT(*) AS requests,
                COUNT(DISTINCT user_email) AS unique_users
            FROM activity_log
            WHERE user_email NOT LIKE 'anon:%%' AND created_at > NOW() - INTERVAL '7 days' {admin_filter}
            GROUP BY 1
            ORDER BY unique_users DESC
            LIMIT 15
        """, tuple(admin_params) or None))

        # New user signups per day (30d)
        signups = _ser(fetch_all("""
            SELECT created_at::date AS day, COUNT(*) AS new_users
            FROM user_roles
            WHERE created_at > NOW() - INTERVAL '30 days'
            GROUP BY created_at::date
            ORDER BY day ASC
        """))

        # Stickiness: users who came back multiple days (7d, excl admins)
        stickiness = _ser(fetch_all(f"""
            SELECT days_active, COUNT(*) AS user_count
            FROM (
                SELECT user_email, COUNT(DISTINCT created_at::date) AS days_active
                FROM activity_log
                WHERE created_at > NOW() - INTERVAL '7 days'
                  AND user_email NOT LIKE 'anon:%%' {admin_filter}
                GROUP BY user_email
            ) sub
            GROUP BY days_active
            ORDER BY days_active
        """, tuple(admin_params) or None))

        # Most engaged guests: top 10 by pages visited
        top_guests = _ser(fetch_all(f"""
            SELECT
                REPLACE(user_email, 'anon:', '') AS ip,
                COUNT(DISTINCT endpoint) AS unique_pages,
                COUNT(*) AS total_requests,
                MIN(created_at) AS first_seen,
                MAX(created_at) AS last_seen
            FROM activity_log
            WHERE user_email LIKE 'anon:%%' AND created_at > NOW() - INTERVAL '7 days' {admin_filter}
            GROUP BY user_email
            ORDER BY unique_pages DESC
            LIMIT 10
        """, tuple(admin_params) or None))

        return {
            "kpis": kpis,
            "engagement": engagement,
            "daily_trend": daily_trend,
            "hourly_today": hourly_today,
            "guest_pages": guest_pages,
            "registered_pages": registered_pages,
            "signups": signups,
            "stickiness": stickiness,
            "top_guests": top_guests,
        }
    except Exception as e:
        logger.exception("Traction dashboard failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/adoption")
async def adoption_dashboard(user=Depends(_require_admin)):
    """Adoption dashboard: KPIs, daily trend, feature breakdown, top users, recent activity."""
    try:
        import decimal, datetime as dt

        # ---- Adoption KPI cards ----
        kpis = fetch_one("""
            SELECT
                (SELECT COUNT(*) FROM user_roles) AS total_registered,
                (SELECT COUNT(DISTINCT user_email) FROM activity_log
                 WHERE created_at > NOW() - INTERVAL '7 days'
                   AND user_email NOT LIKE 'anon:%%') AS active_7d,
                (SELECT COUNT(DISTINCT user_email) FROM activity_log
                 WHERE created_at > NOW() - INTERVAL '30 days'
                   AND user_email NOT LIKE 'anon:%%') AS active_30d,
                (SELECT COUNT(DISTINCT user_email) FROM activity_log
                 WHERE created_at::date = CURRENT_DATE
                   AND user_email NOT LIKE 'anon:%%') AS sessions_today,
                -- Previous-period comparisons
                (SELECT COUNT(DISTINCT user_email) FROM activity_log
                 WHERE created_at > NOW() - INTERVAL '14 days'
                   AND created_at <= NOW() - INTERVAL '7 days'
                   AND user_email NOT LIKE 'anon:%%') AS active_prev_7d,
                (SELECT COUNT(DISTINCT user_email) FROM activity_log
                 WHERE created_at > NOW() - INTERVAL '60 days'
                   AND created_at <= NOW() - INTERVAL '30 days'
                   AND user_email NOT LIKE 'anon:%%') AS active_prev_30d,
                (SELECT COUNT(DISTINCT user_email) FROM activity_log
                 WHERE created_at::date = CURRENT_DATE - 1
                   AND user_email NOT LIKE 'anon:%%') AS sessions_yesterday
        """)

        # ---- Daily trend (last 30 days): DAU + page views ----
        daily_trend = fetch_all("""
            SELECT
                (created_at AT TIME ZONE 'Europe/Brussels')::date AS day,
                COUNT(DISTINCT user_email) FILTER (WHERE user_email NOT LIKE 'anon:%%') AS dau,
                COUNT(*) AS page_views
            FROM activity_log
            WHERE created_at > NOW() - INTERVAL '30 days'
            GROUP BY 1
            ORDER BY 1 ASC
        """)

        # ---- Feature breakdown (last 7 days) ----
        features = fetch_all("""
            SELECT
                CASE
                    WHEN endpoint LIKE '/api/companies/search%%' THEN 'Company Search'
                    WHEN endpoint LIKE '/api/people/search%%' THEN 'People Search'
                    WHEN endpoint LIKE '/api/screener%%' THEN 'Screener'
                    WHEN endpoint LIKE '%%/financials' THEN 'Financials'
                    WHEN endpoint LIKE '%%/structure' THEN 'Company Structure'
                    WHEN endpoint LIKE '%%/sector-benchmark' THEN 'Sector Benchmark'
                    WHEN endpoint LIKE '%%/network' THEN 'Network Graph'
                    WHEN endpoint LIKE '/api/companies/%%/compare%%' THEN 'Compare'
                    WHEN endpoint LIKE '/api/companies/%%/load' THEN 'NBB Data Load'
                    WHEN endpoint LIKE '/api/staatsblad/%%' THEN 'Publications'
                    WHEN endpoint LIKE '/api/favourites%%' THEN 'Favourites'
                    WHEN endpoint LIKE '/api/dashboard' THEN 'Dashboard'
                    WHEN endpoint LIKE '/api/company/0%%' THEN 'Company Profile'
                    WHEN endpoint LIKE '/api/ai%%' OR endpoint LIKE '%%/enrich%%' THEN 'AI Insights'
                    WHEN endpoint LIKE '/api/export%%' THEN 'Export'
                    ELSE NULL
                END AS feature,
                COUNT(*) AS requests,
                COUNT(DISTINCT user_email) AS unique_users
            FROM activity_log
            WHERE created_at > NOW() - INTERVAL '7 days'
            GROUP BY 1
            HAVING CASE
                    WHEN endpoint LIKE '/api/companies/search%%' THEN 'Company Search'
                    WHEN endpoint LIKE '/api/people/search%%' THEN 'People Search'
                    WHEN endpoint LIKE '/api/screener%%' THEN 'Screener'
                    WHEN endpoint LIKE '%%/financials' THEN 'Financials'
                    WHEN endpoint LIKE '%%/structure' THEN 'Company Structure'
                    WHEN endpoint LIKE '%%/sector-benchmark' THEN 'Sector Benchmark'
                    WHEN endpoint LIKE '%%/network' THEN 'Network Graph'
                    WHEN endpoint LIKE '/api/companies/%%/compare%%' THEN 'Compare'
                    WHEN endpoint LIKE '/api/companies/%%/load' THEN 'NBB Data Load'
                    WHEN endpoint LIKE '/api/staatsblad/%%' THEN 'Publications'
                    WHEN endpoint LIKE '/api/favourites%%' THEN 'Favourites'
                    WHEN endpoint LIKE '/api/dashboard' THEN 'Dashboard'
                    WHEN endpoint LIKE '/api/company/0%%' THEN 'Company Profile'
                    WHEN endpoint LIKE '/api/ai%%' OR endpoint LIKE '%%/enrich%%' THEN 'AI Insights'
                    WHEN endpoint LIKE '/api/export%%' THEN 'Export'
                    ELSE NULL
                END IS NOT NULL
            ORDER BY requests DESC
            LIMIT 15
        """)

        # ---- Top users (last 30 days, by session count) ----
        top_users = fetch_all("""
            SELECT
                user_email AS email,
                COUNT(DISTINCT (created_at AT TIME ZONE 'Europe/Brussels')::date) AS session_days,
                COUNT(*) AS total_requests,
                MAX(created_at AT TIME ZONE 'Europe/Brussels') AS last_active
            FROM activity_log
            WHERE created_at > NOW() - INTERVAL '30 days'
              AND user_email NOT LIKE 'anon:%%'
            GROUP BY user_email
            ORDER BY session_days DESC, total_requests DESC
            LIMIT 10
        """)

        # ---- Recent activity (last 50, with Belgian timestamps) ----
        recent = fetch_all("""
            SELECT
                user_email,
                endpoint,
                method,
                created_at AT TIME ZONE 'Europe/Brussels' AS created_at_be
            FROM activity_log
            ORDER BY created_at DESC
            LIMIT 50
        """)

        def _ser(val):
            if isinstance(val, decimal.Decimal):
                return float(val)
            if isinstance(val, (dt.date, dt.datetime)):
                return str(val)
            return val

        def serialize_rows(rows):
            return [{k: _ser(v) for k, v in r.items()} for r in rows]

        return {
            "kpis": {k: _ser(v) for k, v in (kpis or {}).items()},
            "daily_trend": serialize_rows(daily_trend),
            "features": serialize_rows(features),
            "top_users": serialize_rows(top_users),
            "recent": serialize_rows(recent),
        }
    except Exception as e:
        logger.exception("Adoption dashboard failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/payments")
async def admin_payments(user=Depends(_require_admin)):
    """List recent Stripe payments for the admin dashboard."""
    if not stripe.api_key:
        return {"payments": [], "total_revenue": 0, "currency": "eur"}

    try:
        sessions = stripe.checkout.Session.list(limit=20)
        payments = []
        total_revenue = 0

        for s in sessions.data:
            amount = s.amount_total or 0
            currency = s.currency or "eur"
            status = s.payment_status or s.status or "unknown"
            email = s.customer_email or (s.customer_details.email if s.customer_details else None)
            created = datetime.fromtimestamp(s.created, tz=timezone.utc).isoformat()

            payments.append({
                "id": s.id,
                "amount": amount,
                "currency": currency,
                "status": status,
                "email": email or None,
                "created": created,
                "mode": s.mode,  # "payment" or "subscription"
            })

            if status == "paid":
                total_revenue += amount

        return {
            "payments": payments,
            "total_revenue": total_revenue,
            "currency": "eur",
        }
    except Exception as e:
        logger.exception("Admin payments failed")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# GET /api/admin/arr — Annualised Recurring Revenue from Stripe
# ---------------------------------------------------------------------------

@router.get("/arr")
async def admin_arr(user=Depends(_require_admin)):
    """ARR = sum of successful Stripe charges in the last 28 days × 13.

    Weekly breakdown lets the operator see if the run-rate is trending up or
    down. Subscription_count is the distinct paying-customer count today.
    Currency-aware: amounts are summed in the charge's own currency and
    returned separately so mixed-currency books don't lie. Most DataSnoop
    charges are in EUR.
    """
    if not stripe.api_key:
        return {
            "arr": 0, "currency": "eur", "weekly": [],
            "subscribers": 0, "note": "Stripe not configured",
        }

    try:
        import time as _time
        now = int(_time.time())
        four_weeks_ago = now - 28 * 86400

        # All successful charges in the last 28 days. Pagination safeguard:
        # Stripe returns 100 per page; we walk `has_more` until exhausted.
        charges: list = []
        starting_after = None
        while True:
            params = {
                "created": {"gte": four_weeks_ago, "lt": now},
                "limit": 100,
            }
            if starting_after:
                params["starting_after"] = starting_after
            page = stripe.Charge.list(**params)
            charges.extend(page.data)
            if not page.has_more:
                break
            starting_after = page.data[-1].id
            if len(charges) > 5000:  # sanity cap
                break

        # Per-week buckets (7-day windows, newest first)
        weekly = []
        for w in range(4):
            start = now - (w + 1) * 7 * 86400
            end = now - w * 7 * 86400
            bucket_total = 0
            bucket_count = 0
            for c in charges:
                if c.status != "succeeded":
                    continue
                if c.refunded:
                    continue
                if start <= c.created < end:
                    bucket_total += c.amount  # cents
                    bucket_count += 1
            weekly.append({
                "week_start": datetime.fromtimestamp(start, tz=timezone.utc).date().isoformat(),
                "week_end": datetime.fromtimestamp(end, tz=timezone.utc).date().isoformat(),
                "gross_cents": bucket_total,
                "gross_eur": round(bucket_total / 100.0, 2),
                "charges": bucket_count,
            })
        weekly.reverse()  # oldest first for chart rendering

        # Total 4-week revenue across succeeded, non-refunded charges
        last_4w_cents = sum(
            c.amount for c in charges
            if c.status == "succeeded" and not c.refunded
        )
        arr_cents = last_4w_cents * 13
        arr_eur = round(arr_cents / 100.0, 2)

        # Distinct paying customers RIGHT NOW (active subscriptions).
        # Separate from revenue — counts heads, not money.
        active_subs = 0
        try:
            sub_page = stripe.Subscription.list(status="active", limit=100)
            active_subs = len(sub_page.data)
            while sub_page.has_more:
                sub_page = stripe.Subscription.list(
                    status="active", limit=100,
                    starting_after=sub_page.data[-1].id,
                )
                active_subs += len(sub_page.data)
        except Exception as e:
            logger.warning("Subscription count failed: %s", e)

        return {
            "arr_eur": arr_eur,
            "last_4w_eur": round(last_4w_cents / 100.0, 2),
            "multiplier": 13,
            "currency": "eur",
            "weekly": weekly,
            "active_subscribers": active_subs,
            "window_days": 28,
            "as_of": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.exception("Admin ARR failed")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# GET /api/admin/invoices — inbox-ingested invoices for the P&L cost side
# ---------------------------------------------------------------------------

@router.get("/invoices")
async def admin_invoices(user=Depends(_require_admin)):
    """Return the last 50 invoices ingested from invoice@datasnoop.be plus
    rolling monthly totals so the admin page can render a cost column next
    to the ARR card.
    """
    try:
        rows = fetch_all(
            """SELECT id, sender, subject, received_at, invoice_date,
                      amount_cents, currency, vendor, category, confirmed
               FROM platform_invoice
               ORDER BY COALESCE(invoice_date, received_at::date) DESC
               LIMIT 50"""
        )
        for r in rows:
            for key in ("received_at", "invoice_date"):
                if r.get(key):
                    r[key] = r[key].isoformat() if hasattr(r[key], "isoformat") else str(r[key])

        # Monthly totals for the last 6 calendar months
        monthly = fetch_all(
            """SELECT to_char(date_trunc('month', COALESCE(invoice_date, received_at::date)), 'YYYY-MM') AS ym,
                      SUM(amount_cents) AS cents_total,
                      COUNT(*) AS invoices
               FROM platform_invoice
               WHERE amount_cents IS NOT NULL
                 AND COALESCE(invoice_date, received_at::date) >= (CURRENT_DATE - INTERVAL '6 months')
               GROUP BY 1
               ORDER BY 1 DESC"""
        )
        for m in monthly:
            m["eur_total"] = round((m.get("cents_total") or 0) / 100.0, 2)

        return {"invoices": rows, "monthly": monthly}
    except Exception as e:
        logger.exception("Admin invoices failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/invoices/{invoice_id}/confirm")
async def admin_confirm_invoice(invoice_id: int, body: dict, user=Depends(_require_admin)):
    """Operator override: set confirmed=true, optionally override
    amount_cents / category / vendor."""
    fields = []
    params: list = []
    for key in ("amount_cents", "category", "vendor"):
        if key in body and body[key] is not None:
            fields.append(f"{key} = %s")
            params.append(body[key])
    fields.append("confirmed = TRUE")
    params.append(invoice_id)
    sql = f"UPDATE platform_invoice SET {', '.join(fields)} WHERE id = %s"
    try:
        execute(sql, tuple(params))
        return {"status": "confirmed"}
    except Exception as e:
        logger.exception("Confirm invoice failed")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# GET /api/admin/costs — OpenRouter + fixed costs for mini P&L
# ---------------------------------------------------------------------------

@router.get("/costs")
async def admin_costs(user=Depends(_require_admin)):
    """Platform costs: OpenRouter AI spend, hosting, domains."""
    import httpx

    # ── OpenRouter credit usage (lifetime USD spend) ──
    openrouter_usage_usd = 0.0
    openrouter_limit_usd = 0.0
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
    if openrouter_key:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://openrouter.ai/api/v1/auth/key",
                    headers={"Authorization": f"Bearer {openrouter_key}"},
                    timeout=10,
                )
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    openrouter_usage_usd = data.get("usage", 0)
                    openrouter_limit_usd = data.get("limit", 0)
        except Exception as e:
            logger.warning("OpenRouter usage fetch failed: %s", e)

    # ── Custom cost items (editable via POST /api/admin/costs) ──
    cost_items = []
    row = fetch_one("SELECT value FROM meta WHERE variable = 'cost_items'")
    if row and row.get("value"):
        try:
            cost_items = json.loads(row["value"])
        except Exception:
            pass
    if not cost_items:
        # Default items if none configured yet
        cost_items = [
            {"name": "Hosting (Hetzner)", "amount": 18.34, "frequency": "monthly"},
            {"name": "Domains", "amount": 25.00, "frequency": "yearly"},
        ]

    # ── AI call counts (last 30 days) ──
    ai_calls = fetch_one("""
        SELECT
            COUNT(*) FILTER (WHERE endpoint LIKE '%%/ai-insights') AS ai_insights,
            COUNT(*) FILTER (WHERE endpoint LIKE '%%/summarize-publications') AS pub_summaries,
            COUNT(*) FILTER (WHERE endpoint LIKE '%%/similar/ai') AS similar_ai,
            COUNT(*) FILTER (WHERE endpoint LIKE '%%/enrich') AS enrichments,
            COUNT(*) FILTER (WHERE endpoint LIKE '%%/scrape-%%') AS scrapes
        FROM activity_log
        WHERE created_at > NOW() - INTERVAL '30 days'
    """) or {}

    return {
        "openrouter_usage_usd": openrouter_usage_usd,
        "openrouter_limit_usd": openrouter_limit_usd,
        "cost_items": cost_items,
        "ai_calls_30d": {k: int(v) if v else 0 for k, v in ai_calls.items()},
    }


# ---------------------------------------------------------------------------
# GET /api/admin/llm-cost-breakdown — per-call-type real OpenRouter cost
# ---------------------------------------------------------------------------

@router.get("/llm-cost-breakdown")
async def admin_llm_cost_breakdown(
    days: int = 30,
    user=Depends(_require_admin),
):
    """Per-call-type LLM cost breakdown for the admin panel.

    Aggregates the real ``usage.cost`` logged by ``ai_client.ai_complete``
    into ``llm_call_log`` since the last container restart. Rows are
    grouped by user-facing feature using the same pattern matching the
    tier middleware uses for endpoint classification; calls made outside
    a recognised feature path fall into the ``other`` bucket.

    Use ``/api/admin/costs`` for the authoritative lifetime spend reported
    by OpenRouter; this endpoint shows the *attribution* by feature.
    """
    days = max(1, min(days, 365))
    rows = fetch_all(f"""
        SELECT
            CASE
                WHEN endpoint LIKE '%%/ai-insights%%'                                   THEN 'ai-insights'
                WHEN endpoint LIKE '%%/ai-commentary%%'                                 THEN 'ai-commentary'
                WHEN endpoint LIKE '%%/extract-admins%%'                                THEN 'extract-admins'
                WHEN endpoint LIKE '%%/summarize-publications%%'                        THEN 'summarize-publications'
                WHEN endpoint LIKE '%%/scrape-website%%'                                THEN 'scrape-website'
                WHEN endpoint LIKE '%%/scrape-linkedin%%'                               THEN 'scrape-linkedin'
                WHEN endpoint LIKE '%%/similar/ai%%'                                    THEN 'similar-ai'
                WHEN endpoint LIKE '%%/enrich%%' AND endpoint NOT LIKE '%%/enrichment%%' THEN 'enrich'
                WHEN endpoint LIKE '%%/screener/nl%%'                                   THEN 'screener-nl'
                ELSE 'other'
            END AS kind,
            COUNT(*) AS calls,
            COALESCE(SUM(cost_usd), 0) AS total_cost_usd,
            COALESCE(AVG(cost_usd), 0) AS avg_cost_usd
        FROM llm_call_log
        WHERE ts >= NOW() - INTERVAL '{days} days'
        GROUP BY kind
    """)

    breakdown = []
    grand_total = 0.0
    grand_calls = 0
    for r in rows or []:
        calls = int(r.get("calls") or 0)
        total = float(r.get("total_cost_usd") or 0.0)
        avg = float(r.get("avg_cost_usd") or 0.0)
        breakdown.append({
            "kind": r.get("kind") or "other",
            "calls": calls,
            "est_cost_per_call_usd": round(avg, 6),
            "est_total_usd": round(total, 4),
        })
        grand_total += total
        grand_calls += calls

    breakdown.sort(key=lambda r: r["est_total_usd"], reverse=True)

    return {
        "window_days": days,
        "calls_total": grand_calls,
        "est_total_usd": round(grand_total, 4),
        "est_avg_per_call_usd": round(grand_total / grand_calls, 6) if grand_calls else 0.0,
        "breakdown": breakdown,
        "note": (
            "Costs are real per-call OpenRouter billed amounts captured "
            "via `usage: {include: true}`, grouped by user-facing feature. "
            "For lifetime authoritative spend see `openrouter_usage_usd` "
            "in /api/admin/costs."
        ),
    }


class CostItemsBody(BaseModel):
    items: list[dict]  # [{"name": "Hosting", "amount": 18.34, "frequency": "monthly"}]


@router.post("/costs")
async def update_costs(body: CostItemsBody, user=Depends(_require_admin)):
    """Save custom cost line items."""
    execute(
        "INSERT INTO meta (variable, value) VALUES (%s, %s) ON CONFLICT (variable) DO UPDATE SET value = EXCLUDED.value",
        ("cost_items", json.dumps(body.items)),
    )
    return {"status": "ok", "count": len(body.items)}


# ---------------------------------------------------------------------------
# POST /api/admin/embed-all — batch-embed companies with AI insights
# ---------------------------------------------------------------------------

@router.post("/embed-all")
async def admin_embed_all(user=Depends(_require_admin)):
    """Generate embeddings for all companies with AI insights that don't have one yet."""
    from embeddings import batch_embed_all
    result = await batch_embed_all(limit=500)
    return result


# ---------------------------------------------------------------------------
# Site configuration (logo, etc.)
# ---------------------------------------------------------------------------

_SITE_CONFIG_DEFAULTS = {
    "site_logo": "/logos/dog-telescope.jpg",
}


@router.get("/site-config")
async def get_site_config(user=Depends(_require_admin)):
    """Return current site configuration from the meta table."""
    try:
        config = {}
        for key, default in _SITE_CONFIG_DEFAULTS.items():
            row = fetch_one(
                "SELECT value FROM meta WHERE variable = %s", (key,)
            )
            config[key] = row["value"] if row else default
        return config
    except Exception as e:
        logger.exception("Get site config failed")
        raise HTTPException(status_code=500, detail=str(e))


class SiteConfigUpdate(BaseModel):
    site_logo: Optional[str] = None


@router.put("/site-config")
async def update_site_config(body: SiteConfigUpdate, user=Depends(_require_admin)):
    """Update site configuration values in the meta table."""
    try:
        updated = {}
        if body.site_logo is not None:
            execute(
                "INSERT INTO meta (variable, value) VALUES (%s, %s) "
                "ON CONFLICT (variable) DO UPDATE SET value = EXCLUDED.value",
                ("site_logo", body.site_logo),
            )
            updated["site_logo"] = body.site_logo

        if not updated:
            raise HTTPException(status_code=400, detail="No fields to update")
        return updated
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Update site config failed")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Name normalization (for fuzzy matching)
# ---------------------------------------------------------------------------

@router.post("/normalize-names")
async def normalize_names(user=Depends(_require_admin)):
    """Re-normalize all company names for fuzzy matching.

    Strips Belgian legal suffixes (NV, SA, BVBA, SRL, etc.), lowercases,
    and collapses whitespace into the name_normalized column.
    Useful after KBO data refreshes.
    """
    try:
        count = refresh_all_normalized_names()
        return {"status": "completed", "rows_updated": count}
    except Exception as e:
        logger.exception("Name normalization failed")
        raise HTTPException(status_code=500, detail=str(e))
