"""In-process TTL cache for read-mostly endpoints.

Serves repeat hits to the same query without going back to Postgres.
Designed for sector/province/size aggregates that change at most daily —
NOT for per-user data, paginated lists where the cache key would explode,
or anything tied to auth state.

Usage:
    from cache import ttl_cache

    @ttl_cache(ttl_seconds=300)
    def expensive_aggregate(province: str | None = None) -> list[dict]:
        return fetch_all(...)

The cache key is the (function, args, kwargs) tuple, so callers can pass
small primitives (str/int/bool/None). Lists/dicts are not hashable and
will raise — that is intentional, push variation into named params.
"""

from __future__ import annotations

import asyncio
import functools
import threading
import time
from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")

_lock = threading.Lock()


def ttl_cache(ttl_seconds: int = 300, maxsize: int = 256) -> Callable:
    """Decorator: cache the function result for ttl_seconds.

    Works for both sync and async functions. Per-decorator storage keeps
    every wrapped endpoint isolated, so we don't fight over a global LRU.
    """

    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        store: dict[tuple, tuple[float, Any]] = {}

        def _key(args: tuple, kwargs: dict) -> tuple:
            # Frozenset of items keeps kwargs order-independent.
            return (args, tuple(sorted(kwargs.items())))

        def _evict_expired(now: float) -> None:
            # Cheap pass: drop expired entries on every miss. Bounded by maxsize
            # so this stays O(1) amortised.
            if len(store) <= maxsize:
                return
            expired = [k for k, (exp, _) in store.items() if exp <= now]
            for k in expired:
                store.pop(k, None)
            if len(store) > maxsize:
                # Drop oldest expirations until we are back under cap.
                ordered = sorted(store.items(), key=lambda kv: kv[1][0])
                for k, _ in ordered[: len(store) - maxsize]:
                    store.pop(k, None)

        if asyncio.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any):
                now = time.time()
                key = _key(args, kwargs)
                hit = store.get(key)
                if hit and hit[0] > now:
                    return hit[1]
                value = await fn(*args, **kwargs)
                with _lock:
                    store[key] = (now + ttl_seconds, value)
                    _evict_expired(now)
                return value

            async_wrapper.cache_clear = lambda: store.clear()  # type: ignore[attr-defined]
            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any):
            now = time.time()
            key = _key(args, kwargs)
            hit = store.get(key)
            if hit and hit[0] > now:
                return hit[1]
            value = fn(*args, **kwargs)
            with _lock:
                store[key] = (now + ttl_seconds, value)
                _evict_expired(now)
            return value

        sync_wrapper.cache_clear = lambda: store.clear()  # type: ignore[attr-defined]
        return sync_wrapper

    return decorator
