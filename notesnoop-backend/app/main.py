from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db import get_conn, put_conn
from .routers import bootstrap, email, graph, notes, realtime, webhooks


app = FastAPI(title="NoteSnoop API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://notesnoop.app",
        "https://staging.notesnoop.app",
        "https://note.datasnoop.be",
        "http://localhost:3010",
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


@app.get("/api/readiness")
def readiness():
    settings = get_settings()
    checks: dict[str, dict[str, object]] = {}
    allow_unsigned = os.getenv("NOTESNOOP_WEBHOOK_ALLOW_UNSIGNED", "").lower() in {"1", "true", "yes"}
    postmark_inbound_configured = bool(os.getenv("NOTESNOOP_POSTMARK_BASIC_AUTH") or os.getenv("NOTESNOOP_POSTMARK_WEBHOOK_SECRET"))

    conn = None
    try:
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        checks["database"] = {"ok": True}
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
    checks["ollama"] = {"ok": _configured(os.getenv("OLLAMA_API_KEY", "")), "beta_ok": _configured(os.getenv("OLLAMA_API_KEY", ""))}
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
app.include_router(notes.router)
app.include_router(realtime.router)
app.include_router(webhooks.router)
