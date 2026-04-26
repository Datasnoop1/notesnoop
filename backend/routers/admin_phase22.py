"""Admin Phase-22 — fast shell + analytics + readiness routes.

This module adds the new admin endpoints introduced by the Phase-22 admin
rebuild. They live in a dedicated router so the legacy `admin.py` stays
untouched and revertable while the new admin UI is being validated.

Routes:

* ``GET /api/admin/shell``        — minimal first-paint payload
                                    (admin email + 5 KPI counts).
* ``GET /api/admin/analytics``    — consolidated traction + adoption +
                                    usage + sessions + retention metrics.
* ``GET /api/admin/readiness``    — unified NBB + semantic + Staatsblad
                                    pipeline status.
* ``GET /api/admin/sessions/breakdown`` — device / browser / country mix
                                    derived from the session middleware.
* ``GET /api/admin/sessions/paths`` — top user-flow path bigrams (the
                                    "users who landed on X next visited Y"
                                    breakdown).

Authentication: every route depends on ``_require_admin`` which is
imported from the legacy admin router so the role-cache stays warm.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from db import fetch_all, fetch_one
from routers.admin import _require_admin, _get_admin_emails

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin-phase22"])


# ---------------------------------------------------------------------------
# Tiny in-process TTL cache.
#
# Every analytics route here is admin-only and cheap to recompute, but the
# heavy /analytics call hits activity_log a handful of times. Caching at
# the route level lets the operator hammer Refresh without each click
# triggering 6 full-table aggregations. 30 s default, 60 s for readiness
# (which only changes on cron ticks anyway). Process-local — multi-worker
# admins should swap this for Redis if it ever becomes a bottleneck.
# ---------------------------------------------------------------------------

_CACHE: dict[str, tuple[float, Any]] = {}


def _cache_get(key: str, ttl: float):
    hit = _CACHE.get(key)
    if hit and (time.time() - hit[0]) < ttl:
        return hit[1]
    return None


def _cache_put(key: str, value):
    _CACHE[key] = (time.time(), value)
    if len(_CACHE) > 100:
        # Drop the oldest entry — admin caches are tiny, no LRU bookkeeping.
        oldest = min(_CACHE, key=lambda k: _CACHE[k][0])
        _CACHE.pop(oldest, None)
    return value


def _admin_filter_clause(prefix: str = "user_email") -> tuple[str, list[str]]:
    """Return a (sql_fragment, params) tuple that filters out admin traffic.

    Uses the cached admin-email list from the legacy router. Empty list
    yields a no-op clause so the SQL still parses.
    """
    admins = _get_admin_emails()
    if not admins:
        return ("TRUE", [])
    placeholders = ",".join(["%s"] * len(admins))
    return (f"{prefix} NOT IN ({placeholders})", list(admins))


# ---------------------------------------------------------------------------
# /shell — minimal first-paint payload
# ---------------------------------------------------------------------------

@router.get("/shell")
async def admin_shell(user=Depends(_require_admin)):
    """Return the bare-minimum payload the admin page needs to render its
    chrome (header, tabs, banner). Heavy KPIs come from /analytics.

    Designed to respond in <100 ms — every query here is a single-row
    aggregate against an indexed column.
    """
    cached = _cache_get("shell", 15.0)
    if cached:
        return cached

    try:
        row = fetch_one(
            """
            SELECT
                (SELECT COUNT(*) FROM user_roles) AS users_total,
                (SELECT COUNT(*) FROM feedback) AS feedback_total,
                (SELECT COUNT(*) FROM platform_invoice) AS invoices_total,
                (SELECT COUNT(*) FROM activity_log
                 WHERE created_at >= NOW() - INTERVAL '24 hours') AS reqs_24h,
                (SELECT COUNT(DISTINCT session_id) FROM activity_log
                 WHERE created_at >= NOW() - INTERVAL '24 hours'
                   AND session_id IS NOT NULL) AS sessions_24h
            """
        )
        payload = {
            "admin_email": (user or {}).get("email"),
            "users_total": int(row["users_total"] or 0),
            "feedback_total": int(row["feedback_total"] or 0),
            "invoices_total": int(row["invoices_total"] or 0),
            "reqs_24h": int(row["reqs_24h"] or 0),
            "sessions_24h": int(row["sessions_24h"] or 0),
            "ts": int(time.time()),
        }
        return _cache_put("shell", payload)
    except Exception as e:
        logger.exception("admin_shell failed")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# /analytics — consolidated traction + adoption + usage + sessions + retention
# ---------------------------------------------------------------------------

@router.get("/analytics")
async def admin_analytics(user=Depends(_require_admin)):
    """Single round-trip replacing /traction + /adoption + /usage + new
    session metrics. Cached 60 s — the data is at most one minute stale,
    which is acceptable for analytics dashboards.

    All windows are computed against ``activity_log`` with admin traffic
    excluded. Session-derived metrics (duration, pages/session, bounce)
    silently fall back to NULL on rows that pre-date the session-id
    middleware deploy.
    """
    cached = _cache_get("analytics", 60.0)
    if cached:
        return cached

    try:
        # Build the admin-exclusion clause once and reuse with named %s
        # parameters. psycopg supports a flat tuple per query so we pass
        # the params list per fetch.
        admin_clause, admin_params = _admin_filter_clause("user_email")

        # ---- KPIs (1 query) ---------------------------------------------
        kpi = fetch_one(
            f"""
            WITH base AS (
                SELECT user_email, session_id, created_at, endpoint, ua_family,
                       device_type, country_code
                FROM activity_log
                WHERE created_at >= NOW() - INTERVAL '60 days'
                  AND {admin_clause}
            )
            SELECT
                -- Visitors: unique session ids + unique anon-IP-hashes (legacy)
                COUNT(DISTINCT user_email) FILTER (
                    WHERE created_at >= NOW() - INTERVAL '24 hours'
                ) AS visitors_1d,
                COUNT(DISTINCT user_email) FILTER (
                    WHERE created_at >= NOW() - INTERVAL '7 days'
                ) AS visitors_7d,
                COUNT(DISTINCT user_email) FILTER (
                    WHERE created_at >= NOW() - INTERVAL '30 days'
                ) AS visitors_30d,
                -- Sessions
                COUNT(DISTINCT session_id) FILTER (
                    WHERE session_id IS NOT NULL
                      AND created_at >= NOW() - INTERVAL '24 hours'
                ) AS sessions_1d,
                COUNT(DISTINCT session_id) FILTER (
                    WHERE session_id IS NOT NULL
                      AND created_at >= NOW() - INTERVAL '7 days'
                ) AS sessions_7d,
                COUNT(DISTINCT session_id) FILTER (
                    WHERE session_id IS NOT NULL
                      AND created_at >= NOW() - INTERVAL '30 days'
                ) AS sessions_30d,
                -- Registered (anything not anon:*)
                COUNT(DISTINCT user_email) FILTER (
                    WHERE user_email NOT LIKE 'anon:%%'
                      AND created_at >= NOW() - INTERVAL '24 hours'
                ) AS registered_1d,
                COUNT(DISTINCT user_email) FILTER (
                    WHERE user_email NOT LIKE 'anon:%%'
                      AND created_at >= NOW() - INTERVAL '7 days'
                ) AS registered_7d,
                COUNT(DISTINCT user_email) FILTER (
                    WHERE user_email NOT LIKE 'anon:%%'
                      AND created_at >= NOW() - INTERVAL '30 days'
                ) AS registered_30d,
                -- Total request volume
                COUNT(*) FILTER (
                    WHERE created_at >= NOW() - INTERVAL '24 hours'
                ) AS reqs_1d,
                COUNT(*) FILTER (
                    WHERE created_at >= NOW() - INTERVAL '7 days'
                ) AS reqs_7d,
                COUNT(*) FILTER (
                    WHERE created_at >= NOW() - INTERVAL '30 days'
                ) AS reqs_30d
            FROM base
            """,
            tuple(admin_params),
        )

        # ---- Daily trend 30d (1 query) ----------------------------------
        daily = fetch_all(
            f"""
            SELECT
                date_trunc('day', created_at)::date AS day,
                COUNT(DISTINCT user_email) AS visitors,
                COUNT(DISTINCT user_email) FILTER (WHERE user_email NOT LIKE 'anon:%%') AS registered,
                COUNT(DISTINCT session_id) FILTER (WHERE session_id IS NOT NULL) AS sessions,
                COUNT(*) AS reqs
            FROM activity_log
            WHERE created_at >= NOW() - INTERVAL '30 days'
              AND {admin_clause}
            GROUP BY 1
            ORDER BY 1
            """,
            tuple(admin_params),
        )

        # ---- Hourly distribution last 7d (1 query, Europe/Brussels TZ) ---
        hourly = fetch_all(
            f"""
            SELECT
                EXTRACT(HOUR FROM created_at AT TIME ZONE 'Europe/Brussels')::int AS hour,
                EXTRACT(DOW  FROM created_at AT TIME ZONE 'Europe/Brussels')::int AS dow,
                COUNT(*) AS reqs
            FROM activity_log
            WHERE created_at >= NOW() - INTERVAL '7 days'
              AND {admin_clause}
            GROUP BY 1, 2
            ORDER BY 1, 2
            """,
            tuple(admin_params),
        )

        # ---- Top pages last 7d (1 query) --------------------------------
        top_pages = fetch_all(
            f"""
            SELECT endpoint, COUNT(*) AS hits,
                   COUNT(DISTINCT user_email) AS visitors
            FROM activity_log
            WHERE created_at >= NOW() - INTERVAL '7 days'
              AND endpoint NOT LIKE '/api/health%%'
              AND endpoint NOT LIKE '/api/dashboard%%'
              AND {admin_clause}
            GROUP BY endpoint
            ORDER BY hits DESC
            LIMIT 20
            """,
            tuple(admin_params),
        )

        # ---- Sessions: duration / pages-per-session / bounce (1 query) --
        # We derive a "session" as a contiguous run of activity for a
        # given session_id. Duration = last - first event in the cookie
        # window; bounce = sessions with exactly 1 request. Sessions older
        # than 7 days are discarded.
        sess = fetch_one(
            f"""
            WITH s AS (
                SELECT session_id,
                       MIN(created_at) AS started_at,
                       MAX(created_at) AS ended_at,
                       COUNT(*)        AS reqs
                FROM activity_log
                WHERE created_at >= NOW() - INTERVAL '7 days'
                  AND session_id IS NOT NULL
                  AND {admin_clause}
                GROUP BY session_id
            )
            SELECT
                COUNT(*) AS sessions,
                AVG(EXTRACT(EPOCH FROM (ended_at - started_at)))::int AS avg_duration_s,
                AVG(reqs)::numeric(10,2) AS pages_per_session,
                COUNT(*) FILTER (WHERE reqs <= 1) AS bounces,
                ROUND(100.0 * COUNT(*) FILTER (WHERE reqs <= 1) /
                      NULLIF(COUNT(*), 0), 1) AS bounce_rate_pct
            FROM s
            """,
            tuple(admin_params),
        )

        # ---- Retention cohorts (weekly, last 8 weeks, 1 query) ----------
        # Cohort = first-seen week. Week N retention = % of cohort that
        # came back N weeks later. Bucketed by ISO week.
        cohorts = fetch_all(
            f"""
            WITH first_seen AS (
                SELECT user_email,
                       date_trunc('week', MIN(created_at))::date AS cohort
                FROM activity_log
                WHERE user_email NOT LIKE 'anon:%%'
                  AND created_at >= NOW() - INTERVAL '90 days'
                  AND {admin_clause}
                GROUP BY user_email
            ),
            visits AS (
                SELECT al.user_email,
                       date_trunc('week', al.created_at)::date AS week
                FROM activity_log al
                WHERE al.user_email NOT LIKE 'anon:%%'
                  AND al.created_at >= NOW() - INTERVAL '90 days'
                  AND {admin_clause}
                GROUP BY al.user_email, week
            )
            SELECT
                fs.cohort                                  AS cohort,
                ((v.week - fs.cohort)/7)::int              AS weeks_since,
                COUNT(DISTINCT fs.user_email)              AS users
            FROM first_seen fs
            JOIN visits v ON v.user_email = fs.user_email
            WHERE fs.cohort >= NOW() - INTERVAL '56 days'
            GROUP BY 1, 2
            ORDER BY 1, 2
            """,
            tuple(admin_params + admin_params),
        )

        # ---- Signups last 30d (1 query) ---------------------------------
        # New email-based users = first time we see that user_email in
        # activity_log. Bucket by day.
        signups = fetch_all(
            f"""
            SELECT date_trunc('day', first_seen)::date AS day, COUNT(*) AS signups
            FROM (
                SELECT user_email, MIN(created_at) AS first_seen
                FROM activity_log
                WHERE user_email NOT LIKE 'anon:%%'
                  AND {admin_clause}
                GROUP BY user_email
            ) f
            WHERE first_seen >= NOW() - INTERVAL '30 days'
            GROUP BY 1
            ORDER BY 1
            """,
            tuple(admin_params),
        )

        # ---- Top registered + top guests last 7d (2 queries) ------------
        top_registered = fetch_all(
            """
            SELECT user_email, COUNT(*) AS reqs,
                   COUNT(DISTINCT endpoint) AS pages,
                   MAX(created_at) AS last_seen
            FROM activity_log
            WHERE user_email NOT LIKE 'anon:%%'
              AND created_at >= NOW() - INTERVAL '7 days'
            GROUP BY user_email
            ORDER BY reqs DESC
            LIMIT 15
            """,
        )
        top_guests = fetch_all(
            """
            SELECT user_email AS anon_id, COUNT(*) AS reqs,
                   COUNT(DISTINCT endpoint) AS pages,
                   MAX(created_at) AS last_seen
            FROM activity_log
            WHERE user_email LIKE 'anon:%%'
              AND created_at >= NOW() - INTERVAL '7 days'
            GROUP BY user_email
            ORDER BY reqs DESC
            LIMIT 15
            """,
        )

        # ---- Dormant accounts (registered users with NO activity 30d) ---
        dormant = fetch_all(
            """
            SELECT u.email,
                   u.created_at,
                   (SELECT MAX(created_at) FROM activity_log
                    WHERE user_email = u.email) AS last_active
            FROM user_roles u
            WHERE u.role IN ('user', 'pro')
              AND NOT EXISTS (
                  SELECT 1 FROM activity_log
                  WHERE user_email = u.email
                    AND created_at >= NOW() - INTERVAL '30 days'
              )
            ORDER BY u.created_at DESC
            LIMIT 25
            """,
        )

        # ---- Failed actions (5xx) last 24h (1 query) --------------------
        # We don't currently store status codes in activity_log, so this
        # is a placeholder until activity_log gains a status_code column
        # (tech-debt). Returning [] keeps the contract stable for the UI.
        failures: list = []

        payload = {
            "kpi": kpi,
            "daily": daily,
            "hourly": hourly,
            "top_pages": top_pages,
            "session": sess,
            "cohorts": cohorts,
            "signups": signups,
            "top_registered": top_registered,
            "top_guests": top_guests,
            "dormant": dormant,
            "failures": failures,
        }
        return _cache_put("analytics", payload)
    except Exception as e:
        logger.exception("admin_analytics failed")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# /sessions/breakdown — devices, browsers, countries
# ---------------------------------------------------------------------------

@router.get("/sessions/breakdown")
async def admin_sessions_breakdown(user=Depends(_require_admin)):
    """Coarse buckets — device family / browser family / country.

    Cached 60 s. UA family is bucketed at insert time so this is just a
    GROUP BY on indexed columns.
    """
    cached = _cache_get("sessions_breakdown", 60.0)
    if cached:
        return cached

    try:
        admin_clause, admin_params = _admin_filter_clause("user_email")

        device = fetch_all(
            f"""
            SELECT COALESCE(device_type, 'unknown') AS device,
                   COUNT(DISTINCT session_id) AS sessions,
                   COUNT(*) AS reqs
            FROM activity_log
            WHERE created_at >= NOW() - INTERVAL '7 days'
              AND session_id IS NOT NULL
              AND {admin_clause}
            GROUP BY device
            ORDER BY sessions DESC
            """,
            tuple(admin_params),
        )
        browser = fetch_all(
            f"""
            SELECT COALESCE(ua_family, 'unknown') AS browser,
                   COUNT(DISTINCT session_id) AS sessions,
                   COUNT(*) AS reqs
            FROM activity_log
            WHERE created_at >= NOW() - INTERVAL '7 days'
              AND session_id IS NOT NULL
              AND {admin_clause}
            GROUP BY browser
            ORDER BY sessions DESC
            """,
            tuple(admin_params),
        )
        country = fetch_all(
            f"""
            SELECT COALESCE(country_code, 'XX') AS country,
                   COUNT(DISTINCT session_id) AS sessions,
                   COUNT(*) AS reqs
            FROM activity_log
            WHERE created_at >= NOW() - INTERVAL '7 days'
              AND session_id IS NOT NULL
              AND {admin_clause}
            GROUP BY country
            ORDER BY sessions DESC
            LIMIT 25
            """,
            tuple(admin_params),
        )
        payload = {"device": device, "browser": browser, "country": country}
        return _cache_put("sessions_breakdown", payload)
    except Exception as e:
        logger.exception("admin_sessions_breakdown failed")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# /sessions/paths — top user-flow bigrams
# ---------------------------------------------------------------------------

@router.get("/sessions/paths")
async def admin_sessions_paths(user=Depends(_require_admin)):
    """Compute the top "page → next page" transitions across sessions of
    the last 7 days.

    Naive but cheap: pulls all (session_id, endpoint, created_at) rows
    from the last 7 days, sorts in SQL, and uses ``LAG`` to attach the
    previous endpoint. Then we GROUP BY (prev, next). With session_id
    indexed and an admin filter, this is comfortably under 1 s on tens
    of thousands of rows.
    """
    cached = _cache_get("sessions_paths", 60.0)
    if cached:
        return cached

    try:
        admin_clause, admin_params = _admin_filter_clause("user_email")
        rows = fetch_all(
            f"""
            WITH ev AS (
                SELECT session_id,
                       endpoint,
                       LAG(endpoint) OVER (
                           PARTITION BY session_id ORDER BY created_at
                       ) AS prev_endpoint
                FROM activity_log
                WHERE created_at >= NOW() - INTERVAL '7 days'
                  AND session_id IS NOT NULL
                  AND {admin_clause}
            )
            SELECT prev_endpoint AS prev, endpoint AS next, COUNT(*) AS n
            FROM ev
            WHERE prev_endpoint IS NOT NULL
              AND prev_endpoint <> endpoint
            GROUP BY prev_endpoint, endpoint
            ORDER BY n DESC
            LIMIT 30
            """,
            tuple(admin_params),
        )
        return _cache_put("sessions_paths", {"transitions": rows})
    except Exception as e:
        logger.exception("admin_sessions_paths failed")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# /readiness — unified pipeline health (NBB + semantic + Staatsblad)
# ---------------------------------------------------------------------------

def _readiness_status(*, latest_event_age_h: float | None,
                      error_count_24h: int,
                      progress_stalled: bool) -> str:
    """Decide healthy / warning / broken from a small set of signals.

    Rules (deliberately conservative — operator-facing):
      * broken  if no successful event in the last 36 h (any pipeline)
      * warning if no event in the last 12 h, OR errors > 25 in 24 h,
                OR progress is flat
      * healthy otherwise
    """
    if latest_event_age_h is None or latest_event_age_h > 36:
        return "broken"
    if latest_event_age_h > 12 or error_count_24h > 25 or progress_stalled:
        return "warning"
    return "healthy"


@router.get("/readiness")
async def admin_readiness(user=Depends(_require_admin)):
    """Single endpoint summarising the three production data pipelines.

    Each block carries:
        status        : "healthy" | "warning" | "broken"
        last_run_at   : timestamp of the most recent successful action
        completed     : count of records meaningfully processed
        remaining     : count of records still to process (where known)
        progress_pct  : 0-100, rounded
        errors_24h    : recent failures
        recent_failures : up to 5 example error strings
        freshness_h   : hours since most recent successful event
        notes         : human-readable extra context
        details_url   : pointer to a deeper dashboard
    """
    cached = _cache_get("readiness", 60.0)
    if cached:
        return cached

    out: dict[str, Any] = {}

    # ---- NBB pipeline -------------------------------------------------------
    try:
        nbb_row = fetch_one(
            """
            SELECT
                (SELECT COUNT(*) FROM financial_latest) AS loaded_companies,
                (SELECT MAX(loaded_at) FROM nbb_load_log) AS latest_load_at,
                (SELECT COUNT(*) FROM nbb_load_log
                 WHERE loaded_at >= NOW() - INTERVAL '24 hours'
                   AND COALESCE(deposit_key,'') NOT LIKE 'NO_FILINGS%%') AS loads_24h,
                (SELECT COUNT(*) FROM nbb_load_log
                 WHERE loaded_at >= NOW() - INTERVAL '7 days'
                   AND COALESCE(deposit_key,'') NOT LIKE 'NO_FILINGS%%') AS loads_7d,
                (SELECT COUNT(DISTINCT enterprise_number) FROM enterprise
                 WHERE status = 'AC' AND type_of_enterprise = '2') AS target_universe,
                (SELECT COUNT(*) FROM nbb_load_log
                 WHERE deposit_key LIKE 'NO_FILINGS%%') AS no_filings,
                (SELECT MAX(error) FROM nbb_load_log
                 WHERE error IS NOT NULL
                   AND loaded_at >= NOW() - INTERVAL '24 hours') AS recent_error
            """
        )
    except Exception:
        # Older nbb_load_log schemas may be missing the `error` column;
        # treat the lookup as best-effort.
        logger.exception("nbb readiness query failed; falling back")
        nbb_row = {
            "loaded_companies": 0,
            "latest_load_at": None,
            "loads_24h": 0,
            "loads_7d": 0,
            "target_universe": 0,
            "no_filings": 0,
            "recent_error": None,
        }

    target = int(nbb_row.get("target_universe") or 0)
    loaded = int(nbb_row.get("loaded_companies") or 0)
    progress_pct = round(100 * loaded / target, 1) if target else None
    latest = nbb_row.get("latest_load_at")
    age_h: float | None = None
    if latest is not None:
        age_h = max(0.0, (time.time() - latest.timestamp()) / 3600.0)
    errors_24h = 1 if nbb_row.get("recent_error") else 0
    out["nbb"] = {
        "name": "NBB Backload",
        "status": _readiness_status(
            latest_event_age_h=age_h,
            error_count_24h=errors_24h,
            progress_stalled=(int(nbb_row.get("loads_24h") or 0) < 100),
        ),
        "last_run_at": latest.isoformat() if latest else None,
        "completed": loaded,
        "remaining": max(0, target - loaded) if target else None,
        "progress_pct": progress_pct,
        "errors_24h": errors_24h,
        "recent_failures": [str(nbb_row["recent_error"])] if nbb_row.get("recent_error") else [],
        "freshness_h": round(age_h, 1) if age_h is not None else None,
        "throughput_24h": int(nbb_row.get("loads_24h") or 0),
        "throughput_7d": int(nbb_row.get("loads_7d") or 0),
        "notes": (
            "Tier-1 active legal-person enterprises only. "
            "FY2022+ JSON-XBRL filings; pre-2022 are PDF-only and skipped."
        ),
        "details_url": "/admin?tab=nbb",
    }

    # ---- Semantic pipeline --------------------------------------------------
    try:
        sem = fetch_one(
            """
            SELECT
                (SELECT COUNT(*) FROM enrichment_job WHERE status = 'queued')   AS queued,
                (SELECT COUNT(*) FROM enrichment_job WHERE status = 'claimed')  AS claimed,
                (SELECT COUNT(*) FROM enrichment_job WHERE status = 'done')     AS done,
                (SELECT COUNT(*) FROM enrichment_job WHERE status = 'failed')   AS failed,
                (SELECT COUNT(*) FROM enrichment_job WHERE status = 'dead')     AS dead,
                (SELECT COUNT(*) FROM enrichment_job WHERE status = 'excluded') AS excluded,
                (SELECT COUNT(*) FROM enrichment_job
                 WHERE status = 'done'
                   AND finished_at >= NOW() - INTERVAL '24 hours') AS done_24h,
                (SELECT MAX(finished_at) FROM enrichment_job WHERE status = 'done') AS last_done,
                (SELECT COUNT(*) FROM enrichment_job
                 WHERE status IN ('failed','dead')
                   AND finished_at >= NOW() - INTERVAL '24 hours') AS failures_24h,
                (SELECT value FROM meta WHERE variable = 'enrichment_enabled') AS enabled,
                (SELECT value FROM meta WHERE variable = 'enrichment_daily_budget') AS budget_usd,
                (SELECT COALESCE(SUM(cost_usd),0) FROM llm_call_log
                 WHERE endpoint LIKE '/bulk-enrichment/%%'
                   AND ts >= date_trunc('day', NOW())) AS spend_today_usd
            """
        )
        sem_recent_failures = fetch_all(
            """
            SELECT enterprise_number, error, finished_at
            FROM enrichment_job
            WHERE status IN ('failed','dead')
              AND finished_at >= NOW() - INTERVAL '24 hours'
            ORDER BY finished_at DESC
            LIMIT 5
            """
        )
    except Exception:
        logger.exception("semantic readiness query failed; falling back")
        sem = {
            "queued": 0, "claimed": 0, "done": 0, "failed": 0,
            "dead": 0, "excluded": 0, "done_24h": 0,
            "last_done": None, "failures_24h": 0,
            "enabled": "false", "budget_usd": "0", "spend_today_usd": 0,
        }
        sem_recent_failures = []

    sem_target = int(sem.get("queued", 0)) + int(sem.get("claimed", 0)) + int(sem.get("done", 0))
    sem_done = int(sem.get("done", 0))
    sem_progress = round(100 * sem_done / sem_target, 1) if sem_target else None
    sem_last = sem.get("last_done")
    sem_age_h: float | None = None
    if sem_last is not None:
        sem_age_h = max(0.0, (time.time() - sem_last.timestamp()) / 3600.0)
    paused = (str(sem.get("enabled")).lower() != "true")
    sem_status = _readiness_status(
        latest_event_age_h=sem_age_h,
        error_count_24h=int(sem.get("failures_24h") or 0),
        progress_stalled=(int(sem.get("done_24h") or 0) < 50 and not paused),
    )
    if paused:
        sem_status = "warning"
    out["semantic"] = {
        "name": "Semantic Enrichment",
        "status": sem_status,
        "last_run_at": sem_last.isoformat() if sem_last else None,
        "completed": sem_done,
        "remaining": int(sem.get("queued", 0)) + int(sem.get("claimed", 0)),
        "excluded": int(sem.get("excluded", 0)),
        "progress_pct": sem_progress,
        "errors_24h": int(sem.get("failures_24h") or 0),
        "recent_failures": [
            f"{r['enterprise_number']}: {(r['error'] or '')[:160]}"
            for r in sem_recent_failures
        ],
        "freshness_h": round(sem_age_h, 1) if sem_age_h is not None else None,
        "throughput_24h": int(sem.get("done_24h") or 0),
        "paused": paused,
        "budget_usd": float(sem.get("budget_usd") or 0),
        "spend_today_usd": float(sem.get("spend_today_usd") or 0),
        "notes": "Q2 (GPT-4o-mini) + KBO context, Haiku 4.5 escalation.",
        "details_url": "/admin/enrichment",
    }

    # ---- Staatsblad pipeline ------------------------------------------------
    try:
        st = fetch_one(
            """
            SELECT
                (SELECT COUNT(*) FROM staatsblad_publication
                 WHERE reference <> 'NO_DATA') AS pubs_total,
                (SELECT COUNT(*) FROM staatsblad_publication
                 WHERE loaded_at >= NOW() - INTERVAL '24 hours') AS pubs_24h,
                (SELECT COUNT(*) FROM staatsblad_publication
                 WHERE loaded_at >= NOW() - INTERVAL '7 days') AS pubs_7d,
                (SELECT COUNT(*) FROM staatsblad_event) AS events_total,
                (SELECT COUNT(*) FROM staatsblad_event
                 WHERE extracted_at >= NOW() - INTERVAL '24 hours') AS events_24h,
                (SELECT COUNT(*) FROM staatsblad_event
                 WHERE extracted_at >= NOW() - INTERVAL '7 days') AS events_7d,
                (SELECT MAX(extracted_at) FROM staatsblad_event) AS last_extraction,
                (SELECT MAX(loaded_at) FROM staatsblad_publication) AS last_pub_load,
                (SELECT MAX(pub_date) FROM staatsblad_publication) AS data_freshness_date
            """
        )
        st_queue = fetch_one(
            """
            SELECT
                COUNT(*) FILTER (WHERE status = 'pending')      AS pending,
                COUNT(*) FILTER (WHERE status = 'in_progress')  AS in_progress,
                COUNT(*) FILTER (WHERE status = 'done')         AS done,
                COUNT(*) FILTER (WHERE status = 'failed')       AS failed
            FROM staatsblad_bulk_queue
            """
        )
        st_recent_failures = fetch_all(
            """
            SELECT cbe, last_error
            FROM staatsblad_bulk_queue
            WHERE status = 'failed' AND last_error IS NOT NULL
            ORDER BY completed_at DESC
            LIMIT 5
            """
        )
    except Exception:
        logger.exception("staatsblad readiness query failed; falling back")
        st = {
            "pubs_total": 0, "pubs_24h": 0, "pubs_7d": 0,
            "events_total": 0, "events_24h": 0, "events_7d": 0,
            "last_extraction": None, "last_pub_load": None,
            "data_freshness_date": None,
        }
        st_queue = {"pending": 0, "in_progress": 0, "done": 0, "failed": 0}
        st_recent_failures = []

    st_age_h: float | None = None
    if st.get("last_extraction") is not None:
        st_age_h = max(0.0, (time.time() - st["last_extraction"].timestamp()) / 3600.0)
    st_target = int(st_queue.get("pending", 0)) + int(st_queue.get("in_progress", 0)) + int(st_queue.get("done", 0))
    st_progress = round(100 * int(st_queue.get("done", 0)) / st_target, 1) if st_target else None
    out["staatsblad"] = {
        "name": "Staatsblad Pipeline",
        "status": _readiness_status(
            latest_event_age_h=st_age_h,
            error_count_24h=int(st_queue.get("failed", 0)),
            progress_stalled=(int(st.get("events_24h") or 0) < 50),
        ),
        "last_run_at": (st["last_extraction"].isoformat()
                        if st.get("last_extraction") else None),
        "completed": int(st.get("events_total") or 0),
        "remaining": int(st_queue.get("pending", 0)) + int(st_queue.get("in_progress", 0)),
        "progress_pct": st_progress,
        "errors_24h": int(st_queue.get("failed", 0)),
        "recent_failures": [
            f"{r['cbe']}: {(r['last_error'] or '')[:160]}"
            for r in st_recent_failures
        ],
        "freshness_h": round(st_age_h, 1) if st_age_h is not None else None,
        "throughput_24h": int(st.get("events_24h") or 0),
        "throughput_7d": int(st.get("events_7d") or 0),
        "publications_total": int(st.get("pubs_total") or 0),
        "publications_24h": int(st.get("pubs_24h") or 0),
        "data_freshness_date": (st["data_freshness_date"].isoformat()
                                if st.get("data_freshness_date") else None),
        "queue": st_queue,
        "notes": (
            "Producer on RunPod (5y backfill via Anthropic batch), "
            "consumer cron every 2 days."
        ),
        "details_url": "/admin?tab=readiness#staatsblad",
    }

    # Roll-up summary chip for the dashboard header.
    summaries = [out[k]["status"] for k in ("nbb", "semantic", "staatsblad")]
    if "broken" in summaries:
        overall = "broken"
    elif "warning" in summaries:
        overall = "warning"
    else:
        overall = "healthy"
    out["overall"] = overall
    out["computed_at"] = int(time.time())

    return _cache_put("readiness", out)


# ---------------------------------------------------------------------------
# /pulse/cache-bust — operator escape hatch
# ---------------------------------------------------------------------------

@router.post("/pulse/cache-bust")
async def admin_pulse_cache_bust(user=Depends(_require_admin)):
    """Drop the in-process cache used by the routes above.

    The operator can use this to force-refresh after a deploy or after
    running a one-off backfill — saves waiting 60 s for the TTL to lapse.
    """
    n = len(_CACHE)
    _CACHE.clear()
    return {"dropped": n}
