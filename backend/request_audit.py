"""Traffic attribution helpers for passive extraction monitoring.

The request path should stay cheap. DNS verification and nginx log parsing are
for offline ingestion only; FastAPI middleware only uses the lightweight UA and
origin helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from hashlib import sha256
from ipaddress import ip_address
from re import IGNORECASE, compile as re_compile
import socket
from typing import Mapping
from urllib.parse import parse_qs, urlsplit


BOT_RE = re_compile(
    r"bot|crawler|spider|slurp|facebookexternalhit|preview|lighthouse|"
    r"semrush|ahrefs|googlebot|googleother|bingbot|duckduckbot|yandex|"
    r"baidu|petalbot|gptbot|perplexity|claudebot|anthropic|ccbot|bytespider",
    flags=IGNORECASE,
)
MOBILE_RE = re_compile(r"android|iphone|ipod|mobile|opera mini", flags=IGNORECASE)
TABLET_RE = re_compile(r"ipad|tablet|kindle|silk", flags=IGNORECASE)
COMPANY_PAGE_RE = re_compile(r"^/company/(?P<cbe>\d{10})/?(?:\?(?P<query>.*))?$")
API_COMPANY_RE = re_compile(r"^/api/companies/(?P<cbe>\d{10})(?:/(?P<sub>[^?]+))?(?:\?.*)?$")
NGINX_ACCESS_RE = re_compile(
    r"^(?P<ip>\S+) \S+ \S+ \[(?P<ts>[^\]]+)\] "
    r'"(?P<method>\S+) (?P<path>\S+) (?P<proto>[^"]+)" '
    r"(?P<status>\d{3}) (?P<bytes>\d+|-) "
    r'"(?P<referrer>[^"]*)" "(?P<user_agent>[^"]*)"'
)

SEARCH_BOT_SUFFIXES = {
    "googlebot": ("googlebot.com", "google.com"),
    "googleother": ("googlebot.com", "google.com"),
    "bingbot": ("search.msn.com",),
}
AI_BOT_FAMILIES = {
    "gptbot",
    "perplexitybot",
    "claudebot",
    "anthropic",
    "ccbot",
    "bytespider",
}
CLOUD_NETWORK_MARKERS = (
    "amazonaws.com",
    "googleusercontent.com",
    "azure.com",
    "cloudapp.net",
    "digitalocean.com",
    "hetzner",
    "linode",
    "vultr",
    "ovh",
    "contabo",
    "scaleway",
)
ALLOWED_REQUEST_ORIGINS = {"direct", "next-ssr", "sitemap", "internal"}
SAME_SITE_REFERRER_HOSTS = {
    "datasnoop.be",
    "www.datasnoop.be",
    "datasnoop.eu",
    "www.datasnoop.eu",
    "datapeak.invm.be",
    "staging.datasnoop.be",
}


@dataclass(frozen=True)
class PublicRequestEvent:
    client_ip: str
    created_at: datetime
    method: str
    path: str
    request_target_hash: str
    status_code: int
    response_bytes: int
    referrer_path: str | None
    user_agent: str
    ua_family: str
    device_type: str
    bot_family: str | None
    is_ai_crawler: bool
    is_rsc_prefetch: bool
    route_kind: str
    cbe: str | None


def ua_family(user_agent: str) -> str:
    if not user_agent:
        return "unknown"
    if BOT_RE.search(user_agent):
        return "bot"
    ua_l = user_agent.lower()
    if "edg/" in ua_l or "edge/" in ua_l:
        return "edge"
    if "opr/" in ua_l or "opera" in ua_l:
        return "opera"
    if "firefox" in ua_l:
        return "firefox"
    if "chrome" in ua_l and "safari" in ua_l:
        return "chrome"
    if "safari" in ua_l:
        return "safari"
    return "other"


def device_type(user_agent: str) -> str:
    if not user_agent:
        return "unknown"
    if BOT_RE.search(user_agent):
        return "bot"
    if TABLET_RE.search(user_agent):
        return "tablet"
    if MOBILE_RE.search(user_agent):
        return "mobile"
    return "desktop"


def bot_family(user_agent: str) -> str | None:
    ua_l = (user_agent or "").lower()
    checks = (
        ("googleother", ("googleother",)),
        ("googlebot", ("googlebot",)),
        ("bingbot", ("bingbot",)),
        ("gptbot", ("gptbot",)),
        ("perplexitybot", ("perplexitybot", "perplexity")),
        ("claudebot", ("claudebot", "claude-web")),
        ("anthropic", ("anthropic",)),
        ("ccbot", ("ccbot", "commoncrawl")),
        ("bytespider", ("bytespider",)),
        ("duckduckbot", ("duckduckbot",)),
        ("yandex", ("yandex",)),
        ("ahrefs", ("ahrefs",)),
        ("semrush", ("semrush",)),
    )
    for family, needles in checks:
        if any(needle in ua_l for needle in needles):
            return family
    if BOT_RE.search(user_agent or ""):
        return "declared_bot"
    return None


def is_trusted_internal_client(client_ip: str | None) -> bool:
    if not client_ip:
        return False
    try:
        parsed = ip_address(client_ip)
    except ValueError:
        return False
    return parsed.is_private or parsed.is_loopback or parsed.is_link_local


def request_origin(headers: Mapping[str, str], client_ip: str | None = None) -> str:
    raw = (headers.get("x-datasnoop-request-origin") or "").strip().lower()
    if raw not in ALLOWED_REQUEST_ORIGINS:
        return "direct"
    if raw == "direct":
        return "direct"
    return raw if is_trusted_internal_client(client_ip) else "direct"


def sanitized_request_path(raw_path: str) -> str:
    parsed = urlsplit(raw_path or "")
    path = parsed.path or "/"
    if not path.startswith("/"):
        return "/"
    return path


def audit_public_path(headers: Mapping[str, str]) -> str | None:
    raw = (headers.get("x-datasnoop-public-path") or "").strip()
    if not raw or not raw.startswith("/") or len(raw) > 512:
        return None
    return sanitized_request_path(raw)[:512]


def route_kind_and_cbe(path: str) -> tuple[str, str | None, bool]:
    split = urlsplit(path)
    clean_path = split.path
    query = parse_qs(split.query)
    company = COMPANY_PAGE_RE.match(path) or COMPANY_PAGE_RE.match(clean_path)
    if company:
        return "company_page", company.group("cbe"), "_rsc" in query
    api_company = API_COMPANY_RE.match(path) or API_COMPANY_RE.match(clean_path)
    if api_company:
        sub = api_company.group("sub")
        kind = "api_company" if not sub else f"api_company_{sub.split('/')[0]}"
        return kind, api_company.group("cbe"), False
    if clean_path.startswith("/search"):
        return "search_page", None, "_rsc" in query
    if clean_path.startswith("/screener"):
        return "screener_page", None, "_rsc" in query
    if clean_path.startswith("/api/companies/search"):
        return "api_company_search", None, False
    if clean_path.startswith("/api/people/search"):
        return "api_people_search", None, False
    if clean_path.startswith("/api/"):
        return "api_other", None, False
    if clean_path.startswith("/_next/") or clean_path.startswith("/logos/"):
        return "asset", None, False
    return "other", None, "_rsc" in query


def referrer_path(referrer: str) -> str | None:
    if not referrer or referrer == "-":
        return None
    parsed = urlsplit(referrer)
    if not parsed.path:
        return None
    host = (parsed.hostname or "").lower()
    if host and host not in SAME_SITE_REFERRER_HOSTS:
        return "external"
    return sanitized_request_path(parsed.path)[:512]


def parse_nginx_access_line(line: str) -> PublicRequestEvent | None:
    match = NGINX_ACCESS_RE.match(line)
    if not match:
        return None
    raw = match.groupdict()
    try:
        created_at = datetime.strptime(raw["ts"], "%d/%b/%Y:%H:%M:%S %z")
    except ValueError:
        try:
            created_at = parsedate_to_datetime(raw["ts"])
        except Exception:
            return None

    raw_path = raw["path"]
    route_kind, cbe, is_rsc = route_kind_and_cbe(raw_path)
    ua = raw["user_agent"] or ""
    family = bot_family(ua)
    return PublicRequestEvent(
        client_ip=raw["ip"],
        created_at=created_at,
        method=raw["method"],
        path=sanitized_request_path(raw_path)[:1024],
        request_target_hash=sha256(raw_path.encode("utf-8", errors="replace")).hexdigest(),
        status_code=int(raw["status"]),
        response_bytes=0 if raw["bytes"] == "-" else int(raw["bytes"]),
        referrer_path=referrer_path(raw["referrer"]),
        user_agent=ua,
        ua_family=ua_family(ua),
        device_type=device_type(ua),
        bot_family=family,
        is_ai_crawler=family in AI_BOT_FAMILIES,
        is_rsc_prefetch=is_rsc,
        route_kind=route_kind,
        cbe=cbe,
    )


def hash_client_ip(ip: str, salt: str) -> str:
    digest = sha256((salt + (ip or "")).encode("utf-8")).hexdigest()
    return f"anon:{digest[:16]}"


def event_hash(event: PublicRequestEvent, salt: str) -> str:
    stable = "|".join(
        [
            salt,
            event.client_ip,
            event.created_at.isoformat(),
            event.method,
            event.path,
            event.request_target_hash,
            str(event.status_code),
            str(event.response_bytes),
            event.user_agent,
        ]
    )
    return sha256(stable.encode("utf-8")).hexdigest()


def network_label_from_ptr(ptr: str | None) -> str | None:
    if not ptr:
        return None
    labels = [part for part in ptr.strip(".").lower().split(".") if part]
    if len(labels) < 2:
        return ptr.lower()
    if labels[-2:] in (["googlebot", "com"], ["google", "com"]):
        return ".".join(labels[-2:])
    if len(labels) >= 3:
        return ".".join(labels[-3:])
    return ".".join(labels)


def verify_declared_bot(ip: str, family: str | None) -> tuple[bool, str | None]:
    if family not in SEARCH_BOT_SUFFIXES:
        return False, None
    try:
        ptr = socket.gethostbyaddr(ip)[0].rstrip(".").lower()
    except Exception:
        return False, None
    if not any(ptr.endswith(suffix) for suffix in SEARCH_BOT_SUFFIXES[family]):
        return False, network_label_from_ptr(ptr)
    try:
        forward_ips = {entry[4][0] for entry in socket.getaddrinfo(ptr, None)}
    except Exception:
        return False, network_label_from_ptr(ptr)
    return ip in forward_ips, network_label_from_ptr(ptr)


def client_type(
    event: PublicRequestEvent,
    *,
    verified_bot: bool,
    network_label: str | None,
) -> str:
    if verified_bot and event.bot_family in SEARCH_BOT_SUFFIXES:
        return "verified_search_bot"
    if event.is_ai_crawler:
        return "ai_crawler"
    if event.bot_family:
        return "declared_bot"
    label_l = (network_label or "").lower()
    if event.ua_family in {"chrome", "safari", "firefox", "edge", "opera"} and any(
        marker in label_l for marker in CLOUD_NETWORK_MARKERS
    ):
        return "cloud_browser"
    if event.ua_family in {"chrome", "safari", "firefox", "edge", "opera"}:
        return "browser"
    return "unknown"


def safe_ip(ip: str) -> bool:
    try:
        ip_address(ip)
        return True
    except ValueError:
        return False
