from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db import get_conn, put_conn
from .routers import bootstrap, email, graph, memory, notes, realtime, webhooks


app = FastAPI(title="NoteSnoop API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://notesnoop.app",
        "https://staging.notesnoop.app",
        "https://note.datasnoop.be",
        "http://localhost:3010",
        "http://127.0.0.1:3010",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "notesnoop-backend"}


def _configured(value: str, *bad_values: str) -> bool:
    clean = (value or "").strip()
    return bool(clean) and clean not in set(bad_values)


def _parse_db_timestamp(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _ops_checks(cur) -> dict[str, dict[str, object]]:
    checks: dict[str, dict[str, object]] = {}
    migrations_dir = Path(__file__).resolve().parents[1] / "notesnoop" / "migrations"
    migration_files = sorted(path.name for path in migrations_dir.glob("*.sql"))
    cur.execute("SELECT count(*) FROM public.schema_migrations")
    applied_count = int(cur.fetchone()[0])
    checks["migrations"] = {
        "ok": applied_count == len(migration_files),
        "beta_ok": applied_count == len(migration_files),
        "files": len(migration_files),
        "applied": applied_count,
        "pending": max(0, len(migration_files) - applied_count),
    }

    cur.execute("SELECT last_seen_at FROM ops_heartbeats WHERE key = 'notesnoop-worker'")
    row = cur.fetchone()
    last_seen = _parse_db_timestamp(row[0] if row else None)
    age_seconds = (datetime.now(timezone.utc) - last_seen).total_seconds() if last_seen else None
    worker_ok = bool(age_seconds is not None and age_seconds <= 180)
    checks["worker"] = {
        "ok": worker_ok,
        "beta_ok": worker_ok,
        "last_seen_at": last_seen.isoformat() if last_seen else None,
        "age_seconds": round(age_seconds, 1) if age_seconds is not None else None,
    }

    cur.execute("SELECT ops_ai_job_health()")
    job_health = cur.fetchone()[0] or {}
    stale_running = int(job_health.get("stale_running") or 0)
    checks["ai_jobs"] = {
        "ok": stale_running == 0,
        "beta_ok": stale_running == 0,
        **job_health,
    }
    return checks


@app.get("/api/readiness")
def readiness():
    settings = get_settings()
    checks: dict[str, dict[str, object]] = {}
    allow_unsigned = os.getenv("NOTESNOOP_WEBHOOK_ALLOW_UNSIGNED", "").lower() in {"1", "true", "yes"}
    postmark_inbound_configured = bool(os.getenv("NOTESNOOP_POSTMARK_BASIC_AUTH") or os.getenv("NOTESNOOP_POSTMARK_WEBHOOK_SECRET"))
    ollama_host = (os.getenv("OLLAMA_HOST") or os.getenv("OLLAMA_BASE_URL") or "https://ollama.com").rstrip("/")
    ollama_is_cloud = "ollama.com" in ollama_host
    ollama_configured = bool(os.getenv("OLLAMA_API_KEY", "")) or not ollama_is_cloud

    conn = None
    try:
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        checks["database"] = {"ok": True}
        with conn.cursor() as cur:
            checks.update(_ops_checks(cur))
    except Exception as exc:
        checks["database"] = {"ok": False, "detail": str(exc)[:160]}
    finally:
        if conn is not None:
            put_conn(conn)

    checks["auth"] = {
        "ok": bool(settings.dev_auth or settings.clerk_issuer),
        "beta_ok": bool(not settings.dev_auth and settings.clerk_issuer),
        "mode": "dev" if settings.dev_auth else "clerk",
    }
    checks["ollama"] = {
        "ok": ollama_configured,
        "beta_ok": ollama_configured,
        "mode": "cloud" if ollama_is_cloud else "local",
    }
    checks["inbound_webhook_auth"] = {
        "ok": bool(allow_unsigned or postmark_inbound_configured),
        "beta_ok": bool(not allow_unsigned and postmark_inbound_configured),
        "mode": "unsigned" if allow_unsigned else "configured",
    }
    checks["postmark_outbound"] = {
        "ok": bool(settings.postmark_dry_run or settings.postmark_server_token),
        "beta_ok": bool(not settings.postmark_dry_run and settings.postmark_server_token),
        "mode": "dry_run" if settings.postmark_dry_run else "live",
    }
    checks["email_ai_default"] = {
        "ok": settings.email_ai_default == "manual",
        "beta_ok": settings.email_ai_default == "manual",
        "value": settings.email_ai_default,
    }
    checks["database"].setdefault("beta_ok", checks["database"]["ok"])

    ready = all(bool(item["ok"]) for item in checks.values())
    beta_ready = all(bool(item.get("beta_ok")) for item in checks.values())
    return {"status": "ready" if ready else "blocked", "beta_status": "ready" if beta_ready else "blocked", "checks": checks}


app.include_router(bootstrap.router)
app.include_router(email.router)
app.include_router(graph.router)
app.include_router(memory.router)
app.include_router(notes.router)
app.include_router(realtime.router)
app.include_router(webhooks.router)
