"""Disconnect watchdog for psycopg2-backed search requests."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from db import (
    QueryCancelContext,
    cancel_backend_for_request,
    reset_query_cancel_context,
    set_query_cancel_context,
)

logger = logging.getLogger("search_cancel_watchdog")

WATCHDOG_PATHS = frozenset(
    {
        "/api/companies/search",
        "/api/companies/semantic-search",
        "/api/people/search",
        "/api/search/suggest",
    }
)
POLL_INTERVAL_S = float(os.getenv("SEARCH_CANCEL_WATCHDOG_POLL_S", "0.05"))


def _env_flag_enabled(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def is_watchdog_candidate(method: str, path: str) -> bool:
    return method.upper() == "GET" and path in WATCHDOG_PATHS


class SearchCancelWatchdogMiddleware(BaseHTTPMiddleware):
    """Cancel abandoned read-only search queries at the database level.

    During the psycopg2 bridge period, sync FastAPI handlers run in a worker
    thread. Browser disconnects do not interrupt that thread, so a separate
    async watcher cancels the active Postgres query by PID. The cancel SQL is
    guarded by both PID and application_name request ownership.
    """

    async def dispatch(self, request: Request, call_next):
        if not _env_flag_enabled("SEARCH_CANCEL_WATCHDOG_ENABLED", True):
            return await call_next(request)
        if not is_watchdog_candidate(request.method, request.url.path):
            return await call_next(request)

        ctx = QueryCancelContext(request_id=uuid.uuid4().hex, path=request.url.path)
        token = set_query_cancel_context(ctx)
        stop = asyncio.Event()

        async def watch_disconnect() -> None:
            disconnected = False
            while not stop.is_set():
                try:
                    if disconnected or await request.is_disconnected():
                        disconnected = True
                        ctx.cancel_requested = True
                        pid, request_id = ctx.snapshot()
                        if pid and await asyncio.to_thread(
                            cancel_backend_for_request, pid, request_id
                        ):
                            return
                    await asyncio.wait_for(stop.wait(), timeout=POLL_INTERVAL_S)
                except asyncio.TimeoutError:
                    continue
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.debug("search cancel watchdog failed", exc_info=True)
                    return

        watcher = asyncio.create_task(watch_disconnect())
        try:
            return await call_next(request)
        finally:
            stop.set()
            reset_query_cancel_context(token)
            watcher.cancel()
            try:
                await watcher
            except asyncio.CancelledError:
                pass
