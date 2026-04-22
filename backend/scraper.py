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

# ── DuckDuckGo rate-limit protection ──────────────────────────────────
# Phase 0 mini-spike (scripts/research/v3) observed DDG 403s after ~50
# sequential calls from one IP. The bulk worker calls
# `duckduckgo_search_url` twice per CBE (website + LinkedIn search), so
# at 400k no-web CBEs we'd hit the limit in minutes without throttling.
# 3 seconds between CALLS (not per CBE) is the Phase 0 recommendation.
# Overridable via env for tuning / local smoke tests.
DDG_MIN_INTERVAL_S = float(os.getenv("DDG_MIN_INTERVAL_S", "3.0"))
BING_FALLBACK_ENABLED = os.getenv("BING_FALLBACK_ENABLED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

_ddg_lock = asyncio.Lock()
_ddg_last_call: float = 0.0


async def _ddg_throttle() -> None:
    """Sleep until at least DDG_MIN_INTERVAL_S has elapsed since the last call.

    Shared across every async task in this process — the bulk worker runs
    concurrent jobs and a per-task sleep wouldn't actually rate-limit at
    the DDG origin. The lock serialises the wait window so two tasks can't
    both wake up and fire simultaneously.
    """
    global _ddg_last_call
    async with _ddg_lock:
        now = _time.monotonic()
        delta = now - _ddg_last_call
        if delta < DDG_MIN_INTERVAL_S:
            await asyncio.sleep(DDG_MIN_INTERVAL_S - delta)
        _ddg_last_call = _time.monotonic()


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
    """Scrape a URL via Zenrows. Returns HTML text.

    Parameters
    ----------
    url : str
        The target URL to scrape.
    js_render : bool
        Enable JavaScript rendering (needed for SPAs / LinkedIn).
    premium_proxy : bool
        Use premium residential proxies (needed for LinkedIn).
    """
    if not ZENROWS_KEY:
        logger.warning("ZENROWS_API_KEY not configured — skipping scrape")
        return ""

    params: dict[str, str] = {
        "apikey": ZENROWS_KEY,
        "url": url,
    }
    if js_render:
        params["js_render"] = "true"
    if premium_proxy:
        params["premium_proxy"] = "true"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                ZENROWS_BASE,
                params=params,
                timeout=60,
            )
            if resp.status_code == 200:
                logger.info("Scraped %s — %d bytes", url, len(resp.text))
                return resp.text
            logger.warning(
                "Zenrows returned %s for %s: %s",
                resp.status_code, url, resp.text[:300],
            )
    except Exception as e:
        logger.exception("Zenrows request failed for %s: %s", url, e)

    return ""


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
    website_query = f"{company_name}{location_part} {country} official website"
    await _ddg_throttle()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"https://html.duckduckgo.com/html/?q={_url_encode(website_query)}",
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                follow_redirects=True,
            )
            if resp.status_code == 200:
                website_url = _extract_best_website(resp.text, company_name)
            elif resp.status_code in (403, 429):
                logger.warning(
                    "DuckDuckGo rate-limited (%s) on website search for %s",
                    resp.status_code, company_name,
                )
    except Exception as e:
        logger.warning("DuckDuckGo website search failed for %s: %s", company_name, e)

    # ── Search for LinkedIn page ────────────────────────────────
    linkedin_query = f"{company_name}{location_part} site:linkedin.com/company"
    await _ddg_throttle()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"https://html.duckduckgo.com/html/?q={_url_encode(linkedin_query)}",
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                follow_redirects=True,
            )
            if resp.status_code == 200:
                linkedin_url = _extract_linkedin_url(resp.text)
            elif resp.status_code in (403, 429):
                logger.warning(
                    "DuckDuckGo rate-limited (%s) on LinkedIn search for %s",
                    resp.status_code, company_name,
                )
    except Exception as e:
        logger.warning("DuckDuckGo LinkedIn search failed for %s: %s", company_name, e)

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
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"https://html.duckduckgo.com/html/?q={_url_encode(website_query)}",
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                follow_redirects=True,
            )
            if resp.status_code == 200:
                return _extract_best_website(resp.text, company_name)
            if resp.status_code in (403, 429):
                ddg_rate_limited = True
                logger.warning(
                    "DuckDuckGo rate-limited (%s) on website search for %s",
                    resp.status_code, company_name,
                )
    except Exception as e:
        logger.warning("DuckDuckGo website search failed for %s: %s", company_name, e)
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
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"https://html.duckduckgo.com/html/?q={_url_encode(linkedin_query)}",
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                follow_redirects=True,
            )
            if resp.status_code == 200:
                return _extract_linkedin_url(resp.text)
            if resp.status_code in (403, 429):
                ddg_rate_limited = True
                logger.warning(
                    "DuckDuckGo rate-limited (%s) on LinkedIn search for %s",
                    resp.status_code, company_name,
                )
    except Exception as e:
        logger.warning("DuckDuckGo LinkedIn search failed for %s: %s", company_name, e)
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
    """Fetch a URL via Zenrows with a tight timeout. Returns HTML or empty string."""
    params: dict[str, str] = {
        "apikey": ZENROWS_KEY,
        "url": url,
    }
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                ZENROWS_BASE,
                params=params,
                timeout=timeout,
            )
            if resp.status_code == 200:
                return resp.text
            logger.warning(
                "Zenrows returned %s for Google search: %s",
                resp.status_code, resp.text[:200],
            )
    except httpx.TimeoutException:
        logger.warning("Zenrows Google search timed out after %ds for %s", timeout, url)
    except Exception as e:
        logger.warning("Zenrows Google search failed: %s", e)
    return ""


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
        name_slug = re.sub(r"[^a-z0-9]", "", company_name.lower())
        domain_slug = re.sub(r"[^a-z0-9]", "", domain.split(".")[0])

        # Strong signal: domain matches company name
        if name_slug and domain_slug and (
            name_slug in domain_slug or domain_slug in name_slug
        ):
            score += 10

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
