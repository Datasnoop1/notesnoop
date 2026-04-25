"""Playwright + Webshare proxy scraper service.

Replaces the bulk Zenrows fallback path. Exposes a single internal HTTP
endpoint that the backend / enrichment-worker / on-profile retry callers
hit instead of the old Zenrows API. The proxy list and rotation policy
mirror the established pattern from `scripts/staatsblad_bulk_scrape.py`
(`ProxyPool` class) so we have one mental model for proxy handling
across the codebase.

Lifecycle:
  - On startup: load proxies from PROXIES_FILE, launch one Chromium
    instance with stealth flags.
  - Per request: borrow the browser, spin up a fresh BrowserContext with
    a randomly picked proxy, navigate, return HTML, dispose the context.
    Fresh contexts give us cookie / storage isolation between calls.
  - Periodic recycle: every BROWSER_RECYCLE_AFTER successful requests we
    fully close and relaunch Chromium. This is the single most reliable
    cure for the Chromium memory creep that otherwise leaks into the
    container's RSS over hours of operation.
  - Concurrency is capped via asyncio.Semaphore. Each in-flight context
    holds ~150-250 MB, so the default cap of 3 keeps us under 1 GB peak.

API:
  POST /scrape  body: {"url": str, "timeout_ms": int (optional)}
  -> {"html": str, "proxy_used": str|None, "elapsed_ms": int, "error": str|None}

  GET  /health  -> {"status": "ok"|"degraded", "proxies": int, "in_flight": int}

Failure modes (returned with empty html + error string):
  - "no-proxies-configured": PROXIES_FILE was empty or missing
  - "browser-not-ready": Chromium failed to launch / disconnected
  - "http-<code>": navigation got a 4xx/5xx response
  - "timeout": navigation exceeded timeout_ms
  - "<exception class>: <truncated message>": anything else

The service intentionally never raises HTTP 500 to its callers — the
caller (enrichment worker) treats empty HTML as "scrape failed" and
falls through to the template path. A noisy 500 would just trip the
health-check.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import random
import socket
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI
from playwright.async_api import Browser, async_playwright
from pydantic import BaseModel

# ── Logging ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
log = logging.getLogger("playwright-scraper")

# ── Config ─────────────────────────────────────────────────────────────
PROXIES_FILE = os.getenv("WEBSHARE_PROXIES_FILE", "/run/secrets/webshare_proxies.txt")
MAX_CONCURRENT = int(os.getenv("PLAYWRIGHT_MAX_CONCURRENT", "3"))
DEFAULT_TIMEOUT_MS = int(os.getenv("PLAYWRIGHT_DEFAULT_TIMEOUT_MS", "30000"))
NETWORK_IDLE_MS = int(os.getenv("PLAYWRIGHT_NETWORK_IDLE_MS", "5000"))
BROWSER_RECYCLE_AFTER = int(os.getenv("PLAYWRIGHT_RECYCLE_AFTER", "500"))
USER_AGENT = os.getenv(
    "PLAYWRIGHT_USER_AGENT",
    # Recent stable Chrome on Windows. Reasonable middle-ground that
    # doesn't trip "weird automation UA" heuristics.
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
)
CHROMIUM_LAUNCH_ARGS = [
    # The single most important stealth flag — without it,
    # navigator.webdriver is true and Cloudflare detects us instantly.
    "--disable-blink-features=AutomationControlled",
    # Required inside containers — Chromium can't sandbox without
    # additional kernel privileges we don't have.
    "--no-sandbox",
    # /dev/shm is small in Docker by default; spilling tab memory there
    # crashes long sessions.
    "--disable-dev-shm-usage",
    # We don't need GPU acceleration for static HTML scraping.
    "--disable-gpu",
]
# Cap on the total in-flight + queued requests. Returns 503-ish
# `queue-full` once exceeded so callers fall through to template path
# instead of piling up an unbounded asyncio waiter list.
QUEUE_LIMIT = int(os.getenv("PLAYWRIGHT_QUEUE_LIMIT", "20"))

# ── Globals ────────────────────────────────────────────────────────────
_pw = None
_browser: Browser | None = None
_proxies: list[str] = []  # raw "IP:PORT:USER:PASS" lines
_lock = asyncio.Semaphore(MAX_CONCURRENT)
_recycle_lock = asyncio.Lock()
_request_count = 0  # total scrape attempts (success+fail) since last browser launch
_queue_count = 0  # in-flight + waiting; protected by GIL (asyncio single-threaded)


# ── SSRF defence ───────────────────────────────────────────────────────
# Block scrapes targeting internal infrastructure. Without this, anything
# on the docker network with access to /scrape could exfiltrate via the
# service: backend admin routes, AWS / GCP metadata service (169.254.169.254),
# loopback Postgres, sibling docker DNS names like `backend` / `nginx`.
def _ip_is_internal(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True if the IP is private/loopback/link-local/reserved/multicast/
    unspecified, OR an IPv4-mapped IPv6 address whose underlying IPv4 is
    one of the above. The IPv4-mapped check defends against
    `http://[::ffff:127.0.0.1]/` style bypasses — the wrapper IPv6 is
    `is_loopback=False` because IPv6 loopback is `::1` only, but the
    mapped IPv4 inside is loopback.
    """
    if (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
        return True
    # ipv4_mapped attribute exists on IPv6Address; None for non-mapped.
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None and (
        mapped.is_private or mapped.is_loopback or mapped.is_link_local
        or mapped.is_reserved or mapped.is_multicast or mapped.is_unspecified
    ):
        return True
    return False


def _is_safe_url(url: str) -> tuple[bool, str]:
    """Return (safe, reason). Reject anything that isn't plain http(s) to
    a publicly routable IP. Best-effort — DNS rebinding is not handled
    (would require routing through a fixed-IP HTTP proxy or intercepting
    every Chromium request).

    The reason string is for SERVER-SIDE LOGS ONLY. Callers receive a
    generic `unsafe-url` error (see /scrape) so the response body can't
    be used to enumerate internal infrastructure IPs.
    """
    try:
        u = urlparse(url)
    except Exception as e:
        return False, f"unparseable-url:{type(e).__name__}"
    if u.scheme not in ("http", "https"):
        return False, f"bad-scheme:{u.scheme}"
    if not u.hostname:
        return False, "no-hostname"
    # Reject literal IPs that are internal, before even calling DNS.
    try:
        literal = ipaddress.ip_address(u.hostname)
        if _ip_is_internal(literal):
            return False, f"internal-ip:{literal}"
    except ValueError:
        pass  # not a literal IP, fall through to DNS resolution
    # Resolve hostname → IP(s). Any internal-range IP disqualifies the URL.
    try:
        infos = socket.getaddrinfo(u.hostname, None)
    except Exception as e:
        return False, f"dns-failed:{type(e).__name__}"
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if _ip_is_internal(ip):
            return False, f"resolves-to-internal-ip:{ip}"
    return True, ""


def _scrub_for_log(s: str, limit: int = 200) -> str:
    """Strip control chars + cap length. Defends against log-injection
    via attacker-controlled URLs containing newlines / ANSI escapes."""
    s = s[:limit]
    return "".join(c if 0x20 <= ord(c) < 0x7f else "?" for c in s)


# ── Proxy loading ──────────────────────────────────────────────────────
def _load_proxies(path: str) -> list[str]:
    """Same parser as scripts/staatsblad_bulk_scrape.py::ProxyPool.

    File format: one proxy per line as `IP:PORT:USER:PASS`. Blanks and
    `#` comments ignored. Malformed lines are dropped silently (we do
    NOT log the line content — if the path were ever mistyped to a
    secrets file we don't want it echoed into logs).
    """
    p = Path(path)
    if not p.exists():
        log.warning("proxy file not found: %s", path)
        return []
    proxies: list[str] = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.count(":") != 3:
            log.warning("skip malformed proxy line (wrong field count)")
            continue
        proxies.append(line)
    return proxies


def _parse_proxy_line(line: str) -> dict:
    """Convert `IP:PORT:USER:PASS` to Playwright's proxy dict shape."""
    ip, port, user, password = line.split(":")
    return {
        "server": f"http://{ip}:{port}",
        "username": user,
        "password": password,
    }


# ── Browser lifecycle ──────────────────────────────────────────────────
async def _launch_browser() -> Browser:
    assert _pw is not None, "playwright not started"
    return await _pw.chromium.launch(headless=True, args=CHROMIUM_LAUNCH_ARGS)


async def _maybe_recycle_browser() -> None:
    """Close + relaunch Chromium if we've crossed the recycle threshold.

    Drains the semaphore (acquires all MAX_CONCURRENT slots) before
    closing the browser so no in-flight context is using it. Without the
    drain, a concurrent /scrape could be in the middle of `new_context()`
    or `goto()` against a soon-to-be-closed Browser — the Playwright
    error from that race would surface as a generic exception in the
    caller and a spurious template-path fallback.
    """
    global _browser, _request_count
    if _request_count < BROWSER_RECYCLE_AFTER:
        return
    async with _recycle_lock:
        if _request_count < BROWSER_RECYCLE_AFTER:
            return  # another caller already recycled
        # Drain: hold all semaphore slots so /scrape can't enter the
        # critical section while we're closing/relaunching.
        slots_held = 0
        try:
            for _ in range(MAX_CONCURRENT):
                await _lock.acquire()
                slots_held += 1
            log.info("recycling Chromium after %d requests", _request_count)
            try:
                if _browser is not None:
                    await _browser.close()
            except Exception as e:
                log.warning("error closing browser during recycle: %s", e)
            try:
                _browser = await _launch_browser()
                _request_count = 0
                log.info("Chromium relaunched")
            except Exception as e:
                log.error("Chromium relaunch failed: %s", e)
                _browser = None  # /health will report degraded
        finally:
            for _ in range(slots_held):
                _lock.release()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _pw, _browser, _proxies
    _proxies = _load_proxies(PROXIES_FILE)
    log.info("loaded %d Webshare proxies from %s", len(_proxies), PROXIES_FILE)
    _pw = await async_playwright().start()
    try:
        _browser = await _launch_browser()
        log.info("Chromium launched (concurrency cap: %d)", MAX_CONCURRENT)
    except Exception as e:
        log.error("Chromium launch failed at startup: %s", e)
        _browser = None
    yield
    if _browser is not None:
        try:
            await _browser.close()
        except Exception:
            pass
    if _pw is not None:
        await _pw.stop()


app = FastAPI(lifespan=lifespan, title="playwright-scraper")


# ── API models ─────────────────────────────────────────────────────────
class ScrapeRequest(BaseModel):
    url: str
    timeout_ms: int | None = None


class ScrapeResponse(BaseModel):
    html: str
    proxy_used: str | None = None
    elapsed_ms: int
    error: str | None = None


# ── Endpoints ──────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {
        "status": "ok" if (_browser is not None and _browser.is_connected()) else "degraded",
        "proxies": len(_proxies),
        # Semaphore._value is the number of free slots, not in-flight count.
        "in_flight": MAX_CONCURRENT - _lock._value,
        "queued_or_in_flight": _queue_count,
        "queue_limit": QUEUE_LIMIT,
        "requests_since_recycle": _request_count,
    }


@app.post("/scrape", response_model=ScrapeResponse)
async def scrape(req: ScrapeRequest) -> ScrapeResponse:
    global _request_count, _queue_count
    started = time.monotonic()
    timeout_ms = req.timeout_ms or DEFAULT_TIMEOUT_MS

    # Bounded queue: refuse early if too many requests are already in
    # flight or waiting. Prevents an unbounded asyncio waiter list when
    # something upstream goes runaway. The increment/decrement around
    # this check is single-threaded under asyncio so no lock needed.
    if _queue_count >= QUEUE_LIMIT:
        return ScrapeResponse(html="", elapsed_ms=0, error="queue-full")

    # SSRF defence — reject internal targets up-front. We do this before
    # any state mutation so abuse attempts cost us no resources beyond
    # the DNS lookup. Detailed reason is logged server-side only; the
    # caller gets a generic `unsafe-url` error so the response body can't
    # be used to enumerate internal IPs (e.g. discovering that
    # `backend` resolves to `172.20.0.4`).
    safe, reason = _is_safe_url(req.url)
    if not safe:
        log.warning(
            "rejected unsafe url url=%s reason=%s",
            _scrub_for_log(req.url, 256),
            _scrub_for_log(reason, 80),
        )
        return ScrapeResponse(html="", elapsed_ms=0, error="unsafe-url")

    if not _proxies:
        return ScrapeResponse(html="", elapsed_ms=0, error="no-proxies-configured")

    proxy_line = random.choice(_proxies)
    proxy = _parse_proxy_line(proxy_line)
    proxy_label = proxy["server"]  # for logs / response

    _queue_count += 1
    try:
        async with _lock:
            # Re-check browser INSIDE the lock — recycle could have closed
            # it while we were waiting. Without this re-check we'd hand a
            # closed Browser handle to new_context() and bubble a confusing
            # error to the caller.
            if _browser is None or not _browser.is_connected():
                return ScrapeResponse(
                    html="", proxy_used=proxy_label, elapsed_ms=0,
                    error="browser-not-ready",
                )
            ctx = None
            try:
                ctx = await _browser.new_context(
                    proxy=proxy,
                    user_agent=USER_AGENT,
                    viewport={"width": 1366, "height": 768},
                    ignore_https_errors=True,
                )
                # Strip the navigator.webdriver tell. Belt-and-braces with
                # the CHROMIUM_LAUNCH_ARGS flag — Cloudflare et al. read both.
                await ctx.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', "
                    "{get: () => undefined})"
                )
                page = await ctx.new_page()
                try:
                    resp = await page.goto(
                        req.url, timeout=timeout_ms, wait_until="domcontentloaded"
                    )
                except asyncio.TimeoutError:
                    elapsed = int((time.monotonic() - started) * 1000)
                    return ScrapeResponse(
                        html="", proxy_used=proxy_label, elapsed_ms=elapsed,
                        error="timeout",
                    )

                if resp is None:
                    elapsed = int((time.monotonic() - started) * 1000)
                    return ScrapeResponse(
                        html="", proxy_used=proxy_label, elapsed_ms=elapsed,
                        error="http-noresp",
                    )
                if resp.status >= 400:
                    elapsed = int((time.monotonic() - started) * 1000)
                    return ScrapeResponse(
                        html="", proxy_used=proxy_label, elapsed_ms=elapsed,
                        error=f"http-{resp.status}",
                    )

                # Wait for late-arriving content but don't block forever — many
                # sites never go fully idle (long-poll trackers, video players).
                try:
                    await page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_MS)
                except Exception:
                    pass

                html = await page.content()
                elapsed = int((time.monotonic() - started) * 1000)
                return ScrapeResponse(
                    html=html, proxy_used=proxy_label, elapsed_ms=elapsed,
                )
            except Exception as e:
                elapsed = int((time.monotonic() - started) * 1000)
                err = f"{type(e).__name__}: {str(e)[:200]}"
                log.warning(
                    "scrape failed url=%s proxy=%s elapsed=%dms err=%s",
                    req.url, proxy_label, elapsed, err,
                )
                return ScrapeResponse(
                    html="", proxy_used=proxy_label, elapsed_ms=elapsed, error=err,
                )
            finally:
                # Increment recycle counter on EVERY attempt, success or
                # failure. Otherwise a failure-only workload (e.g. proxy
                # outage) would never trigger Chromium recycle and the
                # container would OOM as Chromium memory creeps up.
                _request_count += 1
                if ctx is not None:
                    try:
                        await ctx.close()
                    except Exception:
                        pass
    finally:
        _queue_count -= 1

    # Recycle outside the semaphore so we don't block in-flight requests.
    # `_maybe_recycle_browser` itself drains the semaphore before closing,
    # so this is safe under concurrent /scrape calls.
    await _maybe_recycle_browser()
