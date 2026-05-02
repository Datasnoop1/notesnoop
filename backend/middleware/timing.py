"""Request phase timing middleware and lightweight Prometheus exposition."""

from __future__ import annotations

import contextvars
import logging
import threading
import time
from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import PlainTextResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("phase_timing")


@dataclass
class PhaseTimingState:
    auth_ms: float = 0.0
    cache_ms: float = 0.0
    db_ms: float = 0.0
    serialize_ms: float = 0.0


_current_timing: contextvars.ContextVar[PhaseTimingState | None] = contextvars.ContextVar(
    "datasnoop_phase_timing",
    default=None,
)

_BUCKETS_MS = (1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000)
_PHASES = ("auth", "cache", "db", "serialize", "total")
_metrics_lock = threading.Lock()
_histograms = {
    phase: {
        "buckets": {bucket: 0 for bucket in _BUCKETS_MS},
        "inf": 0,
        "sum": 0.0,
        "count": 0,
    }
    for phase in _PHASES
}


def record_db_timing(duration_ms: float) -> None:
    state = _current_timing.get()
    if state is not None:
        state.db_ms += max(0.0, duration_ms)


def _observe(phase: str, value_ms: float) -> None:
    value = max(0.0, value_ms)
    with _metrics_lock:
        hist = _histograms[phase]
        for bucket in _BUCKETS_MS:
            if value <= bucket:
                hist["buckets"][bucket] += 1
        hist["inf"] += 1
        hist["sum"] += value
        hist["count"] += 1


def _format_server_timing(state: PhaseTimingState, total_ms: float) -> str:
    parts = (
        ("auth-ms", state.auth_ms),
        ("cache-ms", state.cache_ms),
        ("db-ms", state.db_ms),
        ("serialize-ms", state.serialize_ms),
        ("total-ms", total_ms),
    )
    return ", ".join(f"{name};dur={value:.1f}" for name, value in parts)


def _observe_request(state: PhaseTimingState, total_ms: float) -> None:
    _observe("auth", state.auth_ms)
    _observe("cache", state.cache_ms)
    _observe("db", state.db_ms)
    _observe("serialize", state.serialize_ms)
    _observe("total", total_ms)


class TimingMiddleware(BaseHTTPMiddleware):
    """Add Server-Timing headers and aggregate phase histograms for /metrics."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)

        state = PhaseTimingState()
        token = _current_timing.set(state)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            total_ms = (time.perf_counter() - start) * 1000.0
            _current_timing.reset(token)

        response.headers["Server-Timing"] = _format_server_timing(state, total_ms)
        _observe_request(state, total_ms)
        logger.info(
            "PHASE_TIMING path=%s status=%s total_ms=%.1f auth_ms=%.1f cache_ms=%.1f db_ms=%.1f serialize_ms=%.1f",
            path,
            getattr(response, "status_code", 0),
            total_ms,
            state.auth_ms,
            state.cache_ms,
            state.db_ms,
            state.serialize_ms,
        )
        return response


def metrics_response() -> PlainTextResponse:
    lines = [
        "# HELP datasnoop_request_phase_duration_ms Request phase duration in milliseconds.",
        "# TYPE datasnoop_request_phase_duration_ms histogram",
    ]
    with _metrics_lock:
        snapshot = {
            phase: {
                "buckets": dict(hist["buckets"]),
                "inf": hist["inf"],
                "sum": hist["sum"],
                "count": hist["count"],
            }
            for phase, hist in _histograms.items()
        }

    for phase, hist in snapshot.items():
        for bucket in _BUCKETS_MS:
            lines.append(
                f'datasnoop_request_phase_duration_ms_bucket{{phase="{phase}",le="{bucket}"}} '
                f'{hist["buckets"][bucket]}'
            )
        lines.append(
            f'datasnoop_request_phase_duration_ms_bucket{{phase="{phase}",le="+Inf"}} {hist["inf"]}'
        )
        lines.append(f'datasnoop_request_phase_duration_ms_sum{{phase="{phase}"}} {hist["sum"]:.3f}')
        lines.append(f'datasnoop_request_phase_duration_ms_count{{phase="{phase}"}} {hist["count"]}')

    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")
