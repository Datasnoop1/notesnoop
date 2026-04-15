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
