"""Datasnoop FastAPI backend — Company intelligence API."""

import hashlib
import logging
import os
import secrets
import time

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.background import BackgroundTask, BackgroundTasks
from starlette.middleware.base import BaseHTTPMiddleware

from routers import dashboard, screener, companies, stats, people, favourites, feedback, admin, polls, stripe_pay, staatsblad, tier_config, graveyard, me, bulk_import, changes, open_data, staatsblad_events, search, admin_enrichment, public_api, admin_phase22, clerk_webhook
from auth import ensure_jwks_bootstrapped
from rate_limit import limiter, get_client_ip, assert_single_worker_or_redis, RedisRateLimiter
from db import ensure_trgm_setup, ensure_phase22_schema
from middleware.cancel_watchdog import SearchCancelWatchdogMiddleware
from middleware.timing import TimingMiddleware, metrics_response
from request_audit import (
    audit_public_path,
    bot_family as classify_bot_family,
    request_origin,
)

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Anonymous client identifier hashing (GDPR)
# ---------------------------------------------------------------------------

_ACTIVITY_LOG_IP_SALT = os.getenv("ACTIVITY_LOG_IP_SALT")
if not _ACTIVITY_LOG_IP_SALT:
    _app_env = (os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "").lower()
    if _app_env == "production":
        raise RuntimeError(
            "ACTIVITY_LOG_IP_SALT must be set in production. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    _ACTIVITY_LOG_IP_SALT = secrets.token_hex(32)
    logger.warning(
        "ACTIVITY_LOG_IP_SALT is not set; using an ephemeral in-memory salt. "
        "Per-IP tier limit counts will reset on every restart. "
        "Set ACTIVITY_LOG_IP_SALT in the environment to make hashes stable."
    )


def _hash_client_id(ip: str) -> str:
    """Return a salted SHA-256 hash of a client IP, formatted as 'anon:<16-hex>'."""
    digest = hashlib.sha256((_ACTIVITY_LOG_IP_SALT + (ip or "")).encode()).hexdigest()
    return f"anon:{digest[:16]}"

app = FastAPI(
    title="Datasnoop API",
    description="Company intelligence — KBO registry + NBB annual accounts",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://datapeak.invm.be", "https://datasnoop.be", "https://datasnoop.eu", "https://www.datasnoop.be", "https://staging.datasnoop.be"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# ---------------------------------------------------------------------------
# LLM endpoint-attribution context middleware
# ---------------------------------------------------------------------------

class EndpointContextMiddleware(BaseHTTPMiddleware):
    """Stamp the current request path onto a contextvar read by ai_client.

    Lets every OpenRouter call made during request handling be attributed
    to the user-facing endpoint that triggered it (for the admin LLM
    cost panel). Reset in a finally so the contextvar never leaks across
    requests in the same worker.
    """

    async def dispatch(self, request: Request, call_next):
        from ai_client import set_current_endpoint, reset_current_endpoint
        token = set_current_endpoint(request.url.path)
        try:
            return await call_next(request)
        finally:
            reset_current_endpoint(token)


# ---------------------------------------------------------------------------
# Session-id middleware (GDPR-compliant)
# ---------------------------------------------------------------------------
# Sets a host-only `ds_sid` cookie carrying a random UUID. The value carries
# zero PII — it is only used to derive session-level metrics (session
# duration, pages/session, bounce rate, retention) by GROUP BY in the admin
# analytics queries. Cookie attributes:
#   - HttpOnly (no JS access — defends against XSS exfiltration)
#   - Secure (HTTPS only — set unconditionally; staging is HTTP-on-port-8080
#     but the operator only runs admin analytics from prod)
#   - SameSite=Lax (no cross-site attribution; required for OAuth flows)
#   - Path=/ (entire app)
#   - Max-Age 30 days (idle timeout = 30 min — see _session_idle_minutes)
# Documented in `docs/sessions.md`.

import re as _re
import uuid as _uuid

_SESSION_COOKIE = "ds_sid"
_SESSION_MAX_AGE_S = 30 * 24 * 3600  # 30 days hard ceiling

_BOT_RE = _re.compile(
    r"bot|crawler|spider|slurp|facebookexternalhit|preview|lighthouse|"
    r"semrush|ahrefs|googlebot|bingbot|duckduckbot|yandex|baidu|petalbot",
    _re.IGNORECASE,
)
_MOBILE_RE = _re.compile(r"android|iphone|ipod|mobile|opera mini", _re.IGNORECASE)
_TABLET_RE = _re.compile(r"ipad|tablet|kindle|silk", _re.IGNORECASE)


def _ua_family(ua: str) -> str:
    """Bucket a User-Agent into a coarse family. We never store the raw UA."""
    if not ua:
        return "unknown"
    if _BOT_RE.search(ua):
        return "bot"
    ua_l = ua.lower()
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


def _device_type(ua: str) -> str:
    if not ua:
        return "unknown"
    if _BOT_RE.search(ua):
        return "bot"
    if _TABLET_RE.search(ua):
        return "tablet"
    if _MOBILE_RE.search(ua):
        return "mobile"
    return "desktop"


class SessionMiddleware(BaseHTTPMiddleware):
    """Set a `ds_sid` cookie if the request doesn't already carry one.

    The cookie value is a random UUIDv4 — no PII, no fingerprinting.
    Stamps a `request.state.session_id` so downstream middleware (the
    activity log) can record it without having to re-parse cookies.
    """

    async def dispatch(self, request: Request, call_next):
        existing = request.cookies.get(_SESSION_COOKIE)
        is_new = not existing
        sid = existing or _uuid.uuid4().hex
        # Stash for downstream middleware/handlers.
        request.state.session_id = sid
        response = await call_next(request)
        if is_new:
            # Only set the cookie when we minted it. Re-setting on every
            # request would be wasteful (Set-Cookie header on every
            # response).
            #
            # Secure flag must follow the actual scheme. Production is
            # HTTPS (Secure=True); staging serves HTTP on port 8080
            # (Secure=False, otherwise the cookie is silently dropped by
            # the browser and analytics goes blank on staging).
            # X-Forwarded-Proto trumps url.scheme because nginx
            # terminates TLS in front of uvicorn.
            forwarded = (request.headers.get("x-forwarded-proto") or "").lower()
            scheme = forwarded or request.url.scheme
            response.set_cookie(
                key=_SESSION_COOKIE,
                value=sid,
                max_age=_SESSION_MAX_AGE_S,
                httponly=True,
                secure=(scheme == "https"),
                samesite="lax",
                path="/",
            )
        return response


# ---------------------------------------------------------------------------
# Activity logging middleware
# ---------------------------------------------------------------------------

class ActivityLogMiddleware(BaseHTTPMiddleware):
    # `/api/_auth/clerk-webhook` is a Svix-authed webhook (no Bearer token,
    # no user identity); logging it into activity_log would just be noise.
    SKIP_PATHS = ("/api/health", "/api/polls/active", "/api/dashboard", "/api/status/", "/api/_auth/clerk-webhook")
    # `/api/v1/*` (public API) has its own per-key audit log in
    # `api_call_log`; double-logging here would just bloat activity_log
    # without adding signal.
    SKIP_PREFIXES = ("/api/v1/",)

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if (
            path.startswith("/api/")
            and path not in self.SKIP_PATHS
            and not any(path.startswith(p) for p in self.SKIP_PREFIXES)
        ):
            auth_header = request.headers.get("authorization", "")
            client_ip = get_client_ip(request)
            sid = getattr(request.state, "session_id", None)
            ua_raw = request.headers.get("user-agent", "")
            country = (
                request.headers.get("cf-ipcountry", "") or ""
            ).strip().upper()[:2] or None
            method = request.method
            origin = request_origin(request.headers, client_ip=client_ip)
            public_path = audit_public_path(request.headers)

            def write_activity_log() -> None:
                from db import execute
                email = None
                if auth_header.startswith("Bearer "):
                    try:
                        from auth import _decode_token
                        payload = _decode_token(auth_header[7:])
                        email = payload.get("email")
                        if email:
                            execute(
                                "INSERT INTO user_roles (email, role) VALUES (%s, 'user') ON CONFLICT (email) DO NOTHING",
                                (email,),
                            )
                    except Exception:
                        logger.debug("ActivityLog token decode failed")

                # Log for both authenticated and anonymous users
                # Anonymous: store a salted hash of the IP, never the raw IP (GDPR)
                user_label = email or _hash_client_id(client_ip)
                # Pull session id + UA family stamped by SessionMiddleware /
                # request headers. UA is bucketed at insert time so the raw
                # string never lands in the database.
                ua_fam = _ua_family(ua_raw)
                device = _device_type(ua_raw)
                bot_fam = classify_bot_family(ua_raw)

                execute(
                    """
                    INSERT INTO activity_log
                        (user_email, endpoint, method, session_id, ua_family,
                         device_type, country_code, request_origin, public_path,
                         bot_family)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        user_label,
                        path,
                        method,
                        sid,
                        ua_fam,
                        device,
                        country,
                        origin,
                        public_path,
                        bot_fam,
                    ),
                )

            def safe_write_activity_log() -> None:
                try:
                    write_activity_log()
                except Exception:
                    logger.debug("ActivityLog insert failed", exc_info=True)

            existing_background = response.background
            if existing_background is None:
                response.background = BackgroundTask(safe_write_activity_log)
            else:
                tasks = BackgroundTasks()
                tasks.add_task(existing_background)
                tasks.add_task(safe_write_activity_log)
                response.background = tasks
        return response

# Middleware insertion order matters: Starlette runs middleware in REVERSE
# of registration. `add_middleware` prepends, so the LAST `add_middleware`
# call ends up OUTERMOST. We want SessionMiddleware to run first (so the
# session id is already set when ActivityLog reads it) — so register it
# LAST.
app.add_middleware(ActivityLogMiddleware)
app.add_middleware(EndpointContextMiddleware)
app.add_middleware(SessionMiddleware)

# ---------------------------------------------------------------------------
# Tier-based usage limit middleware
# ---------------------------------------------------------------------------

# Cache tier config in memory, refresh every 60 seconds
_tier_cache: dict = {}
_tier_cache_ts: float = 0.0
_TIER_CACHE_TTL = 60.0


def _get_tier_config() -> dict:
    """Return {tier_name: row_dict} from tier_config table, cached."""
    global _tier_cache, _tier_cache_ts
    now = time.time()
    if _tier_cache and (now - _tier_cache_ts) < _TIER_CACHE_TTL:
        return _tier_cache
    try:
        from db import fetch_all
        rows = fetch_all("SELECT * FROM tier_config")
        _tier_cache = {r["tier"]: r for r in rows}
        _tier_cache_ts = now
    except Exception:
        pass  # keep stale cache on error
    return _tier_cache


def _classify_endpoint(path: str) -> str | None:
    """Map an API path to a tier limit column name, or None if not limited.

    Operator policy (2026-04-17): only AI-burning endpoints (LLM calls,
    Zenrows scrapes) and explicit exports are tier-counted. Essential
    data — search, company profile views, NBB / Staatsblad filing fetch —
    is always unlimited, so free users never bounce off a "limit reached"
    wall on the basics. Cost protection on the essentials comes from the
    global per-IP rate limiter (200 req/min) + in-process per-CBE caches.
    """
    # AI bucket — every endpoint here costs money per call.
    if (
        ("/enrich" in path and "/enrichment" not in path)
        or "/ai-insights" in path
        or "/ai-commentary" in path
        or "/extract-admins" in path
        or "/scrape-" in path
        or "/summarize-publications" in path
        or "/similar/ai" in path
        or "/screener/nl" in path
        # Stage 3: /events/search calls OpenRouter for query embedding
        # on every request — bucket it with the AI endpoints so
        # anonymous abuse is bounded.  `/companies/{cbe}/events`
        # (non-search) is read-only DB and stays unlimited.
        or "/events/search" in path
        # Phase 1: /search/semantic calls OpenRouter for the query
        # embedding on cache miss (~$0.00002/call at 256 dims). Cap
        # anonymous + free-tier abuse at the AI bucket.
        or "/search/semantic" in path
    ):
        return "ai_enrichments_per_day"
    if (
        path.startswith("/api/people/search")
        or (path.startswith("/api/people/") and path.endswith("/connections"))
        or (path.startswith("/api/people/") and path.endswith("/enrichment"))
        or (path.startswith("/api/companies/") and path.endswith("/structure"))
        or (path.startswith("/api/companies/") and path.endswith("/network"))
        or (path.startswith("/api/companies/") and path.endswith("/deep-network"))
    ):
        return "searches_per_day"
    if "/export" in path:
        return "export_per_day"
    return None


# In-process TTL cache for TierLimitMiddleware. Key: (user_label, limit_type)
# → (expire_ts, count). See the middleware body for invalidation rules.
import time as _time_mod
_tier_count_cache: dict = {}

# Email → (expire_ts, tier_label). Populated when the role lookup runs in
# TierLimitMiddleware so authenticated users on tier-limited endpoints
# don't pay a `SELECT role FROM user_roles` round-trip every request.
# Roles change rarely (manual admin grant, Stripe webhook bumps a user
# to "pro"). 60s staleness is acceptable and matches the tier_config
# cache TTL right below this block. Capped at 10k entries — past that
# we drop the whole cache instead of doing LRU bookkeeping; a real
# multi-instance scenario should swap this for Redis.
_TIER_ROLE_TTL_S = 60.0
_TIER_ROLE_CACHE_MAX = 10_000
_tier_role_cache: dict[str, tuple[float, str]] = {}


def _ttl_now() -> float:
    return _time_mod.monotonic()


def _invalidate_tier_cache(user_label: str) -> None:
    """Call after an AI/export endpoint completes so the next tier check
    sees the fresh count. Cheap — just drops a few keys."""
    drop = [k for k in _tier_count_cache if k[0] == user_label]
    for k in drop:
        _tier_count_cache.pop(k, None)


def invalidate_tier_role_cache(email: str | None = None) -> None:
    """Drop a cached role for `email`, or wipe the whole cache when None.

    Stripe webhook + admin grant flows can call this after they bump a
    user's tier so the next request sees the new role without waiting
    for the 60s TTL to lapse.
    """
    if email is None:
        _tier_role_cache.clear()
        return
    _tier_role_cache.pop(email, None)


def _resolve_user_tier(email: str) -> str:
    """Resolve the tier label for an authenticated user, with a 60s cache.

    Returns 'premium' for pro/admin/premium roles, otherwise 'registered'.
    On any DB failure falls back to 'registered' — fail-open is safer than
    blocking a paying customer if the role lookup hiccups.
    """
    now = _ttl_now()
    cached = _tier_role_cache.get(email)
    if cached is not None and cached[0] > now:
        return cached[1]

    tier = "registered"
    try:
        from db import fetch_one
        row = fetch_one(
            "SELECT role FROM user_roles WHERE email = %s", (email,)
        )
        if row and row.get("role") in ("pro", "admin", "premium"):
            tier = "premium"
    except Exception:
        # Fail-open: if the lookup fails, assume registered. Logging is
        # already covered by db.py's exception path.
        pass

    if len(_tier_role_cache) > _TIER_ROLE_CACHE_MAX:
        _tier_role_cache.clear()
    _tier_role_cache[email] = (now + _TIER_ROLE_TTL_S, tier)
    return tier


class TierLimitMiddleware(BaseHTTPMiddleware):
    """Enforce daily usage limits per user tier (guest / registered / premium)."""

    SKIP_PATHS = ("/api/health", "/api/polls/active", "/api/dashboard", "/api/site-config", "/api/status/", "/api/_auth/clerk-webhook")
    # `/api/v1/*` is the customer-facing public API. It enforces its own
    # auth (API key) and its own caps (60/min + daily) so the user-tier
    # limiter doesn't apply.
    SKIP_PREFIXES = ("/api/v1/",)

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Only check API paths, skip static/admin/health
        if not path.startswith("/api/") or path in self.SKIP_PATHS:
            return await call_next(request)

        if any(path.startswith(p) for p in self.SKIP_PREFIXES):
            return await call_next(request)

        # Skip admin endpoints entirely
        if "/admin/" in path:
            return await call_next(request)

        # Only check GET-like reads + POST for enrichment/export
        limit_type = _classify_endpoint(path)
        if limit_type is None:
            return await call_next(request)

        # Load tier config; if not available or disabled, pass through
        tiers = _get_tier_config()
        if not tiers:
            return await call_next(request)

        # Check if any tier has enabled=True (master switch)
        any_enabled = any(t.get("enabled") for t in tiers.values())
        if not any_enabled:
            return await call_next(request)

        # Determine user tier. The role lookup goes through a 60s in-process
        # cache (see _resolve_user_tier) so authenticated traffic on
        # tier-limited endpoints doesn't pay the user_roles SELECT every
        # request. Stripe + admin-grant flows invalidate the cache on
        # role change.
        tier = "guest"
        email = None
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            try:
                from auth import _decode_token
                payload = _decode_token(auth[7:])
                email = payload.get("email")
                if email:
                    tier = _resolve_user_tier(email)
            except Exception:
                pass

        # Get the config for this tier
        tier_cfg = tiers.get(tier)
        if not tier_cfg or not tier_cfg.get("enabled"):
            return await call_next(request)

        # Get the limit for this endpoint type
        limit = tier_cfg.get(limit_type, -1)
        if limit is None or limit == -1:
            # -1 = unlimited
            return await call_next(request)
        if limit == 0:
            # 0 = feature disabled for this tier
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "limit_exceeded",
                    "tier": tier,
                    "limit_type": limit_type,
                    "limit": 0,
                    "used": 0,
                },
            )

        # Count today's usage from activity_log.
        #
        # PERF: small in-process TTL cache so we don't hit Postgres on every
        # single AI/export request for the same user. 30s TTL means the count
        # is at worst 30s stale — tier limits already accept "a few extras"
        # because the ActivityLogMiddleware inserts in a separate transaction.
        # Saves ~300ms per authenticated AI call at steady state.
        try:
            from db import fetch_one as db_fetch_one

            # Build the user label used in activity_log (must match ActivityLogMiddleware)
            user_label = email or _hash_client_id(get_client_ip(request))

            cache = _tier_count_cache
            now = _ttl_now()
            cache_key = (user_label, limit_type)
            cached = cache.get(cache_key)
            if cached is not None and cached[0] > now:
                used = cached[1]
            else:
                # Per the policy in `_classify_endpoint`, only AI and export
                # buckets reach this counter — searches and company views are
                # now unlimited at the tier layer.
                if limit_type == "ai_enrichments_per_day":
                    row = db_fetch_one(
                        """SELECT COUNT(*) AS cnt FROM activity_log
                           WHERE user_email = %s
                             AND (endpoint LIKE '%%/enrich%%'
                                  OR endpoint LIKE '%%/ai-insights%%'
                                  OR endpoint LIKE '%%/ai-commentary%%'
                                  OR endpoint LIKE '%%/extract-admins%%'
                                  OR endpoint LIKE '%%/scrape-%%'
                                  OR endpoint LIKE '%%/summarize-publications%%'
                                  OR endpoint LIKE '%%/similar/ai%%'
                                  OR endpoint LIKE '%%/screener/nl%%'
                                  OR endpoint LIKE '%%/events/search%%'
                                  OR endpoint LIKE '%%/search/semantic%%')
                             AND created_at >= CURRENT_DATE""",
                        (user_label,),
                    )
                elif limit_type == "export_per_day":
                    row = db_fetch_one(
                        """SELECT COUNT(*) AS cnt FROM activity_log
                           WHERE user_email = %s
                             AND endpoint LIKE '%%/export%%'
                             AND created_at >= CURRENT_DATE""",
                        (user_label,),
                    )
                elif limit_type == "searches_per_day":
                    row = db_fetch_one(
                        """SELECT COUNT(*) AS cnt FROM activity_log
                           WHERE user_email = %s
                             AND (
                                  endpoint LIKE '/api/people/search%%'
                                  OR endpoint LIKE '/api/people/%%/connections'
                                  OR endpoint LIKE '/api/people/%%/enrichment'
                                  OR endpoint LIKE '/api/companies/%%/structure'
                                  OR endpoint LIKE '/api/companies/%%/network'
                                  OR endpoint LIKE '/api/companies/%%/deep-network'
                             )
                             AND created_at >= CURRENT_DATE""",
                        (user_label,),
                    )
                else:
                    # Unknown bucket — pass through.
                    return await call_next(request)

                used = row["cnt"] if row else 0
                # Expire at now+30s. Cap cache at 5000 entries to prevent
                # unbounded growth on high-cardinality anon IPs.
                if len(cache) > 5000:
                    cache.clear()
                cache[cache_key] = (now + 30.0, used)

            if used >= limit:
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": "limit_exceeded",
                        "tier": tier,
                        "limit_type": limit_type,
                        "limit": limit,
                        "used": used,
                    },
                )
        except Exception:
            # If counting fails, don't block the request
            logger.exception("Tier limit check failed")

        return await call_next(request)


app.add_middleware(TierLimitMiddleware)


# ---------------------------------------------------------------------------
# Staging admin-only gate
# ---------------------------------------------------------------------------

class StagingGateMiddleware(BaseHTTPMiddleware):
    """When STAGING_MODE=true, restrict /api/* to users with role='admin'.

    Purpose: staging is wired to the same Supabase project as prod so we
    can test with real logins, but we don't want regular users landing
    on the staging URL and seeing half-broken features. Anyone who's not
    a listed admin gets HTTP 403 with ``detail='staging_admin_only'``;
    the frontend's StagingGate component renders a friendly blocker
    based on that response.

    Allowlisted paths are kept to the minimum needed so the blocker UI
    can render without exposing any app data:
      /api/health — Docker healthcheck, must succeed without auth
      /api/me/is-admin — the frontend probe that decides whether to show
        the blocker. Callable by anyone (signed in or not) — the endpoint
        itself returns a safe payload with is_admin=false when there's
        no session.

    Notably NOT on the allowlist: /api/site-config, /api/polls/active,
    /api/dashboard, /api/sitemap/*. On staging we block those too, so
    anonymous visitors can't load any data — the only page they'll see
    is the admin-only blocker.

    This middleware is disabled entirely when STAGING_MODE is unset or
    "false", so production is untouched.
    """

    ALLOWLIST_EXACT = {
        "/api/health",
        "/api/me/is-admin",
        # Clerk webhook is auth-exempt (Svix signature is the auth). Must be
        # reachable on staging during Phase 1c webhook smoke-test.
        "/api/_auth/clerk-webhook",
    }
    # `/api/v1/*` is the customer-facing public API. Auth is by API key
    # (independent of the Supabase login this gate checks for). On staging
    # we want operators / pilot customers to be able to smoke-test it
    # without an admin Supabase login, so allowlist the whole prefix —
    # the API key requirement still holds inside the router itself.
    ALLOWLIST_PREFIXES = ("/api/sitemap/", "/api/v1/")
    # Regex patterns — dynamic paths we want anonymously accessible on staging.
    # Keep surgical: only the specific read endpoints used by the public
    # /demo/valuation/[cbe] page, so demo links can be shared externally.
    import re as _re
    ALLOWLIST_PATTERNS = (
        _re.compile(r"^/api/companies/\d{10}$"),              # company detail
        _re.compile(r"^/api/companies/\d{10}/valuation$"),    # valuation data
    )

    def __init__(self, app):
        super().__init__(app)
        self.enabled = (os.getenv("STAGING_MODE", "").lower() in ("1", "true", "yes"))

    async def dispatch(self, request: Request, call_next):
        if not self.enabled:
            return await call_next(request)

        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)
        if (
            path in self.ALLOWLIST_EXACT
            or any(path.startswith(p) for p in self.ALLOWLIST_PREFIXES)
            or any(pat.match(path) for pat in self.ALLOWLIST_PATTERNS)
        ):
            return await call_next(request)

        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "staging_admin_only", "reason": "unauthenticated"},
            )

        try:
            from auth import _decode_token
            payload = _decode_token(auth[7:])
            email = payload.get("email")
        except Exception:
            return JSONResponse(
                status_code=401,
                content={"detail": "staging_admin_only", "reason": "invalid_token"},
            )

        if not email:
            return JSONResponse(
                status_code=401,
                content={"detail": "staging_admin_only", "reason": "no_email"},
            )

        try:
            from db import fetch_one as db_fetch_one
            role_row = db_fetch_one(
                "SELECT role FROM user_roles WHERE email = %s", (email,),
            )
        except Exception:
            # If the role lookup fails in an unexpected way, fail closed on
            # staging — we'd rather block than leak.
            logger.exception("StagingGate role lookup failed")
            return JSONResponse(
                status_code=503,
                content={"detail": "staging_admin_only", "reason": "role_lookup_failed"},
            )

        if not role_row or role_row.get("role") != "admin":
            return JSONResponse(
                status_code=403,
                content={"detail": "staging_admin_only", "reason": "not_admin"},
            )

        return await call_next(request)


app.add_middleware(StagingGateMiddleware)


# ---------------------------------------------------------------------------
# Rate limiting middleware
# ---------------------------------------------------------------------------

class BotFilterMiddleware(BaseHTTPMiddleware):
    """Block known scraper/bot User-Agents from API endpoints.

    Allows: empty UA (healthchecks), python-requests (internal), Datasnoop UA.
    Blocks: scrapy, wget, headless browsers, etc.
    """

    BLOCKED_UA_SUBSTRINGS = (
        "scrapy", "go-http-client", "wget",
        "httpclient", "libwww", "lwp-trivial", "slimerjs",
        "phantomjs", "headlesschrome", "selenium",
    )
    # `/api/v1/*` is server-to-server — Go HTTP clients, libcurl, etc.
    # are legitimate consumers. Auth is by API key, so we don't need
    # UA-based gating here.
    # `/api/_auth/clerk-webhook` is server-to-server (Clerk → us); the
    # Svix signature is the auth, no UA-based bot heuristics apply.
    SKIP_PATHS = ("/api/health", "/api/sitemap/", "/api/status/", "/api/v1/", "/api/_auth/clerk-webhook")

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/") and not any(path.startswith(s) for s in self.SKIP_PATHS):
            ua = (request.headers.get("user-agent") or "").lower()
            if ua and any(bot in ua for bot in self.BLOCKED_UA_SUBSTRINGS):
                return JSONResponse(status_code=403, content={"detail": "Forbidden"})
        return await call_next(request)


app.add_middleware(BotFilterMiddleware)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting keyed by authenticated user email or client IP."""

    SEARCH_PATHS = (
        "/api/companies/search",
        "/api/companies/semantic-search",
        "/api/people/search",
        # V2 autocomplete — one DB round-trip per keystroke. Keep it in
        # the tighter per-IP bucket so the anonymous path is bounded.
        "/api/search/suggest",
    )
    PII_READ_SUFFIXES = ("/connections", "/enrichment", "/structure", "/network", "/deep-network")

    def _get_rate_key(self, request: Request) -> str:
        """Get rate limit key: prefer auth user email, fall back to real IP."""
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            try:
                from auth import _decode_token
                payload = _decode_token(auth[7:])
                email = payload.get("email")
                if email:
                    return f"user:{email}"
            except Exception:
                pass
        return f"ip:{get_client_ip(request)}"

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method

        if not path.startswith("/api/"):
            return await call_next(request)

        # Clerk webhook is server-to-server with Svix retries — IP-rate-limiting
        # it would just turn transient 429s into Svix retry storms. Auth is the
        # Svix signature inside the handler.
        if path == "/api/_auth/clerk-webhook":
            return await call_next(request)

        # `/api/v1/*` (public API) is keyed by API key, not by JWT/IP.
        # The auth dependency enforces 60/min per key + a daily cap.
        # However, both `require_api_key` (DB lookup on every call) and
        # `/api/v1/health` (no auth) are exposed to the public internet.
        # Without *some* IP-level floor an attacker could flood the
        # public-API surface with no key at all and overload the auth
        # lookup. Apply a generous per-IP cap (600/min) here — high
        # enough that legitimate webshop traffic from a single egress IP
        # never hits it, low enough to bound unauthenticated abuse.
        if path.startswith("/api/v1/"):
            try:
                limiter.check(
                    f"ip:{get_client_ip(request)}:apiv1",
                    max_requests=600,
                    window_seconds=60,
                )
            except Exception as e:
                return JSONResponse(
                    status_code=429,
                    content={"detail": str(e.detail) if hasattr(e, "detail") else "Rate limit exceeded"},
                )
            return await call_next(request)

        key = self._get_rate_key(request)

        try:
            # Search/PII-heavy endpoints: 60/min per user
            if (
                any(path.startswith(p) for p in self.SEARCH_PATHS)
                or (
                    (path.startswith("/api/people/") or path.startswith("/api/companies/"))
                    and path.endswith(self.PII_READ_SUFFIXES)
                )
            ):
                limiter.check(key, max_requests=60, window_seconds=60)
            # All other API calls: 200/min per user
            else:
                limiter.check(key, max_requests=200, window_seconds=60)
        except Exception as e:
            return JSONResponse(status_code=429, content={"detail": str(e.detail) if hasattr(e, "detail") else "Rate limit exceeded"})

        return await call_next(request)

app.add_middleware(RateLimitMiddleware)
app.add_middleware(SearchCancelWatchdogMiddleware)
app.add_middleware(TimingMiddleware)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(dashboard.router)
app.include_router(screener.router)
app.include_router(screener.sitemap_router)
app.include_router(companies.router)
app.include_router(stats.router)
app.include_router(people.router)
app.include_router(favourites.router)
app.include_router(feedback.router)
app.include_router(admin.router)
app.include_router(polls.router)
app.include_router(stripe_pay.router)
app.include_router(staatsblad.router)
app.include_router(tier_config.router)
app.include_router(graveyard.router)
app.include_router(me.router)
app.include_router(bulk_import.router)
app.include_router(changes.router)
app.include_router(open_data.router)
app.include_router(staatsblad_events.router)
app.include_router(search.router)
app.include_router(admin_enrichment.router)
app.include_router(admin_phase22.router)
app.include_router(public_api.router)
app.include_router(clerk_webhook.router)

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "datasnoop-api"}


@app.get("/metrics", include_in_schema=False)
async def prometheus_metrics(_user=Depends(admin._require_admin)):
    return metrics_response()


@app.get("/api/status/metrics")
async def status_metrics():
    """Public operator-visible pipeline metrics for the /status page.

    Three services:
      - NBB financials loader (financial_data + financial_latest)
      - Staatsblad event loader (staatsblad_event)
      - Semantic enrichment worker (enrichment_job queue)

    Queries are lightweight (approximate counts via pg_class,
    date-bucketed totals, and a tiny aggregate on enrichment_job).
    No auth required — everything here is aggregate, no PII.
    """
    from db import fetch_one, fetch_all

    out: dict = {"nbb": None, "staatsblad": None, "semantic": None}

    try:
        # financial_data has no insert timestamp — the deposit_date is
        # the filing date (NBB publishes T+~3 months). Use MAX(fiscal_year)
        # as "latest fiscal year ingested" and COUNT companies with a
        # non-null latest row as coverage.
        # financial_data.deposit_date is stored as TEXT (NBB returns
        # ISO-8601 strings); cast explicitly before comparing to date.
        nbb = fetch_one(
            """
            SELECT
              (SELECT MAX(deposit_date) FROM financial_data)  AS latest_deposit_date,
              (SELECT MAX(fiscal_year) FROM financial_data)   AS latest_fiscal_year,
              (SELECT COUNT(*) FROM financial_data
                 WHERE deposit_date::date > CURRENT_DATE - INTERVAL '1 day') AS rows_last_24h,
              (SELECT COUNT(DISTINCT enterprise_number) FROM financial_latest) AS companies_covered
            """
        )
        out["nbb"] = {
            "latest_deposit_date": str(nbb["latest_deposit_date"]) if nbb and nbb.get("latest_deposit_date") else None,
            "latest_fiscal_year": int(nbb["latest_fiscal_year"]) if nbb and nbb.get("latest_fiscal_year") else None,
            "rows_last_24h": int(nbb["rows_last_24h"] or 0) if nbb else 0,
            "companies_covered": int(nbb["companies_covered"] or 0) if nbb else 0,
        }
    except Exception:
        logger.exception("status_metrics: nbb query failed")

    try:
        sb = fetch_one(
            """
            SELECT
              (SELECT MAX(pub_date) FROM staatsblad_event) AS last_event_pub,
              (SELECT MAX(extracted_at) FROM staatsblad_event) AS last_extracted_at,
              (SELECT COUNT(*) FROM staatsblad_event
                 WHERE extracted_at > NOW() - INTERVAL '24 hours') AS events_extracted_24h,
              (SELECT COUNT(DISTINCT enterprise_number) FROM staatsblad_event) AS companies_covered
            """
        )
        out["staatsblad"] = {
            "last_event_pub": str(sb["last_event_pub"]) if sb and sb.get("last_event_pub") else None,
            "last_extracted_at": str(sb["last_extracted_at"]) if sb and sb.get("last_extracted_at") else None,
            "events_extracted_24h": int(sb["events_extracted_24h"] or 0) if sb else 0,
            "companies_covered": int(sb["companies_covered"] or 0) if sb else 0,
        }
    except Exception:
        logger.exception("status_metrics: staatsblad query failed")

    try:
        sem_rows = fetch_all(
            "SELECT status, COUNT(*)::bigint AS n FROM enrichment_job GROUP BY status"
        )
        by_status: dict[str, int] = {str(r["status"]): int(r["n"]) for r in sem_rows}
        last_done = fetch_one(
            "SELECT MAX(finished_at) AS last_done FROM enrichment_job WHERE status = 'done'"
        )
        # Actual enrichment_job statuses: 'queued', 'claimed', 'done',
        # 'excluded', 'error'. Map them onto the operator-facing labels.
        out["semantic"] = {
            "queue": by_status,
            "last_done_at": str(last_done["last_done"]) if last_done and last_done.get("last_done") else None,
            "pending": int(by_status.get("queued", 0)) + int(by_status.get("pending", 0)),
            "running": int(by_status.get("claimed", 0)) + int(by_status.get("running", 0)) + int(by_status.get("in_progress", 0)),
            "done": int(by_status.get("done", 0)),
            "excluded": int(by_status.get("excluded", 0)),
            "error": int(by_status.get("error", 0)) + int(by_status.get("failed", 0)),
        }
    except Exception:
        logger.exception("status_metrics: semantic query failed")

    return out


@app.get("/api/site-config")
async def public_site_config():
    """Public endpoint returning site configuration (logo path, etc.)."""
    from db import fetch_one
    try:
        row = fetch_one("SELECT value FROM meta WHERE variable = 'site_logo'")
        return {"site_logo": row["value"] if row else "/logos/dog-telescope.jpg"}
    except Exception:
        return {"site_logo": "/logos/dog-telescope.jpg"}


# ---------------------------------------------------------------------------
# Startup: run migrations
# ---------------------------------------------------------------------------


@app.on_event("startup")
async def startup_migrations():
    """Run idempotent database migrations on startup."""
    try:
        ensure_trgm_setup()
    except Exception:
        logger.exception("pg_trgm startup migration failed (non-fatal)")
    try:
        # Phase-22 schema (sessions on activity_log, invoice taxonomy
        # depth, vendor-pattern table). Independent of trgm/V2 detection
        # so it always runs.
        ensure_phase22_schema()
    except Exception:
        logger.exception("Phase-22 schema migration failed (non-fatal)")


@app.on_event("startup")
async def startup_rate_limiter():
    """Verify rate limiter is safe for the current worker configuration."""
    assert_single_worker_or_redis()
    backend = "redis" if isinstance(limiter, RedisRateLimiter) else "in-memory"
    logger.info("Rate limiter backend: %s", backend)


@app.on_event("startup")
async def startup_jwks_bootstrap():
    """Fail fast at startup if the Supabase JWKS cannot be fetched.

    Without JWKS we cannot verify production JWTs; refusing to start surfaces
    the config error at boot instead of flooding /api/* with 401s at runtime.
    The helper is HS256-aware: in HS256-only dev/legacy envs it logs a warning
    and lets startup proceed.
    """
    ensure_jwks_bootstrapped()


@app.on_event("startup")
async def startup_phase1_migrations():
    """Run Phase 1 semantic-enrichment migrations (idempotent).

    Adds `bulk_*` columns to `company_enrichment`, creates the
    `enrichment_job`, `query_embedding_cache`, and `aggregator_skiplist`
    tables, and seeds the skip-list. Each step is a no-op on subsequent
    runs — see `src/schema.sql` for the canonical DDL.
    """
    try:
        from enrichment_queue import ensure_schema as ensure_queue
        ensure_queue()
    except Exception:
        logger.exception("enrichment_job migration failed (non-fatal)")


@app.on_event("startup")
async def startup_search_prewarm():
    """Pre-warm /api/companies/search and /api/people/search caches with
    the most-clicked recent terms so the first user-facing query of the
    day doesn't pay the cold-cache cost. ~50 queries × 2 endpoints
    against an already-running DB takes a few seconds in the background
    and never blocks request handling. Failures are silently ignored —
    this is a perf nicety, not a correctness path.
    """
    import asyncio

    async def _prewarm() -> None:
        try:
            from db import fetch_all
            from routers.companies.search import _search_companies_cached
            from routers.people import _search_people_cached
            # Top names by 28-day click count from `company_popularity` —
            # already a materialised lookup that the search scoring uses.
            rows = fetch_all(
                "SELECT ci.name FROM company_popularity cp "
                "JOIN company_info ci ON ci.enterprise_number = cp.enterprise_number "
                "WHERE ci.name IS NOT NULL AND length(ci.name) >= 3 "
                "ORDER BY cp.click_count DESC LIMIT 50"
            )
            seen: set[str] = set()
            warmed = 0
            for r in rows or []:
                name = (r.get("name") or "").strip().lower()
                if not name or name in seen:
                    continue
                seen.add(name)
                try:
                    _search_companies_cached(name, 20, None, None, None)
                    _search_people_cached(name)
                    warmed += 1
                except Exception:
                    continue
            logger.info("search cache pre-warmed: %d terms", warmed)
        except Exception:
            logger.exception("search pre-warm skipped (non-fatal)")

    # Fire-and-forget. The first user-facing request still works even
    # if pre-warm hasn't completed yet — they just hit cold cache once.
    asyncio.create_task(_prewarm())


@app.on_event("startup")
async def startup_search_v2_cache():
    """Load search V2 synonym cache from `legal_form_synonyms`.

    The table is populated by migrations/2026-04-24_search_v2.sql. If
    that migration hasn't run yet, we silently degrade — search still
    works, just without legal-form alias expansion.
    """
    try:
        from db import fetch_all
        from search_normalization import set_synonyms_cache
        rows = fetch_all("SELECT form, canonical FROM legal_form_synonyms")
        set_synonyms_cache({r["form"]: r["canonical"] for r in rows})
        logger.info("search V2 synonym cache loaded: %d entries", len(rows))
    except Exception:
        # Migration not applied yet or table missing — non-fatal.
        logger.info("search V2 synonym cache not available (migration not applied?)")

    try:
        from embeddings import _ensure_query_embedding_cache
        _ensure_query_embedding_cache()
    except Exception:
        logger.exception("query_embedding_cache migration failed (non-fatal)")

    try:
        from db import execute as db_execute
        # Seed with Phase 0 aggregator findings. ON CONFLICT DO NOTHING
        # keeps this idempotent — operator-added patterns survive, seed
        # rows are only inserted when missing.
        _skiplist_seeds = [
            ("pappers.be",           "domain", "seed: KBO aggregator"),
            ("bsearch.be",           "domain", "seed: business directory"),
            ("handelsgids.be",       "domain", "seed: business directory"),
            ("infobel.be",           "domain", "seed: directory"),
            ("immoweb.be",           "domain", "seed: real-estate listing"),
            ("lemariagedelouise.be", "domain", "seed: wedding-vendor listing"),
            ("economie.fgov.be",     "domain", "seed: KBO portal"),
            ("kompass.com",          "domain", "seed: B2B directory"),
            ("europages.com",        "domain", "seed: B2B directory"),
            ("dnb.com",              "domain", "seed: credit directory"),
            ("companyweb.be",        "domain", "seed: directory"),
            ("staatsbladmonitor.be", "domain", "seed: gazette mirror"),
            ("trends.knack.be",      "domain", "seed: press directory"),
            ("/bedrijvengids/",      "path",   "seed: municipal business index"),
            ("/annuaire/",           "path",   "seed: FR municipal directory"),
            ("/infrastructuur-",     "path",   "seed: municipal infrastructure"),
        ]
        for pattern, kind, reason in _skiplist_seeds:
            try:
                db_execute(
                    "INSERT INTO aggregator_skiplist "
                    "(pattern, kind, reason, added_by) "
                    "VALUES (%s, %s, %s, 'seed') "
                    "ON CONFLICT (pattern, kind) DO NOTHING",
                    (pattern, kind, reason),
                )
            except Exception:
                logger.debug("skiplist seed row %s skipped", pattern)
    except Exception:
        logger.exception("aggregator_skiplist seed failed (non-fatal)")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    reload = os.getenv("API_RELOAD", "false").lower() == "true"
    uvicorn.run("main:app", host=host, port=port, reload=reload)
