"""Docker healthcheck for the enrichment worker.

Returns 0 (healthy) when EITHER:
  - The worker is correctly idle (paused, daily budget blown, or queue empty), OR
  - The worker has finished at least one job in the freshness window.

Returns 1 (unhealthy) when the worker should be processing — meta flag is on,
budget has room, queue has work — but no job has been finished in the window.
That state means the worker is hung; the in-process watchdog will eventually
self-restart, and `docker compose ps` shows the bad state in the meantime.

The check uses a short DB statement_timeout so a stalled DB doesn't itself
hang the healthcheck. Any unexpected exception is reported as unhealthy.
"""

from __future__ import annotations

import os
import sys
import logging

import psycopg2

# Quiet logging so docker healthcheck output stays clean.
logging.basicConfig(level=logging.ERROR)

DATABASE_URL = os.getenv("DATABASE_URL", "")
FRESHNESS_S = int(os.getenv("ENRICHMENT_HEALTHCHECK_FRESHNESS_S", "900"))
CONNECT_TIMEOUT_S = int(os.getenv("ENRICHMENT_HEALTHCHECK_CONNECT_S", "5"))
STATEMENT_TIMEOUT_MS = int(os.getenv("ENRICHMENT_HEALTHCHECK_STATEMENT_MS", "5000"))


def _exit(healthy: bool, reason: str) -> None:
    code = 0 if healthy else 1
    label = "ok" if healthy else "FAIL"
    print(f"healthcheck:{label} {reason}", file=sys.stderr)
    sys.exit(code)


def main() -> None:
    if not DATABASE_URL:
        # Without DATABASE_URL we can't tell — assume healthy so we don't
        # restart-loop a misconfigured container into oblivion.
        _exit(True, "no_database_url")

    try:
        conn = psycopg2.connect(
            DATABASE_URL,
            connect_timeout=CONNECT_TIMEOUT_S,
            options=f"-c statement_timeout={STATEMENT_TIMEOUT_MS}",
        )
    except Exception as e:
        _exit(False, f"connect_failed:{type(e).__name__}")

    try:
        cur = conn.cursor()

        # Is the worker supposed to be running at all?
        cur.execute(
            "SELECT value FROM meta WHERE variable = 'enrichment_enabled' LIMIT 1"
        )
        row = cur.fetchone()
        enabled_raw = (row[0] if row else "true") or "true"
        enabled = enabled_raw.strip().lower() in ("true", "1", "yes", "on")
        if not enabled:
            _exit(True, "paused_by_meta_flag")

        # Is there work waiting? An empty queue is healthy idle, not hung.
        cur.execute(
            "SELECT 1 FROM enrichment_job WHERE status = 'queued' LIMIT 1"
        )
        if cur.fetchone() is None:
            _exit(True, "queue_empty")

        # Has anything terminated in the freshness window? `done`,
        # `excluded`, and `failed` all count as forward motion — a worker
        # that's failing every job is still proving its event loop is
        # responsive. We deliberately do NOT include `claimed` here since a
        # row can be `claimed` indefinitely on a hung worker.
        cur.execute(
            """
            SELECT 1
              FROM enrichment_job
             WHERE status IN ('done', 'excluded', 'failed')
               AND finished_at >= NOW() - make_interval(secs => %s)
             LIMIT 1
            """,
            (FRESHNESS_S,),
        )
        if cur.fetchone() is not None:
            _exit(True, f"fresh_within_{FRESHNESS_S}s")

        _exit(False, f"no_progress_in_{FRESHNESS_S}s")
    except SystemExit:
        raise
    except Exception as e:
        _exit(False, f"query_failed:{type(e).__name__}")
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
