# Security review — Wave 2 Webshare-DDG (2026-04-25)

## Verdict: PASS

## Critical
None.

## Findings (with fixes shipped)

- **Proxy credential leak in exception logs** — addressed. Added `_scrub_proxy_url()` that strips `http://USER:PASS@` from any string before logging. All 4 DDG fetch sites apply it to the exception text.
- **Proxy file parser** — does not log line content (matches the staatsblad pattern), defends against accidental wrong-path mounts.
- **Per-IP rate-limit bypass** — intentional, sound. The new circuit-breaker (correctness review) covers the worst case where DDG bans the whole Webshare ASN.
- **DNS rebinding via proxy** — known threat-model shift. Webshare is a trusted commercial provider; same trust as the staatsblad worker already gives them.
- **Container env var visibility** — `WEBSHARE_PROXIES_FILE` is a path, not a secret. The proxies themselves live in the read-only mount, never in env vars.
- **Volume mount path** — `:ro`, default `/root/webshare_proxies.txt`, matches existing pattern. Operator-controlled override via env var; assumes operator with shell access already trusts themselves.

## Files audited
- `backend/scraper.py` (proxy load, exception logging, breaker)
- `docker-compose.yml`, `docker-compose.staging.yml` (mount + env)
