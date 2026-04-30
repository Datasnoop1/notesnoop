"""Lightweight performance telemetry sink.

Receives client-side timing beacons from /search to diagnose where
the operator's perceived slowness is coming from (keystroke vs
network vs render). All events log to stdout with a stable prefix
(`PERF_LOG`) so we can grep them out of `docker logs`. No DB writes,
no auth, capped payload sizes.

Read with:
    docker compose -f docker-compose.staging.yml -p leadpeek-staging \
        logs backend-staging | grep PERF_LOG
"""

import json
import logging
from typing import Any

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api", tags=["perf"])
logger = logging.getLogger("perf_log")


_MAX_BODY_BYTES = 4096


@router.post("/_perf")
async def log_perf(request: Request) -> dict[str, str]:
    """Sink for navigator.sendBeacon payloads from /search.

    Body shape: `{session_id, event, ts_ms, q?, extra?}` JSON.
    Tolerant: malformed bodies still 200 so sendBeacon does not enter
    the browser's retry loop. Bodies larger than 4 KB are dropped
    before being parsed — typical payload is ~200 bytes; anything
    bigger is either misuse or abuse.
    """
    cl = request.headers.get("content-length")
    if cl is not None:
        try:
            if int(cl) > _MAX_BODY_BYTES:
                return {"ok": "0"}
        except ValueError:
            return {"ok": "0"}

    try:
        body: Any = await request.json()
    except Exception:
        body = {}

    if not isinstance(body, dict):
        body = {}

    payload = {
        "session_id": str(body.get("session_id", ""))[:64],
        "event": str(body.get("event", ""))[:32],
        "ts_ms": body.get("ts_ms"),
        "q": str(body.get("q", ""))[:120],
        "extra": body.get("extra"),
    }
    logger.info("PERF_LOG %s", json.dumps(payload, separators=(",", ":")))
    return {"ok": "1"}
