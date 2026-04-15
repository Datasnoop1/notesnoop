"""Zenrows web scraper for company enrichment.

Provides async helpers to scrape company websites and LinkedIn profiles
via the Zenrows proxy API, then extract structured data with AI.
"""

import os
import logging
import re

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

ZENROWS_KEY = os.getenv("ZENROWS_API_KEY", "")
ZENROWS_BASE = "https://api.zenrows.com/v1/"


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
    company_name: str, city: str = "", country: str = "Belgium"
) -> dict:
    """Search DuckDuckGo for a company's website and LinkedIn page.

    Free, no API key, no rate limits. Primary search method.
    Returns: {"website_url": str|None, "linkedin_url": str|None}
    """
    location_part = f" {city}" if city else ""
    website_url = None
    linkedin_url = None

    # ── Search for company website ──────────────────────────────
    website_query = f"{company_name}{location_part} {country} official website"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"https://html.duckduckgo.com/html/?q={_url_encode(website_query)}",
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                follow_redirects=True,
            )
            if resp.status_code == 200:
                website_url = _extract_best_website(resp.text, company_name)
    except Exception as e:
        logger.warning("DuckDuckGo website search failed for %s: %s", company_name, e)

    # ── Search for LinkedIn page ────────────────────────────────
    linkedin_query = f"{company_name}{location_part} site:linkedin.com/company"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"https://html.duckduckgo.com/html/?q={_url_encode(linkedin_query)}",
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                follow_redirects=True,
            )
            if resp.status_code == 200:
                linkedin_url = _extract_linkedin_url(resp.text)
    except Exception as e:
        logger.warning("DuckDuckGo LinkedIn search failed for %s: %s", company_name, e)

    logger.info(
        "DuckDuckGo search for '%s': website=%s, linkedin=%s",
        company_name, website_url or "(none)", linkedin_url or "(none)",
    )
    return {"website_url": website_url, "linkedin_url": linkedin_url}


async def zenrows_search_url(
    company_name: str, city: str = "", country: str = "Belgium"
) -> dict:
    """Search Google via Zenrows for a company's website and LinkedIn page.

    Used as a RETRY fallback when DuckDuckGo results were flagged wrong by users.
    Costs Zenrows credits — only use on second attempts.
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


# Domains to skip when extracting website URLs from Google results
_SKIP_DOMAINS = {
    "google.com", "google.be", "gstatic.com", "googleapis.com",
    "wikipedia.org", "facebook.com", "twitter.com", "instagram.com",
    "youtube.com", "tiktok.com", "pinterest.com", "reddit.com",
    "linkedin.com",  # LinkedIn handled separately
    "yelp.com", "tripadvisor.com", "trustpilot.com",
    "staatsbladmonitor.be", "companyweb.be", "trends.knack.be",
    "kompass.com", "europages.com", "dnb.com",
}


def _extract_best_website(html: str, company_name: str) -> str | None:
    """Parse search results HTML (DuckDuckGo or Google) and return the best company website URL.

    Skips social media, Wikipedia, aggregator sites.
    Prefers .be domains and domains that resemble the company name.
    """
    from bs4 import BeautifulSoup
    from urllib.parse import urlparse, parse_qs, unquote

    soup = BeautifulSoup(html, "html.parser")
    candidates: list[tuple[str, int]] = []  # (url, priority_score)

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

        # Parse the domain
        try:
            domain = urlparse(url).netloc.lower().lstrip("www.")
        except Exception:
            continue

        # Skip known non-company domains
        if any(skip in domain for skip in _SKIP_DOMAINS):
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
