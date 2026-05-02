"""Regression tests for the search disconnect watchdog."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db  # noqa: E402
from middleware import cancel_watchdog  # noqa: E402
from starlette.concurrency import run_in_threadpool  # noqa: E402


class _URL:
    def __init__(self, path):
        self.path = path


class _Request:
    def __init__(self, path="/api/companies/search"):
        self.method = "GET"
        self.url = _URL(path)
        self.disconnected = False

    async def is_disconnected(self):
        return self.disconnected


def test_is_watchdog_candidate_is_limited_to_search_gets():
    assert cancel_watchdog.is_watchdog_candidate("GET", "/api/companies/search")
    assert cancel_watchdog.is_watchdog_candidate("GET", "/api/search/suggest")
    assert not cancel_watchdog.is_watchdog_candidate("POST", "/api/companies/search")
    assert not cancel_watchdog.is_watchdog_candidate("GET", "/api/companies/0403170701")


def test_watchdog_cancels_captured_pid_on_disconnect(monkeypatch):
    calls = []

    def fake_cancel(pid, request_id):
        calls.append((pid, request_id))
        return True

    monkeypatch.setattr(cancel_watchdog, "cancel_backend_for_request", fake_cancel)
    middleware = cancel_watchdog.SearchCancelWatchdogMiddleware(app=lambda *_args: None)
    request = _Request()
    response = object()

    async def call_next(req):
        ctx = db.get_query_cancel_context()
        assert ctx is not None
        ctx.set_pid(777)
        req.disconnected = True
        await asyncio.sleep(cancel_watchdog.POLL_INTERVAL_S * 3)
        return response

    async def run():
        return await middleware.dispatch(request, call_next)

    assert asyncio.run(run()) is response
    assert len(calls) == 1
    assert calls[0][0] == 777
    assert calls[0][1]
    assert db.get_query_cancel_context() is None


def test_query_cancel_context_reaches_starlette_threadpool():
    ctx = db.QueryCancelContext("threadpool-rid", "/api/companies/search")

    async def run():
        token = db.set_query_cancel_context(ctx)
        try:
            return await run_in_threadpool(db.get_query_cancel_context)
        finally:
            db.reset_query_cancel_context(token)

    assert asyncio.run(run()) is ctx
    assert db.get_query_cancel_context() is None
