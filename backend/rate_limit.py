"""Simple in-memory rate limiter for FastAPI.

Uses a sliding window counter per IP address. No external dependencies.
Designed for single-process deployments (which Data Peak uses).
"""

import time
import threading
from collections import defaultdict
from fastapi import Request, HTTPException


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


# Global limiter instance
limiter = RateLimiter()


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
