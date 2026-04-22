"""Admin backend for the bulk-enrichment orchestrator.

Endpoints:

  GET  /api/admin/enrichment/overview  — queue + spend summary
  GET  /api/admin/enrichment/dead      — recent failed / dead jobs
  POST /api/admin/enrichment/pause     — set meta.enrichment_enabled=false
  POST /api/admin/enrichment/resume    — set meta.enrichment_enabled=true
  POST /api/admin/enrichment/budget    — update daily USD budget
  POST /api/admin/enrichment/retry     — requeue failed / dead rows
  GET  /api/admin/enrichment/skiplist  — aggregator skip-list
  POST /api/admin/enrichment/skiplist  — add pattern
  DELETE /api/admin/enrichment/skiplist/{id} — remove pattern

Gated by a shared-secret password header (`X-Enrichment-Password`), not
Supabase admin role. Rationale: the operator couldn't reach the page
through the admin-role check on staging and asked for a simple password
instead. The password comes from env var `ENRICHMENT_ADMIN_PASSWORD`;
if the env var is unset the endpoints fail closed with 503.

NOTE: since staging shares the Postgres with prod, every mutation here
affects the prod worker's `meta` / `aggregator_skiplist` rows too.

Paired with the frontend at `frontend/src/app/admin/enrichment/page.tsx`
(which prompts for the password once and stashes it in localStorage).
"""

from __future__ import annotations

import hmac
import logging
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from db import execute, fetch_all, fetch_one
from enrichment_queue import (
    enrichment_enabled,
    recent_failures,
    set_meta_flag,
    stats as queue_stats,
)
from semantic_bootstrap import ensure_semantic_schema, get_semantic_readiness

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/enrichment", tags=["admin-enrichment"])


def _require_password(
    x_enrichment_password: str | None = Header(default=None),
) -> None:
    """Shared-secret gate for the enrichment admin endpoints.

    Constant-time compare against `ENRICHMENT_ADMIN_PASSWORD`. Missing
    env var = 503 (feature effectively disabled). Wrong password = 401.
    """
    expected = os.getenv("ENRICHMENT_ADMIN_PASSWORD", "")
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="enrichment_admin_password_not_configured",
        )
    got = (x_enrichment_password or "").strip()
    if not hmac.compare_digest(got, expected):
        raise HTTPException(status_code=401, detail="bad_password")


@router.get("/overview")
async def enrichment_overview(_: None = Depends(_require_password)):
    """One-stop panel for the admin UI: status + budget + counters."""
    ensure_semantic_schema()
    counts = queue_stats()
    enabled = enrichment_enabled()
    readiness = get_semantic_readiness()
    total_jobs = sum(int(v or 0) for v in counts.values())
    done_jobs = int(counts.get("done", 0) or 0)
    queued_jobs = int(counts.get("queued", 0) or 0)
    claimed_jobs = int(counts.get("claimed", 0) or 0)
    failed_jobs = int(counts.get("failed", 0) or 0)
    dead_jobs = int(counts.get("dead", 0) or 0)
    completed_jobs = done_jobs + dead_jobs
    completion_pct = (
        round((completed_jobs / total_jobs) * 100, 2)
        if total_jobs > 0
        else 0.0
    )

    row_spend = fetch_one(
        """
        SELECT COALESCE(SUM(cost_usd), 0)::float AS spend
          FROM llm_call_log
         WHERE endpoint LIKE '/bulk-enrichment/%%'
           AND ts >= CURRENT_DATE
        """
    )
    today_spend = float(row_spend["spend"] or 0.0) if row_spend else 0.0

    budget_row = fetch_one(
        "SELECT value FROM meta WHERE variable = 'enrichment_daily_budget'"
    )
    budget = float(budget_row["value"]) if budget_row and budget_row.get("value") else 10.0

    # Last 10 completed jobs
    recent_done = fetch_all(
        """
        SELECT enterprise_number, finished_at, priority
          FROM enrichment_job
         WHERE status = 'done'
      ORDER BY finished_at DESC NULLS LAST
         LIMIT 10
        """
    )

    # Rate in the last hour — done rows with finished_at in the last hour
    row_rate = fetch_one(
        """
        SELECT COUNT(*)::int AS n
          FROM enrichment_job
         WHERE status = 'done'
           AND finished_at >= NOW() - INTERVAL '1 hour'
        """
    )
    last_hour_done = int(row_rate["n"] or 0) if row_rate else 0

    row_last_day = fetch_one(
        """
        SELECT COUNT(*)::int AS n
          FROM enrichment_job
         WHERE status = 'done'
           AND finished_at >= NOW() - INTERVAL '24 hours'
        """
    )
    last_day_done = int(row_last_day["n"] or 0) if row_last_day else 0

    row_first_enqueued = fetch_one(
        "SELECT MIN(enqueued_at) AS ts FROM enrichment_job"
    )
    first_enqueued_at = (
        row_first_enqueued["ts"].isoformat()
        if row_first_enqueued and row_first_enqueued.get("ts")
        else None
    )

    confidence_rows = fetch_all(
        """
        SELECT
            COALESCE(NULLIF(bulk_confidence, ''), 'missing') AS confidence,
            COUNT(*)::int AS n
          FROM company_enrichment
         WHERE bulk_summary IS NOT NULL
      GROUP BY 1
      ORDER BY 1
        """
    )
    confidence_counts = {str(r["confidence"]): int(r["n"]) for r in confidence_rows}
    publishable_rows = int(readiness["counts"]["publishable_rows"] or 0)
    bulk_rows = int(readiness["counts"]["bulk_rows"] or 0)
    publishable_pct = (
        round((publishable_rows / bulk_rows) * 100, 2)
        if bulk_rows > 0
        else 0.0
    )

    row_recent = fetch_one(
        """
        SELECT
            COUNT(*) FILTER (
                WHERE status = 'done'
                  AND finished_at >= NOW() - INTERVAL '6 hours'
            )::int AS done_6h,
            COUNT(*) FILTER (
                WHERE status = 'done'
                  AND finished_at >= NOW() - INTERVAL '24 hours'
            )::int AS done_24h
          FROM enrichment_job
        """
    )
    done_6h = int(row_recent["done_6h"] or 0) if row_recent else 0
    done_24h = int(row_recent["done_24h"] or 0) if row_recent else 0
    eta_days: float | None = None
    eta_at: str | None = None
    if queued_jobs > 0 and done_24h > 0:
        eta_days = round(queued_jobs / done_24h, 2)
        eta_dt = datetime.now(timezone.utc) + timedelta(days=eta_days)
        eta_at = eta_dt.isoformat()

    throughput_window = []
    throughput_rows = fetch_all(
        """
        SELECT
            TO_CHAR(bucket, 'YYYY-MM-DD HH24:00') AS label,
            COALESCE(done_count, 0)::int AS done_count,
            COALESCE(avg_cost_usd, 0)::float AS avg_cost_usd
          FROM (
            SELECT generate_series(
              date_trunc('hour', NOW() - INTERVAL '23 hours'),
              date_trunc('hour', NOW()),
              INTERVAL '1 hour'
            ) AS bucket
          ) hours
          LEFT JOIN (
            SELECT
                date_trunc('hour', finished_at) AS bucket,
                COUNT(*) AS done_count
              FROM enrichment_job
             WHERE status = 'done'
               AND finished_at >= NOW() - INTERVAL '24 hours'
          GROUP BY 1
          ) job_stats ON job_stats.bucket = hours.bucket
          LEFT JOIN (
            SELECT
                date_trunc('hour', ts) AS bucket,
                AVG(cost_usd) AS avg_cost_usd
              FROM llm_call_log
             WHERE endpoint LIKE '/bulk-enrichment/%'
               AND ts >= NOW() - INTERVAL '24 hours'
          GROUP BY 1
          ) cost_stats ON cost_stats.bucket = hours.bucket
      ORDER BY hours.bucket
        """
    )
    for row in throughput_rows:
        throughput_window.append(
            {
                "label": row["label"],
                "done_count": int(row["done_count"] or 0),
                "avg_cost_usd": float(row["avg_cost_usd"] or 0.0),
            }
        )

    return {
        "enabled": enabled,
        "queue_counts": counts,
        "progress": {
            "total_jobs": total_jobs,
            "completed_jobs": completed_jobs,
            "done_jobs": done_jobs,
            "queued_jobs": queued_jobs,
            "claimed_jobs": claimed_jobs,
            "failed_jobs": failed_jobs,
            "dead_jobs": dead_jobs,
            "completion_pct": completion_pct,
            "first_enqueued_at": first_enqueued_at,
        },
        "quality": {
            "bulk_rows": bulk_rows,
            "publishable_rows": publishable_rows,
            "publishable_pct": publishable_pct,
            "confidence_counts": confidence_counts,
        },
        "throughput": {
            "last_hour_completed": last_hour_done,
            "last_6h_completed": done_6h,
            "last_24h_completed": done_24h,
            "last_day_completed": last_day_done,
            "eta_days": eta_days,
            "eta_at": eta_at,
            "hourly_window": throughput_window,
        },
        "today_spend_usd": today_spend,
        "daily_budget_usd": budget,
        "last_hour_completed": last_hour_done,
        "readiness": readiness,
        "recent_done": [
            {
                "enterprise_number": r["enterprise_number"],
                "finished_at": r["finished_at"].isoformat() if r.get("finished_at") else None,
                "priority": r.get("priority"),
            }
            for r in recent_done
        ],
    }


@router.get("/dead")
async def enrichment_dead(limit: int = 100, _: None = Depends(_require_password)):
    """Dead-letter list + recent failures for the admin page."""
    ensure_semantic_schema()
    limit = max(1, min(int(limit), 500))
    return {"items": recent_failures(limit=limit)}


class PauseBody(BaseModel):
    reason: str | None = None


@router.post("/pause")
async def pause_worker(body: PauseBody, _: None = Depends(_require_password)):
    ensure_semantic_schema()
    set_meta_flag("enrichment_enabled", "false")
    logger.info("enrichment paused, reason=%s", (body.reason or "")[:200])
    return {"enabled": False}


@router.post("/resume")
async def resume_worker(_: None = Depends(_require_password)):
    ensure_semantic_schema()
    set_meta_flag("enrichment_enabled", "true")
    logger.info("enrichment resumed")
    return {"enabled": True}


class BudgetBody(BaseModel):
    daily_budget_usd: float


@router.post("/budget")
async def set_budget(body: BudgetBody, _: None = Depends(_require_password)):
    ensure_semantic_schema()
    if body.daily_budget_usd < 0 or body.daily_budget_usd > 10_000:
        raise HTTPException(status_code=422, detail="out_of_range")
    set_meta_flag("enrichment_daily_budget", f"{body.daily_budget_usd:.2f}")
    logger.info("enrichment budget set to $%.2f", body.daily_budget_usd)
    return {"daily_budget_usd": body.daily_budget_usd}


class RetryBody(BaseModel):
    # Either a specific list of CBEs or 'all_failed' / 'all_dead'.
    enterprise_numbers: list[str] | None = None
    scope: str | None = None  # 'failed' | 'dead' | None


@router.post("/retry")
async def retry_jobs(body: RetryBody, _: None = Depends(_require_password)):
    ensure_semantic_schema()
    if body.enterprise_numbers:
        cbes = [c.strip().zfill(10) for c in body.enterprise_numbers if c]
        execute(
            """UPDATE enrichment_job
                  SET status = 'queued', attempts = 0, last_error = NULL,
                      claimed_at = NULL, finished_at = NULL
                WHERE enterprise_number = ANY(%s)""",
            (cbes,),
        )
        logger.info("retry %d CBEs", len(cbes))
        return {"requeued": len(cbes)}

    if body.scope == "failed":
        execute(
            """UPDATE enrichment_job
                  SET status = 'queued', attempts = 0, last_error = NULL
                WHERE status = 'failed'"""
        )
    elif body.scope == "dead":
        execute(
            """UPDATE enrichment_job
                  SET status = 'queued', attempts = 0, last_error = NULL,
                      finished_at = NULL
                WHERE status = 'dead'"""
        )
    else:
        raise HTTPException(status_code=422, detail="no_scope_or_list")

    return {"requeued_scope": body.scope}


@router.get("/skiplist")
async def list_skiplist(_: None = Depends(_require_password)):
    ensure_semantic_schema()
    rows = fetch_all(
        """SELECT id, pattern, kind, reason, added_at, added_by
             FROM aggregator_skiplist
         ORDER BY added_at DESC"""
    )
    return {"items": rows}


class SkiplistAdd(BaseModel):
    pattern: str
    kind: str = "domain"  # 'domain' | 'path'
    reason: str | None = None


@router.post("/skiplist")
async def add_skiplist(body: SkiplistAdd, _: None = Depends(_require_password)):
    ensure_semantic_schema()
    pattern = (body.pattern or "").strip().lower()
    if not pattern or len(pattern) > 120:
        raise HTTPException(status_code=422, detail="pattern_length")
    kind = body.kind.strip().lower()
    if kind not in ("domain", "path"):
        raise HTTPException(status_code=422, detail="kind_invalid")
    execute(
        """INSERT INTO aggregator_skiplist (pattern, kind, reason, added_by)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (pattern, kind) DO UPDATE SET
               reason = EXCLUDED.reason,
               added_at = NOW(),
               added_by = EXCLUDED.added_by""",
        (pattern, kind, (body.reason or "")[:200], "enrichment-admin"),
    )
    # Drop the scraper's in-process cache so the next discovery call
    # sees the new entry.
    try:
        from scraper import invalidate_skiplist_cache
        invalidate_skiplist_cache()
    except Exception:
        pass
    return {"ok": True}


@router.delete("/skiplist/{row_id}")
async def delete_skiplist(row_id: int, _: None = Depends(_require_password)):
    ensure_semantic_schema()
    execute("DELETE FROM aggregator_skiplist WHERE id = %s", (int(row_id),))
    try:
        from scraper import invalidate_skiplist_cache
        invalidate_skiplist_cache()
    except Exception:
        pass
    return {"ok": True}
