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

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from db import execute, fetch_all, fetch_one
from enrichment_queue import (
    enrichment_enabled,
    recent_failures,
    set_meta_flag,
    stats as queue_stats,
)

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
    counts = queue_stats()
    enabled = enrichment_enabled()

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

    return {
        "enabled": enabled,
        "queue_counts": counts,
        "today_spend_usd": today_spend,
        "daily_budget_usd": budget,
        "last_hour_completed": last_hour_done,
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
    limit = max(1, min(int(limit), 500))
    return {"items": recent_failures(limit=limit)}


class PauseBody(BaseModel):
    reason: str | None = None


@router.post("/pause")
async def pause_worker(body: PauseBody, _: None = Depends(_require_password)):
    set_meta_flag("enrichment_enabled", "false")
    logger.info("enrichment paused, reason=%s", (body.reason or "")[:200])
    return {"enabled": False}


@router.post("/resume")
async def resume_worker(_: None = Depends(_require_password)):
    set_meta_flag("enrichment_enabled", "true")
    logger.info("enrichment resumed")
    return {"enabled": True}


class BudgetBody(BaseModel):
    daily_budget_usd: float


@router.post("/budget")
async def set_budget(body: BudgetBody, _: None = Depends(_require_password)):
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
    execute("DELETE FROM aggregator_skiplist WHERE id = %s", (int(row_id),))
    try:
        from scraper import invalidate_skiplist_cache
        invalidate_skiplist_cache()
    except Exception:
        pass
    return {"ok": True}
