# Correctness final review — playwright-scraper v3 (2026-04-25)

## Verdict: PASS

## Critical
None.

## Findings

**v3 hardening verified intact:**
- `_ip_is_internal` (`server.py:111`) — uses `getattr(ip, "ipv4_mapped", None)`, safe on both IPv4Address and IPv6Address.
- `_scrub_for_log` (`server.py:172`) — caps length, replaces non-printable ASCII with `?`.
- Generic `error="unsafe-url"` returned to callers (`server.py:339`); detailed reason logged server-side only.
- Backend `_url_passes_basic_ssrf_guard` (`backend/scraper.py:38`) — nested `_internal()` mirrors server-side IPv4-mapped check.

**v2 critical fixes still intact:**
- Use-after-close: re-check `_browser.is_connected()` inside the lock at `server.py:355`.
- `_request_count` race: increment in finally at `server.py:426` (always runs).
- Recycle on failure: counter increments on every attempt regardless of outcome.
- Drained semaphore on recycle: holds all MAX_CONCURRENT slots before close (`server.py:240-242`).
- Bounded queue: cap at QUEUE_LIMIT before any state mutation (`server.py:323-324`).

**End-to-end smoke trace clean:**
worker → `_playwright_fetch` → backend SSRF guard → POST → server SSRF + scrub → proxy pick → new_context → goto → content → return HTML or empty fallback.

## Files audited
- `playwright-scraper/server.py`
- `backend/scraper.py`
- `docker-compose.yml`, `docker-compose.staging.yml`
