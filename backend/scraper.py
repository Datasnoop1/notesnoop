"""Zenrows web scraper for company enrichment.

Provides async helpers to scrape company websites and LinkedIn profiles
via the Zenrows proxy API, then extract structured data with AI.
"""

import asyncio
import os
import logging
import re
import time as _time
import html as _html
import xml.etree.ElementTree as _et

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

ZENROWS_KEY = os.getenv("ZENROWS_API_KEY", "")
ZENROWS_BASE = "https://api.zenrows.com/v1/"

# ── Playwright + Webshare proxy scraper ───────────────────────────────
# As of 2026-04-25 the proxy fallback is served by an in-network
# playwright-scraper container (see docker-compose.yml + playwright-scraper/).
# The Zenrows function names below stay intact for backwards compatibility,
# but their bodies now delegate to this internal HTTP service. Set the env
# var to empty to disable the proxy fallback entirely.
PLAYWRIGHT_SCRAPER_URL = os.getenv("PLAYWRIGHT_SCRAPER_URL", "").rstrip("/")
# Network-side timeout buffer — the playwright service has its own page
# timeout (defaults to 30s); we add a small margin to account for queueing
# behind the in-flight semaphore inside the service.
PLAYWRIGHT_HTTP_TIMEOUT_S = float(os.getenv("PLAYWRIGHT_HTTP_TIMEOUT_S", "75"))


def _url_passes_basic_ssrf_guard(url: str) -> bool:
    """Cheap pre-flight SSRF check before we send a URL to the scraper.

    Rejects bad schemes and literal private/loopback IPs without doing
    DNS — the playwright service does the full DNS-resolved check as a
    second line of defence. This is intentionally a fast belt-and-braces
    pass: stop obvious abuse without round-tripping through the scraper.

    Handles the IPv4-mapped IPv6 bypass (`http://[::ffff:127.0.0.1]/`):
    Python's `is_loopback` returns False for the IPv6 wrapper because
    IPv6 loopback is `::1` only, but the underlying IPv4 IS loopback.
    """
    from urllib.parse import urlparse
    import ipaddress

    try:
        u = urlparse(url)
    except Exception:
        return False
    if u.scheme not in ("http", "https"):
        return False
    if not u.hostname:
        return False
    try:
        ip = ipaddress.ip_address(u.hostname)
    except ValueError:
        return True  # not a literal IP — let the scraper resolve and judge

    def _internal(addr) -> bool:
        if (addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_reserved or addr.is_multicast or addr.is_unspecified):
            return True
        mapped = getattr(addr, "ipv4_mapped", None)
        if mapped is not None and (
            mapped.is_private or mapped.is_loopback or mapped.is_link_local
            or mapped.is_reserved or mapped.is_multicast or mapped.is_unspecified
        ):
            return True
        return False

    return not _internal(ip)


async def _playwright_fetch(url: str, timeout_ms: int | None = None) -> str:
    """Fetch a URL via the in-network playwright-scraper service.

    Returns the raw HTML on success, or an empty string on any failure
    (no proxies, browser down, HTTP error, timeout, network error).
    Callers should treat the empty return as "scrape failed, fall through
    to template path" — same contract the old Zenrows path had.
    """
    if not PLAYWRIGHT_SCRAPER_URL:
        return ""
    if not _url_passes_basic_ssrf_guard(url):
        # Truncate + strip control chars so a malicious URL can't
        # corrupt the log line (e.g. inject fake INFO records via
        # newlines).
        safe_log = "".join(
            c if 0x20 <= ord(c) < 0x7f else "?" for c in url[:256]
        )
        logger.warning("playwright-scraper: refusing unsafe url %s", safe_log)
        return ""
    payload: dict[str, object] = {"url": url}
    if timeout_ms is not None:
        payload["timeout_ms"] = timeout_ms
    try:
        async with httpx.AsyncClient(timeout=PLAYWRIGHT_HTTP_TIMEOUT_S) as client:
            resp = await client.post(
                f"{PLAYWRIGHT_SCRAPER_URL}/scrape", json=payload,
            )
            if resp.status_code != 200:
                logger.warning(
                    "playwright-scraper returned HTTP %d for %s",
                    resp.status_code, url,
                )
                return ""
            data = resp.json()
            html = data.get("html") or ""
            if not html:
                err = data.get("error") or "empty"
                logger.info(
                    "playwright-scraper miss url=%s proxy=%s elapsed=%dms err=%s",
                    url,
                    data.get("proxy_used"),
                    int(data.get("elapsed_ms") or 0),
                    err,
                )
                return ""
            logger.info(
                "playwright-scraper hit url=%s proxy=%s elapsed=%dms bytes=%d",
                url,
                data.get("proxy_used"),
                int(data.get("elapsed_ms") or 0),
                len(html),
            )
            return html
    except Exception as e:
        logger.warning("playwright-scraper request failed for %s: %s", url, e)
        return ""

# ── DuckDuckGo rate-limit protection ──────────────────────────────────
# Phase 0 mini-spike (scripts/research/v3) observed DDG 403s after ~50
# sequential calls from one IP. The bulk worker calls
# `duckduckgo_search_url` twice per CBE (website + LinkedIn search), so
# at 400k no-web CBEs we'd hit the limit in minutes without throttling.
# Defaults are intentionally conservative for production quality.
# Overridable via env for tuning / local smoke tests.
DDG_MIN_INTERVAL_S = float(os.getenv("DDG_MIN_INTERVAL_S", "8.0"))
DDG_MAX_INTERVAL_S = float(os.getenv("DDG_MAX_INTERVAL_S", "45.0"))
DDG_RATELIMIT_COOLDOWN_S = float(os.getenv("DDG_RATELIMIT_COOLDOWN_S", "90.0"))
DDG_RATELIMIT_MULTIPLIER = float(os.getenv("DDG_RATELIMIT_MULTIPLIER", "1.8"))
DDG_RECOVERY_STEP_S = float(os.getenv("DDG_RECOVERY_STEP_S", "0.5"))
DDG_SUCCESS_STREAK_TO_RECOVER = int(os.getenv("DDG_SUCCESS_STREAK_TO_RECOVER", "5"))
BING_FALLBACK_ENABLED = os.getenv("BING_FALLBACK_ENABLED", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

_ddg_lock = asyncio.Lock()
_ddg_last_call: float = 0.0
_ddg_dynamic_interval_s: float = max(DDG_MIN_INTERVAL_S, 0.1)
_ddg_cooldown_until: float = 0.0
_ddg_rate_limit_streak: int = 0
_ddg_success_streak: int = 0


# ── Webshare proxy pool for DDG (Wave 2 acceleration) ─────────────────
# Routes DuckDuckGo HTML calls through a rotating Webshare datacenter
# proxy pool, lifting the per-IP rate-limit ceiling that was the binding
# constraint with WORKER_CONCURRENCY > 1. With 100 proxies the effective
# DDG quota goes from ~180/hr (single IP at 20s/call) to potentially
# 1k-5k/hr before DDG ML-detects the rotation.
#
# Same proxy file used by the staatsblad bulk worker
# (/root/webshare_proxies.txt on the host, mounted to
# /run/secrets/webshare_proxies.txt inside the container).
import random as _random
from pathlib import Path as _Path

WEBSHARE_PROXIES_FILE = os.getenv(
    "WEBSHARE_PROXIES_FILE", "/run/secrets/webshare_proxies.txt"
)
DDG_VIA_WEBSHARE = os.getenv("DDG_VIA_WEBSHARE", "false").strip().lower() in {
    "1", "true", "yes", "on",
}
# When DDG_VIA_WEBSHARE is on, this is the much-shorter throttle that
# governs total DDG calls/sec from THIS PROCESS (not per-IP). Each call
# rotates to a different proxy IP so DDG's per-IP rate-limit doesn't
# apply, but a global cap is still polite and avoids accidentally
# detected-as-bot patterns.
DDG_VIA_WEBSHARE_MIN_INTERVAL_S = float(
    os.getenv("DDG_VIA_WEBSHARE_MIN_INTERVAL_S", "0.5")
)


def _load_webshare_proxies(path: str) -> list[str]:
    """Same parser as scripts/staatsblad_bulk_scrape.py::ProxyPool — file
    has one `IP:PORT:USER:PASS` per line; returns httpx-ready proxy URLs
    `http://USER:PASS@IP:PORT`. Malformed lines are dropped silently
    (we never log line content — defends against accidentally pointing
    the path at a secrets file).
    """
    p = _Path(path)
    if not p.exists():
        return []
    out: list[str] = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.count(":") != 3:
            continue
        ip, port, user, pw = line.split(":")
        out.append(f"http://{user}:{pw}@{ip}:{port}")
    return out


_WEBSHARE_DDG_PROXIES: list[str] = (
    _load_webshare_proxies(WEBSHARE_PROXIES_FILE) if DDG_VIA_WEBSHARE else []
)
if DDG_VIA_WEBSHARE:
    if _WEBSHARE_DDG_PROXIES:
        logger.info(
            "DDG via Webshare ENABLED: %d proxies loaded from %s "
            "(min_interval=%.2fs)",
            len(_WEBSHARE_DDG_PROXIES),
            WEBSHARE_PROXIES_FILE,
            DDG_VIA_WEBSHARE_MIN_INTERVAL_S,
        )
    else:
        logger.warning(
            "DDG_VIA_WEBSHARE=true but no proxies loaded from %s — "
            "falling back to direct DDG with per-host throttle.",
            WEBSHARE_PROXIES_FILE,
        )

# Circuit-breaker for the case where DDG bans the entire Webshare ASN.
# Per-proxy 4xx are normal (one bad IP doesn't fail the cohort), but if
# we see a long run of 4xx across DIFFERENT IPs, that's a signal the
# whole pool is hot and we should back off globally. Reset on any 200.
_DDG_PROXY_4XX_BREAKER_THRESHOLD = int(
    os.getenv("DDG_VIA_WEBSHARE_BREAKER_THRESHOLD", "20")
)
_ddg_proxy_4xx_streak: int = 0


def _ddg_proxy_or_none() -> str | None:
    """Return a random Webshare proxy URL if rotation is enabled and the
    pool is non-empty, else None (caller goes direct).
    """
    if not _WEBSHARE_DDG_PROXIES:
        return None
    return _random.choice(_WEBSHARE_DDG_PROXIES)


def _scrub_proxy_url(text: str) -> str:
    """Strip Webshare credentials from a string before logging.

    httpx / urllib3 occasionally include the full proxy URL (with
    user:password embedded) in connection error messages. Replace
    `http://USER:PASS@HOST:PORT` with `http://<proxy>` so creds never
    land in /var/log.
    """
    return re.sub(
        r"http://[^:@\s]+:[^@\s]+@",
        "http://<proxy>",
        text,
    )


async def _ddg_throttle() -> None:
    """Sleep until at least DDG_MIN_INTERVAL_S has elapsed since the last call.

    Shared across every async task in this process — the bulk worker runs
    concurrent jobs and a per-task sleep wouldn't actually rate-limit at
    the DDG origin. The lock serialises the wait window so two tasks can't
    both wake up and fire simultaneously.

    When Webshare-DDG rotation is enabled (`DDG_VIA_WEBSHARE=true`), each
    call goes through a different proxy IP so DDG's per-IP rate-limit no
    longer applies. We still hold a much-shorter global throttle (default
    0.5 s) to avoid spiking the DDG origin and to remain a polite client.
    """
    global _ddg_last_call
    async with _ddg_lock:
        now = _time.monotonic()
        if now < _ddg_cooldown_until:
            await asyncio.sleep(_ddg_cooldown_until - now)
            now = _time.monotonic()
        if _WEBSHARE_DDG_PROXIES:
            min_gap = DDG_VIA_WEBSHARE_MIN_INTERVAL_S
        else:
            min_gap = max(DDG_MIN_INTERVAL_S, _ddg_dynamic_interval_s)
        delta = now - _ddg_last_call
        if delta < min_gap:
            await asyncio.sleep(min_gap - delta)
        _ddg_last_call = _time.monotonic()


async def _ddg_proxy_4xx_observed(status: int, label: str) -> None:
    """Track 4xx-via-proxy hits and trip the global cooldown if too many
    fire back-to-back across DIFFERENT proxy IPs (signal that DDG has
    blocklisted the whole Webshare ASN, not just one IP).
    """
    global _ddg_proxy_4xx_streak
    async with _ddg_lock:
        _ddg_proxy_4xx_streak += 1
        if _ddg_proxy_4xx_streak >= _DDG_PROXY_4XX_BREAKER_THRESHOLD:
            # Re-use the existing cooldown machinery so the rest of the
            # worker behaves consistently. Reset the streak so we don't
            # re-trigger every call until the cooldown passes.
            await _ddg_record_rate_limit(status, "<proxy-pool>", label)
            _ddg_proxy_4xx_streak = 0
            logger.warning(
                "DDG via Webshare circuit-breaker tripped: %d consecutive "
                "4xx across different proxy IPs — entering global cooldown",
                _DDG_PROXY_4XX_BREAKER_THRESHOLD,
            )


async def _ddg_proxy_2xx_observed() -> None:
    """Reset the 4xx streak on any successful proxy-routed call."""
    global _ddg_proxy_4xx_streak
    async with _ddg_lock:
        _ddg_proxy_4xx_streak = 0


async def _ddg_record_success() -> None:
    """Gradually recover toward the floor interval after sustained success."""
    global _ddg_success_streak, _ddg_rate_limit_streak, _ddg_dynamic_interval_s
    async with _ddg_lock:
        _ddg_rate_limit_streak = 0
        _ddg_success_streak += 1
        if (
            _ddg_success_streak >= DDG_SUCCESS_STREAK_TO_RECOVER
            and _ddg_dynamic_interval_s > DDG_MIN_INTERVAL_S
        ):
            _ddg_dynamic_interval_s = max(
                DDG_MIN_INTERVAL_S,
                _ddg_dynamic_interval_s - DDG_RECOVERY_STEP_S,
            )
            _ddg_success_streak = 0


async def _ddg_record_rate_limit(status_code: int, company_name: str, query_kind: str) -> None:
    """Escalate interval and cooldown after DDG 403/429."""
    global _ddg_rate_limit_streak, _ddg_success_streak, _ddg_dynamic_interval_s, _ddg_cooldown_until
    async with _ddg_lock:
        _ddg_success_streak = 0
        _ddg_rate_limit_streak += 1

        _ddg_dynamic_interval_s = min(
            DDG_MAX_INTERVAL_S,
            max(
                _ddg_dynamic_interval_s * DDG_RATELIMIT_MULTIPLIER,
                _ddg_dynamic_interval_s + 1.0,
            ),
        )
        cooldown_s = DDG_RATELIMIT_COOLDOWN_S * min(_ddg_rate_limit_streak, 4)
        _ddg_cooldown_until = max(_ddg_cooldown_until, _time.monotonic() + cooldown_s)

        logger.warning(
            "DuckDuckGo rate-limited (%s) on %s search for %s; interval=%.1fs cooldown=%.1fs streak=%d",
            status_code,
            query_kind,
            company_name,
            _ddg_dynamic_interval_s,
            cooldown_s,
            _ddg_rate_limit_streak,
        )


# ── Aggregator skip-list (DB-backed with hardcoded fallback) ──────────
# Phase 0 recommendation: treat the skip-list as a maintained inventory,
# not a static constant. The `aggregator_skiplist` table is the source
# of truth; we cache it for 5 minutes so discovery stays fast.
# If the DB is unreachable we fall back to the seed list below so the
# bulk worker never blocks on a transient DB hiccup.

_SEED_SKIP_DOMAINS = frozenset({
    "google.com", "google.be", "gstatic.com", "googleapis.com",
    "wikipedia.org", "facebook.com", "twitter.com", "instagram.com",
    "youtube.com", "tiktok.com", "pinterest.com", "reddit.com",
    "linkedin.com",  # LinkedIn handled separately
    "yelp.com", "tripadvisor.com", "trustpilot.com",
    "staatsbladmonitor.be", "companyweb.be", "trends.knack.be",
    "kompass.com", "europages.com", "dnb.com",
    # Phase 0 additions:
    "pappers.be", "bsearch.be", "handelsgids.be", "infobel.be",
    "immoweb.be", "lemariagedelouise.be", "economie.fgov.be",
})
_SEED_SKIP_PATHS: frozenset[str] = frozenset({
    "/bedrijvengids/", "/annuaire/", "/infrastructuur-",
})

_skiplist_cache: dict = {"expires_at": 0.0, "domains": set(), "paths": set()}
_SKIPLIST_TTL_S = 300.0


def _load_skiplist() -> tuple[set[str], set[str]]:
    """Read the aggregator skip-list from DB, with a 5-minute cache.

    Returns (domain_set, path_set). If the DB query fails, falls back to
    the seed sets so discovery keeps working against a broken DB.
    """
    now = _time.monotonic()
    if _skiplist_cache["expires_at"] > now and _skiplist_cache["domains"]:
        return _skiplist_cache["domains"], _skiplist_cache["paths"]

    try:
        from db import fetch_all
        rows = fetch_all("SELECT pattern, kind FROM aggregator_skiplist")
        domains = {r["pattern"].lower() for r in rows if r.get("kind") == "domain"}
        paths = {r["pattern"] for r in rows if r.get("kind") == "path"}
        # Union with the seed sets — the DB list typically SUPERSETS the seed
        # (via the schema.sql INSERT), but this is belt-and-braces.
        domains |= _SEED_SKIP_DOMAINS
        paths |= _SEED_SKIP_PATHS
        _skiplist_cache.update({
            "expires_at": now + _SKIPLIST_TTL_S,
            "domains": domains,
            "paths": paths,
        })
        return domains, paths
    except Exception as e:
        logger.debug("aggregator skip-list DB load failed, using seed: %s", e)
        return set(_SEED_SKIP_DOMAINS), set(_SEED_SKIP_PATHS)


def invalidate_skiplist_cache() -> None:
    """Drop the in-process cache — called by the admin UI after an edit."""
    _skiplist_cache.update({"expires_at": 0.0, "domains": set(), "paths": set()})


async def scrape_url(url: str, js_render: bool = False, premium_proxy: bool = False) -> str:
    """Scrape a URL via the playwright-scraper service. Returns HTML text.

    The `js_render` and `premium_proxy` parameters are kept for backwards
    compatibility with old Zenrows callers, but a real headless Chromium
    always renders JS — they're now interpreted as timeout hints:

    - js_render=True OR premium_proxy=True → 60 s page timeout (was: 60s
      Zenrows API timeout + JS render flag). LinkedIn / heavy SPAs.
    - default → 30 s page timeout. Most company sites.
    """
    timeout_ms = 60000 if (js_render or premium_proxy) else 30000
    return await _playwright_fetch(url, timeout_ms=timeout_ms)


def _strip_html(html: str, max_chars: int = 12000) -> str:
    """Crude HTML-to-text extraction to keep AI prompt tokens manageable."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")

    # Remove script/style/nav/footer noise
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "svg"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)
    # Collapse whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:max_chars]


def is_linkedin_url(url: str) -> bool:
    """Check if a URL points to LinkedIn."""
    return "linkedin.com" in url.lower()


async def duckduckgo_search_url(
    company_name: str,
    city: str = "",
    country: str = "Belgium",
    *,
    include_website: bool = True,
    include_linkedin: bool = True,
) -> dict:
    """Search DuckDuckGo for a company's website and/or LinkedIn page.

    Callers can disable unneeded lookups so the bulk worker doesn't pay
    the DDG throttle cost for LinkedIn discovery it never uses.
    """
    location_part = f" {city}" if city else ""
    website_url = None
    linkedin_url = None

    # ── Search for company website ──────────────────────────────
    if include_website:
        website_query = f"{company_name}{location_part} {country} official website"
        await _ddg_throttle()
        proxy = _ddg_proxy_or_none()
        client_kwargs: dict = {"timeout": 5.0}
        if proxy:
            client_kwargs["proxy"] = proxy
        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                resp = await client.get(
                    f"https://html.duckduckgo.com/html/?q={_url_encode(website_query)}",
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                    follow_redirects=True,
                )
                if resp.status_code == 200:
                    await _ddg_record_success()
                    if proxy:
                        await _ddg_proxy_2xx_observed()
                    website_url = _extract_best_website(resp.text, company_name)
                elif resp.status_code in (403, 429):
                    # Per-IP rate limit only matters when going direct.
                    # When rotating Webshare proxies, a 429 on one IP
                    # doesn't mean all IPs are throttled — but track
                    # cross-proxy 4xx streaks so we trip a circuit
                    # breaker if DDG bans the whole Webshare ASN.
                    if proxy:
                        await _ddg_proxy_4xx_observed(resp.status_code, "website")
                    else:
                        await _ddg_record_rate_limit(resp.status_code, company_name, "website")
        except Exception as e:
            logger.warning("DuckDuckGo website search failed for %s: %s", company_name, _scrub_proxy_url(str(e)))

    # ── Search for LinkedIn page ────────────────────────────────
    if include_linkedin:
        linkedin_query = f"{company_name}{location_part} site:linkedin.com/company"
        await _ddg_throttle()
        proxy = _ddg_proxy_or_none()
        client_kwargs: dict = {"timeout": 5.0}
        if proxy:
            client_kwargs["proxy"] = proxy
        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                resp = await client.get(
                    f"https://html.duckduckgo.com/html/?q={_url_encode(linkedin_query)}",
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                    follow_redirects=True,
                )
                if resp.status_code == 200:
                    await _ddg_record_success()
                    if proxy:
                        await _ddg_proxy_2xx_observed()
                    linkedin_url = _extract_linkedin_url(resp.text)
                elif resp.status_code in (403, 429):
                    if proxy:
                        await _ddg_proxy_4xx_observed(resp.status_code, "linkedin")
                    else:
                        await _ddg_record_rate_limit(resp.status_code, company_name, "linkedin")
        except Exception as e:
            logger.warning("DuckDuckGo LinkedIn search failed for %s: %s", company_name, _scrub_proxy_url(str(e)))

    logger.info(
        "DuckDuckGo search for '%s': website=%s, linkedin=%s",
        company_name, website_url or "(none)", linkedin_url or "(none)",
    )
    return {"website_url": website_url, "linkedin_url": linkedin_url}


async def duckduckgo_search_website_url(
    company_name: str, city: str = "", country: str = "Belgium"
) -> str | None:
    """Website-only DDG lookup for the bulk worker.

    The generic helper also performs a LinkedIn search, which is useful
    for profile enrichment but wastes a second throttled DDG call during
    bulk website discovery.
    """
    location_part = f" {city}" if city else ""
    website_query = f"{company_name}{location_part} {country} official website"
    ddg_rate_limited = False
    await _ddg_throttle()
    proxy = _ddg_proxy_or_none()
    client_kwargs: dict = {"timeout": 5.0}
    if proxy:
        client_kwargs["proxy"] = proxy
    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            resp = await client.get(
                f"https://html.duckduckgo.com/html/?q={_url_encode(website_query)}",
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                follow_redirects=True,
            )
            if resp.status_code == 200:
                await _ddg_record_success()
                if proxy:
                    await _ddg_proxy_2xx_observed()
                return _extract_best_website(resp.text, company_name)
            if resp.status_code in (403, 429):
                ddg_rate_limited = True
                # When rotating Webshare proxies, a 429 on one IP doesn't
                # imply the global cooldown — but track the streak so we
                # trip the breaker if DDG bans the whole Webshare ASN.
                if proxy:
                    await _ddg_proxy_4xx_observed(resp.status_code, "website")
                else:
                    await _ddg_record_rate_limit(resp.status_code, company_name, "website")
    except Exception as e:
        logger.warning("DuckDuckGo website search failed for %s: %s", company_name, _scrub_proxy_url(str(e)))
    if BING_FALLBACK_ENABLED:
        if ddg_rate_limited:
            logger.info("Website discovery fallback for %s: trying Bing RSS after DDG rate-limit", company_name)
        website = await bing_search_website_url(company_name, city=city, country=country)
        if website:
            logger.info("Website discovery for %s: website from Bing RSS — %s", company_name, website)
            return website
    return None


async def duckduckgo_search_linkedin_url(
    company_name: str, city: str = ""
) -> str | None:
    """LinkedIn-only DDG lookup for the profile pipeline."""
    location_part = f" {city}" if city else ""
    linkedin_query = f"{company_name}{location_part} site:linkedin.com/company"
    ddg_rate_limited = False
    await _ddg_throttle()
    proxy = _ddg_proxy_or_none()
    client_kwargs: dict = {"timeout": 5.0}
    if proxy:
        client_kwargs["proxy"] = proxy
    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            resp = await client.get(
                f"https://html.duckduckgo.com/html/?q={_url_encode(linkedin_query)}",
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                follow_redirects=True,
            )
            if resp.status_code == 200:
                await _ddg_record_success()
                if proxy:
                    await _ddg_proxy_2xx_observed()
                return _extract_linkedin_url(resp.text)
            if resp.status_code in (403, 429):
                ddg_rate_limited = True
                if proxy:
                    await _ddg_proxy_4xx_observed(resp.status_code, "linkedin")
                else:
                    await _ddg_record_rate_limit(resp.status_code, company_name, "linkedin")
    except Exception as e:
        logger.warning("DuckDuckGo LinkedIn search failed for %s: %s", company_name, _scrub_proxy_url(str(e)))
    if BING_FALLBACK_ENABLED:
        if ddg_rate_limited:
            logger.info("LinkedIn discovery fallback for %s: trying Bing RSS after DDG rate-limit", company_name)
        linkedin = await bing_search_linkedin_url(company_name, city=city)
        if linkedin:
            logger.info("LinkedIn discovery for %s: LinkedIn from Bing RSS — %s", company_name, linkedin)
            return linkedin
    return None


async def _bing_rss_links(query: str, timeout: float = 6.0) -> list[str]:
    """Run a Bing RSS query and return candidate result URLs."""
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(
                "https://www.bing.com/search",
                params={"q": query, "format": "rss"},
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.status_code != 200:
                logger.info("Bing RSS returned %s for query %s", resp.status_code, query)
                return []
            root = _et.fromstring(resp.text)
            links: list[str] = []
            for item in root.findall(".//item/link"):
                if item.text and item.text.startswith("http"):
                    links.append(item.text.strip())
            return links
    except Exception as e:
        logger.info("Bing RSS lookup failed for query %s: %s", query, e)
        return []


async def bing_search_website_url(
    company_name: str, city: str = "", country: str = "Belgium"
) -> str | None:
    """Website discovery via Bing RSS fallback."""
    location_part = f" {city}" if city else ""
    query = f"{company_name}{location_part} {country} official website"
    links = await _bing_rss_links(query)
    if not links:
        return None
    return _extract_best_website_from_urls(links, company_name)


async def bing_search_linkedin_url(
    company_name: str, city: str = ""
) -> str | None:
    """LinkedIn company-page discovery via Bing RSS fallback."""
    location_part = f" {city}" if city else ""
    query = f"{company_name}{location_part} site:linkedin.com/company"
    links = await _bing_rss_links(query)
    if not links:
        return None
    return _extract_linkedin_url_from_urls(links)


async def zenrows_search_url(
    company_name: str, city: str = "", country: str = "Belgium"
) -> dict:
    """Search Google via Zenrows for a company's website and LinkedIn page.

    RETRY fallback only — not used by the bulk enrichment worker.
    Phase 0 mini-spike (scripts/research/v3) found this path returns 0%
    usable hits on our current Zenrows plan (requires premium SERP
    addon), so the bulk path skips it. Kept here for the user-flagged-
    wrong-website retry flow in `ai_insights_pipeline`, which charges
    Zenrows credits per call — tolerable at single-company cadence.
    Returns: {"website_url": str|None, "linkedin_url": str|None}
    """
    if not ZENROWS_KEY:
        return {"website_url": None, "linkedin_url": None}

    location_part = f" {city}" if city else ""
    website_url = None
    linkedin_url = None

    website_query = f"{company_name}{location_part} {country} official website"
    google_url = f"https://www.google.com/search?q={_url_encode(website_query)}&num=10&hl=en"
    try:
        html = await _zenrows_fetch(google_url, timeout=5)
        if html:
            website_url = _extract_best_website(html, company_name)
    except Exception as e:
        logger.warning("Zenrows website search failed for %s: %s", company_name, e)

    linkedin_query = f"{company_name}{location_part} site:linkedin.com/company"
    linkedin_google_url = f"https://www.google.com/search?q={_url_encode(linkedin_query)}&num=5&hl=en"
    try:
        html = await _zenrows_fetch(linkedin_google_url, timeout=5)
        if html:
            linkedin_url = _extract_linkedin_url(html)
    except Exception as e:
        logger.warning("Zenrows LinkedIn search failed for %s: %s", company_name, e)

    logger.info(
        "Zenrows search for '%s': website=%s, linkedin=%s",
        company_name, website_url or "(none)", linkedin_url or "(none)",
    )
    return {"website_url": website_url, "linkedin_url": linkedin_url}


async def zenrows_search_website_url(
    company_name: str, city: str = "", country: str = "Belgium"
) -> str | None:
    """Website-only Zenrows search for the retry path."""
    if not ZENROWS_KEY:
        return None
    location_part = f" {city}" if city else ""
    website_query = f"{company_name}{location_part} {country} official website"
    google_url = f"https://www.google.com/search?q={_url_encode(website_query)}&num=10&hl=en"
    try:
        html = await _zenrows_fetch(google_url, timeout=5)
        if html:
            return _extract_best_website(html, company_name)
    except Exception as e:
        logger.warning("Zenrows website search failed for %s: %s", company_name, e)
    return None


def _url_encode(query: str) -> str:
    """URL-encode a search query string."""
    from urllib.parse import quote_plus
    return quote_plus(query)


async def _zenrows_fetch(url: str, timeout: int = 5) -> str:
    """Fetch a URL via the playwright-scraper service. Returns HTML or empty string.

    Used by the Google-SERP discovery helpers (`zenrows_search_url` and
    `zenrows_search_website_url`). The legacy `timeout` parameter is in
    seconds and gets converted to milliseconds for the Playwright service.

    NOTE: Phase 0 already showed the Google-SERP path is essentially 0%
    viable through datacenter proxies (Google fingerprints them aggressively).
    These helpers are kept wired for completeness but do NOT expect them to
    routinely return useful HTML — DDG remains the working discovery path.
    """
    return await _playwright_fetch(url, timeout_ms=max(timeout, 1) * 1000)


# Legacy export retained for any code importing the old constant.
# The live list lives in the `aggregator_skiplist` table, loaded via
# `_load_skiplist()`. DO NOT extend this set — add to the DB instead.
_SKIP_DOMAINS: frozenset[str] = _SEED_SKIP_DOMAINS


def _extract_best_website_from_urls(urls: list[str], company_name: str) -> str | None:
    """Rank a plain URL list using the same heuristics as HTML extraction."""
    if not urls:
        return None
    fake_html = "".join(
        f'<a href="{_html.escape(u, quote=True)}">result</a>'
        for u in urls
        if u and u.startswith("http")
    )
    return _extract_best_website(fake_html, company_name)


def _extract_linkedin_url_from_urls(urls: list[str]) -> str | None:
    """Return the first clean linkedin.com/company URL from a URL list."""
    from urllib.parse import urlparse

    for url in urls:
        if not url or "linkedin.com/company/" not in url.lower():
            continue
        parsed = urlparse(url)
        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        return clean_url.rstrip("/")
    return None


def _extract_best_website(html: str, company_name: str) -> str | None:
    """Parse search results HTML (DuckDuckGo or Google) and return the best company website URL.

    Skips social media, Wikipedia, aggregator sites.
    Prefers .be domains and domains that resemble the company name.

    Skip-list is loaded from the `aggregator_skiplist` DB table
    (cached in-process for 5 min) with a seed fallback — see
    `_load_skiplist`. Edits to the list via the admin UI take effect on
    the next cache refresh.
    """
    from bs4 import BeautifulSoup
    from urllib.parse import urlparse, parse_qs, unquote

    soup = BeautifulSoup(html, "html.parser")
    candidates: list[tuple[str, int]] = []  # (url, priority_score)

    legal_noise = {
        "bv",
        "bvba",
        "nv",
        "sa",
        "srl",
        "sprl",
        "asbl",
        "vzw",
        "cv",
        "cvba",
        "group",
        "holding",
        "services",
    }
    name_slug = re.sub(r"[^a-z0-9]", "", company_name.lower())
    name_tokens = [
        tok
        for tok in re.findall(r"[a-z0-9]{4,}", company_name.lower())
        if tok not in legal_noise
    ]

    skip_domains, skip_paths = _load_skiplist()

    # Extract URLs from <a> tags — handles both DuckDuckGo and Google formats
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        url = None

        # DuckDuckGo wraps in //duckduckgo.com/l/?uddg=... redirects
        if "uddg=" in href:
            parsed = urlparse(href)
            qs = parse_qs(parsed.query)
            if "uddg" in qs:
                url = unquote(qs["uddg"][0])
        # Google wraps results in /url?q=... redirects
        elif "/url?q=" in href:
            parsed = urlparse(href)
            qs = parse_qs(parsed.query)
            if "q" in qs:
                url = unquote(qs["q"][0])
        elif href.startswith("http"):
            url = href

        if not url or not url.startswith("http"):
            continue

        # Parse the domain and path
        try:
            parsed_u = urlparse(url)
            domain = parsed_u.netloc.lower().lstrip("www.")
            path_lower = (parsed_u.path or "").lower()
        except Exception:
            continue

        # Skip known non-company domains (DB-backed + seed)
        if any(skip in domain for skip in skip_domains):
            continue

        # Skip aggregator path substrings (e.g. /bedrijvengids/, /annuaire/)
        if any(sp in path_lower for sp in skip_paths):
            continue

        # Skip Google cache/translate links
        if "webcache.googleusercontent" in url or "translate.google" in url:
            continue

        # Score the candidate
        score = 0
        domain_parts = [p for p in domain.split(".") if p]
        primary_label = domain_parts[-2] if len(domain_parts) >= 2 else domain_parts[0]
        domain_slug = re.sub(r"[^a-z0-9]", "", primary_label)
        token_hit = any(tok in domain_slug for tok in name_tokens)
        slug_hit = bool(
            name_slug and len(domain_slug) >= 4 and (
                name_slug in domain_slug or domain_slug in name_slug
            )
        )

        # Precision guard: never accept a candidate with zero lexical overlap.
        # This blocks random SERP drift (e.g. forums/app stores) from
        # poisoning company summaries when search quality degrades.
        if not token_hit and not slug_hit:
            continue

        # Strong signal: domain matches company name
        if slug_hit:
            score += 10
        elif token_hit:
            score += 6

        # Prefer .be domains for Belgian companies
        if domain.endswith(".be"):
            score += 5

        # Prefer shorter domains (less likely to be aggregator/directory)
        if len(domain) < 30:
            score += 2

        candidates.append((url, score))

    if not candidates:
        return None

    # Sort by score descending, return the best match
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[0][0]


def _extract_linkedin_url(html: str) -> str | None:
    """Parse search results HTML (DuckDuckGo or Google) and return the first linkedin.com/company URL."""
    from bs4 import BeautifulSoup
    from urllib.parse import urlparse, parse_qs, unquote

    soup = BeautifulSoup(html, "html.parser")

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        url = None

        # DuckDuckGo redirect
        if "uddg=" in href:
            parsed = urlparse(href)
            qs = parse_qs(parsed.query)
            if "uddg" in qs:
                url = unquote(qs["uddg"][0])
        # Google redirect
        elif "/url?q=" in href:
            parsed = urlparse(href)
            qs = parse_qs(parsed.query)
            if "q" in qs:
                url = unquote(qs["q"][0])
        elif href.startswith("http"):
            url = href

        if url and "linkedin.com/company/" in url:
            # Clean up any tracking parameters
            parsed = urlparse(url)
            clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            # Remove trailing slash
            return clean_url.rstrip("/")

    return None


async def scrape_raw(url: str, timeout: float = 10.0) -> str:
    """Fetch a URL with plain httpx + trafilatura (no Zenrows credits).

    Returns the extracted main-content text (≤8k chars), or empty
    string. Used by `backend/enrichment_worker.py` as the default bulk-
    pipeline scrape; Zenrows is only invoked as a block-bypass fallback.

    trafilatura is an optional dep — if it's not installed, fall back
    to the existing BeautifulSoup stripper so the worker still runs.
    """
    headers = {
        "User-Agent": (
            "Datasnoop/1.0 (+https://datasnoop.be; contact@datasnoop.be)"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "nl-BE,nl;q=0.9,fr-BE;q=0.8,en;q=0.7",
    }
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                logger.info("scrape_raw %s returned %s", url, resp.status_code)
                return ""
            html = resp.text or ""
    except httpx.TimeoutException:
        logger.info("scrape_raw timed out for %s", url)
        return ""
    except Exception as e:
        logger.info("scrape_raw failed for %s: %s", url, e)
        return ""

    try:
        import trafilatura  # type: ignore

        extracted = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=False,
            favor_precision=True,
        )
        if extracted:
            return extracted[:8000]
    except ImportError:
        logger.debug("trafilatura not installed, falling back to BeautifulSoup")
    except Exception as e:
        logger.debug("trafilatura extraction failed on %s: %s", url, e)

    return _strip_html(html, max_chars=8000)


async def scrape_company_site(url: str) -> tuple[str, str]:
    """Discovery-aware scrape entry-point used by the bulk worker.

    Returns (text, source) where source ∈ {'raw', 'zenrows', ''}. Tries
    the free raw path first; falls back to Zenrows basic proxy on
    empty/blocked response — the ~5% of sites that need proxy help per
    Phase 0 observation. Empty text with source='' means both paths
    failed.
    """
    text = await scrape_raw(url)
    if text and len(text) >= 200:
        return text, "raw"
    try:
        html = await scrape_url(url, js_render=False, premium_proxy=False)
        stripped = _strip_html(html, max_chars=8000) if html else ""
        if stripped and len(stripped) >= 200:
            return stripped, "zenrows"
    except Exception as e:
        logger.debug("Zenrows fallback failed for %s: %s", url, e)
    return "", ""


# Phase 5.2 — multi-page scrape used by the elaboration narrative path.
_MULTI_PAGE_PATHS = [
    "/about", "/about-us", "/over-ons", "/wie-zijn-wij", "/qui-sommes-nous",
    "/products", "/producten", "/services", "/diensten",
    "/team", "/contact",
    "/history", "/onze-geschiedenis", "/notre-histoire",
]


async def multi_page_scrape(base_url: str, timeout_s: float = 12.0) -> tuple[str, list[str]]:
    """Scrape homepage + a curated list of common subpages.

    Returns (concatenated_text, [paths_that_returned_content]). Used by the
    Phase 5.2 elaboration path to gather richer context than the bulk
    homepage-only scrape.
    """
    if not base_url:
        return "", []
    base_url = base_url.strip().rstrip("/")
    if not base_url.startswith("http"):
        base_url = "https://" + base_url
    urls = [base_url] + [base_url + p for p in _MULTI_PAGE_PATHS]

    async def _try(u: str) -> tuple[str, str]:
        try:
            text, _src = await asyncio.wait_for(scrape_company_site(u), timeout=timeout_s)
            return u, (text or "")
        except Exception:
            return u, ""

    results = await asyncio.gather(*[_try(u) for u in urls])
    seen_text: set[str] = set()
    chunks: list[str] = []
    pages_ok: list[str] = []
    for u, text in results:
        if not text or len(text) < 200:
            continue
        head = text[:200]
        if head in seen_text:
            continue
        seen_text.add(head)
        path = u[len(base_url):] or "/"
        chunks.append(f"=== {path} ===\n{text[:4000]}")
        pages_ok.append(path)
    return "\n\n".join(chunks), pages_ok


async def press_search(name: str, city: str | None = None, timeout_s: float = 8.0) -> str:
    """Best-effort DuckDuckGo press lookup for the elaboration path.

    Returns a `<press_snippets>...</press_snippets>` block ready to embed in
    a prompt, or "" on failure. No API key required.
    """
    if not name:
        return ""
    q = f'"{name}"'
    if city:
        q += f" {city}"
    q += " (overname OR fusie OR investering OR kapitaal OR raise OR acquires OR press)"
    try:
        async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
            r = await client.get("https://html.duckduckgo.com/html/", params={"q": q})
            if r.status_code != 200:
                return ""
            html = r.text
    except Exception:
        return ""
    snippets = re.findall(
        r'<a class="result__a"[^>]*>([^<]+)</a>.*?<a class="result__snippet"[^>]*>([^<]+)</a>',
        html, re.S,
    )
    if not snippets:
        snippets = [("", s) for s in re.findall(
            r'<a[^>]*class="result__snippet"[^>]*>([^<]+)</a>', html, re.S,
        )]
    items: list[str] = []
    for title, snippet in snippets[:5]:
        title = re.sub(r"\s+", " ", title).strip()
        snippet = re.sub(r"\s+", " ", snippet).strip()
        if not snippet:
            continue
        items.append(f"- {title}: {snippet}" if title else f"- {snippet}")
    if not items:
        return ""
    return "<press_snippets>\n" + "\n".join(items[:5]) + "\n</press_snippets>"


def slugify_company_name(name: str) -> str:
    """Convert a company name to a LinkedIn-style URL slug.

    E.g. 'Acme Solutions NV' -> 'acme-solutions-nv'
    """
    slug = name.lower().strip()
    # Remove common suffixes that LinkedIn often drops
    slug = re.sub(r"\b(bvba|bv|nv|sa|srl|sprl|cvba|cv)\b", "", slug).strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s-]+", "-", slug).strip("-")
    return slug
