#!/usr/bin/env python3
"""Bulk Staatsblad metadata scraper — drains `staatsblad_bulk_queue`.

Two transport modes (operator picks at runtime):

  --mode=webshare
      Rotates through Webshare datacenter proxies loaded from
      $WEBSHARE_PROXIES_FILE (default /root/webshare_proxies.txt,
      each line formatted `IP:PORT:USER:PASS`). 20 concurrent async
      workers via httpx. Intended for the one-off 100k-CBE backfill.

  --mode=slow
      No proxy, direct from the Hetzner IP, serial at 1 req/sec.
      Matches the existing daily scraper's cadence so it won't
      trip ejustice's per-IP rate limits. Use if Webshare is
      unavailable or credentials expire mid-run.

Resume-safe: the queue's `FOR UPDATE SKIP LOCKED` dequeue mirrors
backend/enrichment_queue.py. Rows in `in_progress` whose `locked_at`
is older than --stale-minutes minutes are swept back to `pending`
so crashed workers' claims don't block the queue forever.

Block / retry policy:
  200 + parseable HTML               -> mark done, record pubs_found
  200 + body < 200 bytes OR contains
    "rate limit" / "too many"        -> soft-block, requeue w/ backoff
  429 / 403 / 503                    -> requeue w/ backoff, rotate proxy
  other / timeout                    -> requeue w/ backoff
  attempts == 3                      -> mark failed, log last_error

Progress logging every 500 completions. If success rate drops below
95% over the last 1000 attempts, or the script crashes, send an SMTP
alert via the existing nightly_health_report.py env vars.

Usage examples:
  # Seed the queue from financial_latest ∖ staatsblad_publication
  python scripts/staatsblad_bulk_scrape.py --seed

  # Drain the queue with Webshare (recommended)
  python scripts/staatsblad_bulk_scrape.py --mode=webshare --workers=20

  # Drain slowly with no proxy
  python scripts/staatsblad_bulk_scrape.py --mode=slow

  # Run forever against an always-growing queue (for a future cron)
  python scripts/staatsblad_bulk_scrape.py --mode=webshare --daemon
"""
from __future__ import annotations

import argparse
import asyncio
import atexit
import logging
import os
import random
import re
import signal
import smtplib
import ssl
import sys
import time
from collections import deque
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

import httpx
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

# Make the project's src/ importable so we can reuse the parser.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "src"))
from staatsblad import _parse_item  # type: ignore  # noqa: E402

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
# Silence httpx's per-request INFO noise at high concurrency.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
log = logging.getLogger("bulk_scrape")

EJUSTICE_LIST_URL = "https://www.ejustice.just.fgov.be/cgi_tsv/list.pl"
USER_AGENT = "Datasnoop/1.0 (Company Intelligence; +https://datasnoop.be)"
DEFAULT_PROXY_FILE = "/root/webshare_proxies.txt"
MAX_PAGES = max(1, int(os.getenv("BULK_MAX_PAGES", "1")))

# Soft-block heuristics. An ejustice list page for a real CBE is
# consistently >20 KB; anything tiny after a 200 is a proxy interstitial
# or a rate-limit message.
SOFT_BLOCK_MIN_BYTES = 200
SOFT_BLOCK_MARKERS = [
    "rate limit",
    "too many requests",
    "cloudflare",
    "please try again",
]


# ---------------------------------------------------------------------------
# Queue helpers (mirror backend/enrichment_queue.py)
# ---------------------------------------------------------------------------

def _db() -> psycopg2.extensions.connection:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    conn = psycopg2.connect(url)
    conn.autocommit = False
    return conn


def seed_queue(conn) -> int:
    """Insert one row per NBB-filer CBE not yet in staatsblad_publication.

    Idempotent via `ON CONFLICT (cbe) DO NOTHING`, so re-running is safe
    and only adds newly-missing CBEs.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO staatsblad_bulk_queue (cbe, status)
            SELECT DISTINCT fl.enterprise_number, 'pending'
            FROM financial_latest fl
            WHERE fl.enterprise_number NOT IN (
                SELECT DISTINCT enterprise_number FROM staatsblad_publication
            )
            ON CONFLICT (cbe) DO NOTHING
            """
        )
        inserted = cur.rowcount
    conn.commit()
    return inserted


def release_stale(conn, older_than_minutes: int = 10) -> int:
    """Reset `in_progress` claims older than N minutes back to `pending`.

    Safety net for workers that crashed or lost network mid-scrape.
    Decrements `attempts` so a crash doesn't consume a retry budget —
    the CBE still had something to try.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE staatsblad_bulk_queue
               SET status = 'pending',
                   locked_at = NULL,
                   attempts = GREATEST(attempts - 1, 0)
             WHERE status = 'in_progress'
               AND locked_at < NOW() - make_interval(mins => %s)
            """,
            (older_than_minutes,),
        )
        n = cur.rowcount
    conn.commit()
    return n


def dequeue(conn) -> Optional[str]:
    """Claim the next pending CBE, or None if the queue is drained.

    Atomic via FOR UPDATE SKIP LOCKED — multiple workers can call this
    concurrently without grabbing the same row.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH next AS (
                SELECT cbe
                  FROM staatsblad_bulk_queue
                 WHERE status = 'pending'
                 ORDER BY enqueued_at
                 LIMIT 1
                 FOR UPDATE SKIP LOCKED
            )
            UPDATE staatsblad_bulk_queue q
               SET status = 'in_progress',
                   locked_at = NOW(),
                   attempts = q.attempts + 1
              FROM next
             WHERE q.cbe = next.cbe
             RETURNING q.cbe
            """
        )
        row = cur.fetchone()
    conn.commit()
    return row[0] if row else None


def queue_size(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status, COUNT(*) FROM staatsblad_bulk_queue GROUP BY status"
        )
        return {r[0]: r[1] for r in cur.fetchall()}


def mark_done(conn, cbe: str, pubs_found: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE staatsblad_bulk_queue
               SET status = 'done',
                   completed_at = NOW(),
                   pubs_found = %s,
                   last_error = NULL
             WHERE cbe = %s
            """,
            (pubs_found, cbe),
        )
    conn.commit()


# Strip embedded credentials from error messages before they hit Postgres
# (httpx exceptions can render the full proxy URL including user:pass).
_CRED_RE = re.compile(r"://[^@\s/]+@")


def _scrub(msg: str) -> str:
    return _CRED_RE.sub("://***@", msg) if msg else msg


def mark_retry(conn, cbe: str, reason: str, max_attempts: int = 3) -> str:
    """Return `cbe` to `pending` for another go, or give up at max_attempts.

    Returns the NEW status ('pending' or 'failed') so the caller can
    increment stats counters accurately.
    """
    scrubbed = _scrub(reason)[:500]
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE staatsblad_bulk_queue
               SET status = CASE
                      WHEN attempts >= %s THEN 'failed'
                      ELSE 'pending'
                   END,
                   locked_at = NULL,
                   last_error = %s
             WHERE cbe = %s
             RETURNING status
            """,
            (max_attempts, scrubbed, cbe),
        )
        row = cur.fetchone()
    conn.commit()
    return row[0] if row else "pending"


# ---------------------------------------------------------------------------
# Publication write-back (same shape as src/staatsblad.py::store_publications,
# but uses execute_batch for speed and runs against the prod Postgres).
# ---------------------------------------------------------------------------

def store_publications(conn, publications: list[dict]) -> int:
    """Insert publications with ON CONFLICT DO NOTHING. Returns rows affected."""
    if not publications:
        return 0
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(
            cur,
            """
            INSERT INTO staatsblad_publication
                (enterprise_number, pub_date, pub_type, reference, pdf_url, entity_name)
            VALUES (%(enterprise_number)s, %(pub_date)s, %(pub_type)s,
                    %(reference)s, %(pdf_url)s, %(entity_name)s)
            ON CONFLICT DO NOTHING
            """,
            publications,
            page_size=200,
        )
    conn.commit()
    return len(publications)


# ---------------------------------------------------------------------------
# Proxy pool
# ---------------------------------------------------------------------------

class ProxyPool:
    """Rotating pool of Webshare datacenter proxies.

    Loaded from a file where each line is `IP:PORT:USER:PASS`. Pick
    returns a random entry; on failure the caller drops it and picks
    again (the pool isn't reduced because Webshare's IPs are ephemeral
    anyway — a 503 on one call doesn't imply the IP is permanently bad).
    """

    def __init__(self, path: str):
        self.proxies: list[str] = []
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(
                f"proxy file not found: {path} (set WEBSHARE_PROXIES_FILE)"
            )
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(":")
            if len(parts) != 4:
                # Don't log the line content — if the file path is
                # mistyped (e.g. /etc/shadow) we don't want secrets in
                # the log.
                log.warning("skip malformed proxy line (wrong field count)")
                continue
            ip, port, user, password = parts
            # httpx proxy URL format. User/pass go in URL so no
            # separate auth config needed.
            self.proxies.append(f"http://{user}:{password}@{ip}:{port}")
        if not self.proxies:
            raise RuntimeError(f"no proxies loaded from {path}")
        log.info("loaded %d Webshare proxies from %s", len(self.proxies), path)

    def pick(self) -> str:
        return random.choice(self.proxies)


# ---------------------------------------------------------------------------
# Fetch one CBE's result pages. MAX_PAGES defaults to 1, but operators can
# widen the scrape window (for example BULK_MAX_PAGES=5 for ~3 years).
# ---------------------------------------------------------------------------

async def fetch_one_cbe(
    base_client: Optional[httpx.AsyncClient],
    cbe: str,
    proxy: Optional[str],
) -> tuple[str, Optional[list[dict]], Optional[str]]:
    """Returns (status, publications_or_None, error_or_None).

    When `proxy` is set we build a short-lived AsyncClient bound to that
    proxy URL — httpx ≥0.27 requires the `proxy` kwarg on the client
    constructor, not on individual requests. `base_client` is used only
    for `--mode=slow` (no proxy).

    Response body is streamed and capped at MAX_BODY_BYTES to defend
    against a hostile/misbehaving proxy pushing a giant payload.

    Status codes this function returns:
      'ok'          - 200 with parseable HTML; publications is the list
      'soft_block'  - 200 but body tiny / contains rate-limit marker
      'rate_limit'  - 429 / 403 / 503
      'transport'   - timeout, connection error, or oversize body
    """
    url = EJUSTICE_LIST_URL
    headers = {"User-Agent": USER_AGENT}
    timeout = httpx.Timeout(30.0)

    if proxy:
        # Per-call client so we can bind `proxy` at construction.
        client_cm = httpx.AsyncClient(
            proxy=proxy, timeout=timeout, http2=False,
        )
    else:
        assert base_client is not None
        client_cm = None  # we'll reuse base_client

    async def _fetch_page(
        client: httpx.AsyncClient, page: int,
    ) -> tuple[str, Optional[list[dict]], Optional[str]]:
        params = {"language": "nl", "btw": cbe, "page": page}
        try:
            status_code, body = await _do_stream(client, url, params, headers)
        except httpx.TimeoutException:
            return "transport", None, "timeout"
        except _OversizeBody as e:
            return "transport", None, f"oversize body: {e.args[0]} bytes"
        except (httpx.ConnectError, httpx.ReadError, httpx.ProxyError, httpx.HTTPError) as e:
            return "transport", None, _scrub(f"{type(e).__name__}: {e}")[:200]

        if status_code in (429, 403, 503):
            return "rate_limit", None, f"HTTP {status_code}"
        if status_code != 200:
            return "transport", None, f"HTTP {status_code}"

        if len(body) < SOFT_BLOCK_MIN_BYTES:
            return "soft_block", None, f"body {len(body)}B"
        lower = body.lower()
        if any(m in lower for m in SOFT_BLOCK_MARKERS):
            return "soft_block", None, "body matches rate-limit marker"

        items = body.split('<div class="list-item">')
        if len(items) <= 1:
            return "ok", [], None

        pubs = []
        for item in items[1:]:
            p = _parse_item(item, cbe)
            if p:
                pubs.append(p)
        return "ok", pubs, None

    seen_refs: set[str] = set()
    all_pubs: list[dict] = []

    if client_cm:
        async with client_cm as c:
            client = c
            for page in range(1, MAX_PAGES + 1):
                status, pubs, err = await _fetch_page(client, page)
                if status != "ok":
                    return status, None, err
                if not pubs:
                    break
                for pub in pubs:
                    ref = str(pub.get("reference") or "")
                    if ref and ref in seen_refs:
                        continue
                    if ref:
                        seen_refs.add(ref)
                    all_pubs.append(pub)
    else:
        assert base_client is not None
        for page in range(1, MAX_PAGES + 1):
            status, pubs, err = await _fetch_page(base_client, page)
            if status != "ok":
                return status, None, err
            if not pubs:
                break
            for pub in pubs:
                ref = str(pub.get("reference") or "")
                if ref and ref in seen_refs:
                    continue
                if ref:
                    seen_refs.add(ref)
                all_pubs.append(pub)

    return "ok", all_pubs, None


MAX_BODY_BYTES = 2 * 1024 * 1024  # 2 MB cap per response


class _OversizeBody(Exception):
    pass


async def _do_stream(client: httpx.AsyncClient, url: str, params: dict, headers: dict) -> tuple[int, str]:
    """GET with a hard body-size cap to defend against runaway responses."""
    async with client.stream("GET", url, params=params, headers=headers) as resp:
        # Reject too-large declared Content-Length up front.
        cl = resp.headers.get("content-length")
        if cl and int(cl) > MAX_BODY_BYTES:
            raise _OversizeBody(cl)
        chunks: list[bytes] = []
        total = 0
        async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
            total += len(chunk)
            if total > MAX_BODY_BYTES:
                raise _OversizeBody(total)
            chunks.append(chunk)
        body = b"".join(chunks).decode(resp.encoding or "utf-8", errors="replace")
        return resp.status_code, body


# ---------------------------------------------------------------------------
# Worker + orchestrator
# ---------------------------------------------------------------------------

class RateTracker:
    """Rolling window of the last N attempts' outcomes — used for the
    'success rate < 95% over last 1000' alert threshold."""

    def __init__(self, window: int = 1000):
        self.window = window
        self.outcomes: deque[bool] = deque(maxlen=window)

    def record(self, ok: bool) -> None:
        self.outcomes.append(ok)

    def success_rate(self) -> Optional[float]:
        if len(self.outcomes) < self.window:
            return None
        return sum(self.outcomes) / len(self.outcomes)


async def worker(
    worker_id: int,
    client: httpx.AsyncClient,
    proxy_pool: Optional[ProxyPool],
    sem: asyncio.Semaphore,
    backoff_base: float,
    stats: dict,
    rate_tracker: RateTracker,
    stop_flag: asyncio.Event,
) -> None:
    """Pull CBEs from the queue until it's empty or stop_flag is set.

    Each worker has its own DB connection (cheap on Postgres pooler).
    """
    conn = _db()
    try:
        while not stop_flag.is_set():
            async with sem:
                cbe = await asyncio.to_thread(dequeue, conn)
            if cbe is None:
                # Queue empty — stay alive briefly in case seeding is
                # still in-flight, then exit.
                await asyncio.sleep(2)
                remaining = await asyncio.to_thread(queue_size, conn)
                if remaining.get("pending", 0) == 0:
                    log.info("worker %d: queue drained", worker_id)
                    return
                continue

            proxy = proxy_pool.pick() if proxy_pool else None
            status, pubs, err = await fetch_one_cbe(client, cbe, proxy)

            if status == "ok":
                n = 0 if pubs is None else await asyncio.to_thread(
                    store_publications, conn, pubs
                )
                await asyncio.to_thread(mark_done, conn, cbe, len(pubs or []))
                stats["done"] += 1
                stats["pubs_written"] += n
                rate_tracker.record(True)
            else:
                # retry / fail path
                reason = f"{status}: {err or ''}"
                new_status = await asyncio.to_thread(mark_retry, conn, cbe, reason)
                if new_status == "failed":
                    stats["failed"] += 1
                else:
                    stats["retried"] += 1
                rate_tracker.record(False)
                # Per-worker jittered backoff. We DON'T sleep when the
                # queue is deep and most workers are succeeding — only
                # on this worker, after this failure.
                delay = backoff_base * (2 ** min(stats["retried"] % 4, 4)) + random.random()
                await asyncio.sleep(min(delay, 30))
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Progress + alerting
# ---------------------------------------------------------------------------

def _send_alert(subject: str, body: str) -> None:
    """Send an SMTP alert via the existing nightly_health_report.py env
    convention. No-ops (with a warning) if the env vars aren't set so a
    missing config doesn't crash the scraper."""
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    pwd = os.getenv("SMTP_PASS")
    sender = os.getenv("SMTP_FROM", "claude@datasnoop.be")
    to = os.getenv("SMTP_ALERT_TO") or sender
    if not (host and user and pwd and to):
        log.warning("SMTP env vars not set — skipping alert '%s'", subject)
        return
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = f"DataSnoop Watchdog <{sender}>"
    msg["To"] = to
    # Use the standard verifying TLS context — Stalwart on datasnoop.be
    # has a valid Let's Encrypt cert, and disabling verification would
    # expose SMTP AUTH credentials to any on-path MitM.
    ctx = ssl.create_default_context()
    try:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.ehlo("datasnoop-backend")
            s.starttls(context=ctx)
            s.ehlo("datasnoop-backend")
            s.login(user, pwd)
            s.sendmail(sender, [to], msg.as_string())
        log.info("alert sent: %s", subject)
    except Exception as e:  # noqa: BLE001 — we want to log anything
        log.error("alert send failed: %s", e)


async def progress_logger(
    stats: dict,
    rate_tracker: RateTracker,
    stop_flag: asyncio.Event,
    total: int,
    alert_state: dict,
) -> None:
    """Every 500 completions log a line; if success rate drops under
    95% over the last 1000 attempts and we haven't already alerted,
    fire a one-off email alert."""
    last_logged_done = 0
    started_at = time.time()
    while not stop_flag.is_set():
        await asyncio.sleep(5)
        done = stats["done"] + stats["failed"]
        elapsed = max(time.time() - started_at, 1.0)
        rate = done / elapsed
        remaining = max(total - done, 0)
        eta_min = remaining / max(rate, 0.01) / 60
        if done - last_logged_done >= 500 or done >= total:
            log.info(
                "%d/%d done | %d retried | %d failed | %d pubs written | %.1f CBEs/s | ETA %.1f min",
                stats["done"], total, stats["retried"], stats["failed"],
                stats["pubs_written"], rate, eta_min,
            )
            last_logged_done = done

        sr = rate_tracker.success_rate()
        if sr is not None and sr < 0.95 and not alert_state.get("sent_sr"):
            alert_state["sent_sr"] = True
            _send_alert(
                "[Staatsblad bulk scrape] success rate below 95%",
                f"Last 1000 attempts have {sr:.1%} success rate (threshold 95%).\n"
                f"Stats so far: done={stats['done']} retried={stats['retried']} "
                f"failed={stats['failed']} pubs={stats['pubs_written']}\n"
                f"Consider slowing down (lower --workers) or pausing until "
                f"checking proxy health in Webshare dashboard.",
            )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run(args: argparse.Namespace) -> int:
    if args.daemon:
        cycle = 0
        while True:
            cycle += 1
            rc = await run_once(args)
            if rc != 0:
                return rc
            log.info("daemon idle: sleeping %.1f seconds before next queue check", args.daemon_sleep)
            await asyncio.sleep(args.daemon_sleep)
    return await run_once(args)


async def run_once(args: argparse.Namespace) -> int:
    # Seed step (optional; safe to call any time)
    if args.seed:
        with _db() as conn:
            n = await asyncio.to_thread(seed_queue, conn)
        log.info("seed: inserted %d new CBEs into staatsblad_bulk_queue", n)
        if not args.drain_after_seed:
            return 0

    # Release any stale claims before we start.
    with _db() as conn:
        released = await asyncio.to_thread(release_stale, conn, args.stale_minutes)
        if released:
            log.info("released %d stale claims (>%d min old)", released, args.stale_minutes)
        q = await asyncio.to_thread(queue_size, conn)
    total_pending = q.get("pending", 0) + q.get("in_progress", 0)
    log.info("queue state: %s  (draining %d)", q, total_pending)
    if total_pending == 0:
        log.info("queue empty — nothing to do")
        return 0

    # Configure transport
    proxy_pool: Optional[ProxyPool] = None
    effective_workers = args.workers
    if args.mode == "webshare":
        proxy_pool = ProxyPool(args.webshare_proxies_file)
    else:
        # --mode=slow: serial, 1 req/sec matching prod cadence
        effective_workers = 1

    limits = httpx.Limits(
        max_connections=effective_workers * 2,
        max_keepalive_connections=effective_workers,
    )
    stats = {"done": 0, "retried": 0, "failed": 0, "pubs_written": 0}
    rate_tracker = RateTracker(window=1000)
    stop_flag = asyncio.Event()
    alert_state: dict = {}

    # Register crash alert — fires if the event loop exits abnormally.
    def _crash_alert() -> None:
        if stats["done"] + stats["failed"] >= total_pending:
            return  # normal completion
        _send_alert(
            "[Staatsblad bulk scrape] script exited before completion",
            f"Exited early. Stats: {stats}. Check logs.",
        )

    atexit.register(_crash_alert)

    # Signal handling so Ctrl-C gives us a clean shutdown + alert.
    def _handle_sig(*_):
        log.warning("signal received — stopping workers")
        stop_flag.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _handle_sig)

    async with httpx.AsyncClient(limits=limits, http2=False) as client:
        # In slow mode, wrap the client so each request waits 1 sec.
        if args.mode == "slow":
            original_get = client.get

            async def throttled_get(*a, **kw):
                await asyncio.sleep(1.0)
                return await original_get(*a, **kw)

            client.get = throttled_get  # type: ignore[assignment]

        sem = asyncio.Semaphore(effective_workers)
        prog = asyncio.create_task(
            progress_logger(stats, rate_tracker, stop_flag, total_pending, alert_state)
        )
        workers = [
            asyncio.create_task(
                worker(i, client, proxy_pool, sem, args.backoff_base,
                       stats, rate_tracker, stop_flag)
            )
            for i in range(effective_workers)
        ]
        await asyncio.gather(*workers)
        stop_flag.set()
        prog.cancel()

    # Final sweep / summary
    with _db() as conn:
        final = await asyncio.to_thread(queue_size, conn)
    log.info("=" * 60)
    log.info("BULK SCRAPE COMPLETE")
    log.info("  done:     %d", stats["done"])
    log.info("  retried:  %d", stats["retried"])
    log.info("  failed:   %d", stats["failed"])
    log.info("  pubs:     %d", stats["pubs_written"])
    log.info("  final queue state: %s", final)
    log.info("=" * 60)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--mode",
        choices=["webshare", "slow"],
        default="webshare",
        help="Transport: webshare (rotating proxies, 20 workers) or slow (direct, 1 req/sec)",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=20,
        help="Concurrent workers (webshare mode only; slow mode forces 1)",
    )
    p.add_argument(
        "--webshare-proxies-file",
        default=os.getenv("WEBSHARE_PROXIES_FILE", DEFAULT_PROXY_FILE),
        help=f"Path to Webshare proxy list (one IP:PORT:USER:PASS per line). "
             f"Default {DEFAULT_PROXY_FILE} or $WEBSHARE_PROXIES_FILE.",
    )
    p.add_argument(
        "--seed", action="store_true",
        help="Seed staatsblad_bulk_queue from financial_latest ∖ staatsblad_publication",
    )
    p.add_argument(
        "--drain-after-seed", action="store_true",
        help="After --seed, also drain the queue in the same invocation",
    )
    p.add_argument(
        "--stale-minutes", type=int, default=10,
        help="Reset in_progress claims older than this (crashed workers)",
    )
    p.add_argument(
        "--backoff-base", type=float, default=1.0,
        help="Base seconds for exponential backoff on worker retries",
    )
    p.add_argument(
        "--daemon", action="store_true",
        help="Stay alive after the queue drains and poll for newly-seeded work",
    )
    p.add_argument(
        "--daemon-sleep", type=float, default=60.0,
        help="Seconds to wait between queue checks in --daemon mode",
    )
    args = p.parse_args()
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        log.warning("interrupted by user")
        return 130


if __name__ == "__main__":
    sys.exit(main())
