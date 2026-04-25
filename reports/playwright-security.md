# Security final review — playwright-scraper v3 (2026-04-25)

## Verdict: PASS

## Critical
None. All three v2 issues correctly addressed:

1. **SSRF info disclosure (FIXED)** — Caller receives generic `error="unsafe-url"` (`server.py:339`). Detailed reason logged server-side only via `_scrub_for_log` (`server.py:336`). Backend mirrors at `scraper.py:98`.
2. **Log injection (FIXED)** — `_scrub_for_log` strips control chars and caps length. Applied to both URL and reason before they hit any log line. Equivalent inline scrubbing on backend side.
3. **IPv4-mapped IPv6 (defense-in-depth)** — `_ip_is_internal` (`server.py:111`) explicitly checks `ipv4_mapped` even though Python's `is_private` already covers it. Backend has equivalent.

## Non-blocking

- **Proxy credentials** — `proxy["server"]` (host:port) is the only proxy data exposed in logs/responses. Username/password never leak.
- **Network isolation** — Both compose files use `expose: ["8000"]` (docker-network only, no `ports`). nginx has no route. Pattern consistent with `staatsblad-bulk-worker`.
- **Dependencies pinned**:
  - fastapi==0.115.0 (Nov 2024, no known CVEs)
  - uvicorn==0.32.0 (Oct 2024, no known CVEs)
  - pydantic==2.9.0 (Sep 2024, no known CVEs)
  - Base image `mcr.microsoft.com/playwright/python:v1.48.0-noble` (pinned)
- **`_scrub_for_log`** — pure function, no new attack surface.
- **DNS rebinding** — known limitation, documented in `server.py:138-139`. Localhost/internal DNS names rejected at literal-IP stage before resolution; rebinding of external hostnames during navigation would require Chromium request interception (deferred).

## Files audited
- `playwright-scraper/server.py`, `playwright-scraper/Dockerfile`, `playwright-scraper/requirements.txt`
- `backend/scraper.py`
- `docker-compose.yml`, `docker-compose.staging.yml`
- nginx config (no playwright-scraper route)
