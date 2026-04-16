"""Simple in-memory rate limiter for FastAPI.

Uses a sliding window counter per IP address. No external dependencies.
Designed for single-process deployments (which Datasnoop uses).

If REDIS_URL is set, a Redis-backed fixed-window limiter is used instead,
which is safe across multiple workers.
"""

import logging
import os
import time
import threading
from collections import defaultdict
from fastapi import Request, HTTPException

try:
    import redis  # type: ignore
except ImportError:
    redis = None  # type: ignore


logger = logging.getLogger(__name__)


class RateLimiter:
    """Token-bucket rate limiter keyed by client IP."""

    def __init__(self):
        # {ip: [(timestamp, count), ...]}
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def _cleanup(self, ip: str, window: float):
        """Remove expired entries."""
        cutoff = time.time() - window
        self._hits[ip] = [t for t in self._hits[ip] if t > cutoff]

    def check(self, ip: str, max_requests: int, window_seconds: float):
        """Check if request is allowed. Raises 429 if rate exceeded."""
        with self._lock:
            self._cleanup(ip, window_seconds)
            if len(self._hits[ip]) >= max_requests:
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded. Max {max_requests} requests per {int(window_seconds)}s.",
                )
            self._hits[ip].append(time.time())

    def periodic_cleanup(self):
        """Clean up all expired entries. Call periodically."""
        with self._lock:
            now = time.time()
            for ip in list(self._hits.keys()):
                self._hits[ip] = [t for t in self._hits[ip] if t > now - 3600]
                if not self._hits[ip]:
                    del self._hits[ip]


class RedisRateLimiter:
    """Fixed-window rate limiter backed by Redis (multi-worker safe)."""

    def __init__(self, redis_url: str):
        if redis is None:
            raise RuntimeError("redis library not installed")
        self._client = redis.Redis.from_url(redis_url, decode_responses=True)

    def check(self, key: str, max_requests: int, window_seconds: float):
        """Check if request is allowed. Raises 429 if rate exceeded."""
        window = int(window_seconds)
        bucket = int(time.time() // window) if window > 0 else 0
        redis_key = f"rl:{key}:{bucket}"
        try:
            count = self._client.incr(redis_key)
            if count == 1:
                self._client.expire(redis_key, window)
        except Exception as e:
            # If Redis is unavailable, fail open rather than block traffic.
            logger.warning("Redis rate limit check failed: %s — failing open", e)
            return
        if count > max_requests:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded. Max {max_requests} requests per {window}s.",
            )

    def periodic_cleanup(self):
        """No-op: Redis handles expiration automatically."""
        return


def assert_single_worker_or_redis():
    """Warn loudly if running multiple workers without a shared Redis backend."""
    if os.getenv("REDIS_URL"):
        return
    worker_vars = ("UVICORN_WORKERS", "WEB_CONCURRENCY", "GUNICORN_WORKERS")
    for var in worker_vars:
        val = os.getenv(var)
        if not val:
            continue
        try:
            n = int(val)
        except ValueError:
            continue
        if n > 1:
            logger.critical(
                "Rate limiter is in-memory but %s=%s. Per-worker counters will diverge. "
                "Set REDIS_URL to enable shared rate limiting.",
                var,
                n,
            )


def _build_limiter():
    """Return a RedisRateLimiter if REDIS_URL is set and usable, else in-memory."""
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        return RateLimiter()
    if redis is None:
        logger.warning(
            "REDIS_URL is set but the 'redis' package is not installed. "
            "Falling back to in-memory rate limiter."
        )
        return RateLimiter()
    try:
        return RedisRateLimiter(redis_url)
    except Exception:
        logger.exception(
            "Failed to initialise RedisRateLimiter; falling back to in-memory"
        )
        return RateLimiter()


# Global limiter instance
limiter = _build_limiter()


def get_client_ip(request: Request) -> str:
    """Extract real client IP, respecting X-Real-IP and X-Forwarded-For behind nginx."""
    # X-Real-IP is set by nginx to the actual client IP (most reliable)
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    # Fallback to X-Forwarded-For (first entry is original client)
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ── Pre-configured rate limit functions ─────────────────────

def rate_limit_default(request: Request):
    """Standard API rate limit: 60 requests per minute per IP."""
    limiter.check(get_client_ip(request), max_requests=60, window_seconds=60)


def rate_limit_auth(request: Request):
    """Auth endpoints: 10 requests per minute per IP (anti-brute-force)."""
    limiter.check(get_client_ip(request), max_requests=10, window_seconds=60)


def rate_limit_heavy(request: Request):
    """Heavy endpoints (NBB load, export): 5 requests per minute per IP."""
    limiter.check(get_client_ip(request), max_requests=5, window_seconds=60)


def rate_limit_search(request: Request):
    """Search endpoints: 30 requests per minute per IP."""
    limiter.check(get_client_ip(request), max_requests=30, window_seconds=60)
