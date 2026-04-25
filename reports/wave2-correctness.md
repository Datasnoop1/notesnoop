# Correctness review — Wave 2 Webshare-DDG (2026-04-25)

## Verdict: PASS

## Critical
None remaining. Initial review flagged the silent-failure risk if DDG bans the entire Webshare ASN — addressed with a circuit-breaker (`_ddg_proxy_4xx_observed` / `_ddg_proxy_2xx_observed`) that trips the global cooldown after `DDG_VIA_WEBSHARE_BREAKER_THRESHOLD` (default 20) consecutive cross-proxy 4xx responses.

## Findings (after fix)

- All 4 DDG fetch sites correctly pass `proxy=` to `httpx.AsyncClient` and route to the breaker on 4xx-via-proxy / `_ddg_proxy_2xx_observed` on 200-via-proxy.
- Throttle correctly branches: 0.5s when `_WEBSHARE_DDG_PROXIES` non-empty, original `max(DDG_MIN_INTERVAL_S, _ddg_dynamic_interval_s)` when empty.
- Module-import proxy load: file-missing returns empty list, `_ddg_proxy_or_none()` returns None, callers fall back to direct + original throttle.
- Compose mount mirrors the staatsblad-bulk-worker pattern, `:ro`.
- Rollback: `DDG_VIA_WEBSHARE=false` skips proxy load entirely, restores pre-Wave-2 behaviour.

## Files audited
- `backend/scraper.py` (new helpers + 4 DDG sites)
- `docker-compose.yml`, `docker-compose.staging.yml`
