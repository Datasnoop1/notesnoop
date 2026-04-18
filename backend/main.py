"""Datasnoop FastAPI backend — Belgian company intelligence API."""

import hashlib
import logging
import os
import secrets
import time

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from routers import dashboard, screener, companies, stats, people, favourites, feedback, admin, polls, stripe_pay, staatsblad, tier_config, graveyard, me, bulk_import, changes, open_data, staatsblad_events
from rate_limit import limiter, get_client_ip, assert_single_worker_or_redis, RedisRateLimiter
from db import ensure_trgm_setup

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
    description="Belgian company intelligence — KBO registry + NBB annual accounts",
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
# Activity logging middleware
# ---------------------------------------------------------------------------

class ActivityLogMiddleware(BaseHTTPMiddleware):
    SKIP_PATHS = ("/api/health", "/api/polls/active", "/api/dashboard")

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/api/") and path not in self.SKIP_PATHS:
            try:
                from db import execute
                email = None
                auth = request.headers.get("authorization", "")
                if auth.startswith("Bearer "):
                    try:
                        from auth import _decode_token
                        payload = _decode_token(auth[7:])
                        email = payload.get("email")
                        if email:
                            execute(
                                "INSERT INTO user_roles (email, role) VALUES (%s, 'user') ON CONFLICT (email) DO NOTHING",
                                (email,),
                            )
                    except Exception:
                        pass

                # Log for both authenticated and anonymous users
                # Anonymous: store a salted hash of the IP, never the raw IP (GDPR)
                user_label = email or _hash_client_id(get_client_ip(request))
                execute(
                    "INSERT INTO activity_log (user_email, endpoint, method) VALUES (%s, %s, %s)",
                    (user_label, path, request.method),
                )
            except Exception:
                pass
        return response

app.add_middleware(ActivityLogMiddleware)
app.add_middleware(EndpointContextMiddleware)

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
    ):
        return "ai_enrichments_per_day"
    if "/export" in path:
        return "export_per_day"
    return None


# In-process TTL cache for TierLimitMiddleware. Key: (user_label, limit_type)
# → (expire_ts, count). See the middleware body for invalidation rules.
import time as _time_mod
_tier_count_cache: dict = {}


def _ttl_now() -> float:
    return _time_mod.monotonic()


def _invalidate_tier_cache(user_label: str) -> None:
    """Call after an AI/export endpoint completes so the next tier check
    sees the fresh count. Cheap — just drops a few keys."""
    drop = [k for k in _tier_count_cache if k[0] == user_label]
    for k in drop:
        _tier_count_cache.pop(k, None)


class TierLimitMiddleware(BaseHTTPMiddleware):
    """Enforce daily usage limits per user tier (guest / registered / premium)."""

    SKIP_PATHS = ("/api/health", "/api/polls/active", "/api/dashboard", "/api/site-config")

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Only check API paths, skip static/admin/health
        if not path.startswith("/api/") or path in self.SKIP_PATHS:
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

        # Determine user tier
        tier = "guest"
        email = None
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            try:
                from auth import _decode_token
                payload = _decode_token(auth[7:])
                email = payload.get("email")
                if email:
                    tier = "registered"
                    # Check for premium role
                    try:
                        from db import fetch_one
                        role_row = fetch_one(
                            "SELECT role FROM user_roles WHERE email = %s", (email,)
                        )
                        if role_row and role_row["role"] in ("pro", "admin", "premium"):
                            tier = "premium"
                    except Exception:
                        pass
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
                                  OR endpoint LIKE '%%/screener/nl%%')
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
            pass

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
    }
    ALLOWLIST_PREFIXES = ("/api/sitemap/",)
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
    SKIP_PATHS = ("/api/health", "/api/sitemap/")

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

    SEARCH_PATHS = ("/api/companies/search", "/api/companies/semantic-search", "/api/people/search")

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

        key = self._get_rate_key(request)

        try:
            # Search endpoints: 60/min per user
            if any(path.startswith(p) for p in self.SEARCH_PATHS):
                limiter.check(key, max_requests=60, window_seconds=60)
            # All other API calls: 200/min per user
            else:
                limiter.check(key, max_requests=200, window_seconds=60)
        except Exception as e:
            return JSONResponse(status_code=429, content={"detail": str(e.detail) if hasattr(e, "detail") else "Rate limit exceeded"})

        return await call_next(request)

app.add_middleware(RateLimitMiddleware)

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

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "datasnoop-api"}


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


@app.on_event("startup")
async def startup_rate_limiter():
    """Verify rate limiter is safe for the current worker configuration."""
    assert_single_worker_or_redis()
    backend = "redis" if isinstance(limiter, RedisRateLimiter) else "in-memory"
    logger.info("Rate limiter backend: %s", backend)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    reload = os.getenv("API_RELOAD", "false").lower() == "true"
    uvicorn.run("main:app", host=host, port=port, reload=reload)
