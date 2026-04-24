# Final verification — 2026-04-24 sprint

Two subagents ran against the 16 items shipped to staging: one
regression audit of the code (file:line trace of each intended
behaviour), one end-to-end smoke against `http://62.238.14.150:8080`.

## Agent 1 — Regression audit

**VERDICT: PASS** — all 16 items implemented correctly, proper i18n,
keyboard access, SQL parameterisation, no dangerous patterns.

Minor non-blocking polish gaps:
- Item 14: "Share card (public link)" menu label is hardcoded English.
- Item 16: `/showcase` marketing page is English-only (consistent with `/use-cases.html`).
- Item 15: frontend-liveness check hits `/favicon.ico` (static). Not a real liveness signal — semantic quibble only.
- Item 12: `LIMIT 5000` in loc_filter CTE silently truncates very loose filters — acceptable given the scoring CTE behind it.

Full item-by-item trace is embedded in the agent's run log.

## Agent 2 — End-to-end smoke

Initial run flagged two regressions; both have been hotfixed.

| Route | Result (initial) | Result (post-hotfix) |
|-------|-----------------|---------------------|
| `/` | 200 ✓ | 200 ✓ |
| `/status` | 200 ✓ | 200 ✓ |
| `/showcase` | **404** — deploy lag | deploying (round 4) |
| `/s/0400378485` | 200 ✓ | 200 ✓ |
| `/people/Colruyt` | 200 ✓ | 200 ✓ |
| `/company/0400378485` | 200 ✓ | 200 ✓ |
| `/sitemap.xml` | **50 009 URLs** ✓ | 50 009 ✓ |
| `/api/companies/search?q=albert` | 200 ✓ | 200 ✓ |
| `/api/companies/search?q=albert&postal_code=1000` | **500** (bad ESCAPE) | fix deploying |
| `/api/sitemap/companies` | 200 ✓ | 200 ✓ |
| `/api/health` | 200 ✓ | 200 ✓ |
| `/favourites` | 200 ✓ | 200 ✓ |

## Hotfixes applied post-verification

- Commit `12b23cb` — `backend/routers/companies/search.py`: changed location-filter ILIKE clauses from `ESCAPE '\\\\'` (two literal backslashes in the query) to `ESCAPE '\\'` (one literal backslash) to match the rest of the file. Postgres rejects any `ESCAPE` longer than one character with `InvalidEscapeSequence`. Caught by the end-to-end agent.

## Known gaps (all hotfixes applied post-verification)

- `/showcase` now **200** on staging after the round-4 rebuild landed.
- `/api/companies/search?q=...&postal_code=...` now **200** on staging after backend rebuild with commit `12b23cb`. Live check: unfiltered `q=albert` returns 20 results; `q=albert&postal_code=1000` returns 19 (11 commercial + 8 nonprofit). Filter is narrowing as intended.
- The two polish gaps flagged by Agent 1 (hardcoded English menu label, English-only marketing page) are deliberately not hotfixed — they don't break functionality and the operator may want them left as-is.

## Final staging smoke (post-hotfix)

```
/                                             200
/status                                       200
/showcase                                     200
/s/0400378485                                 200
/people/Colruyt                               200
/company/0400378485                           200
/search?q=colruyt&postal_code=1500            200
/api/health                                   200
/api/companies/search?q=albert                200
/api/companies/search?q=albert&postal_code=1000   200
/api/sitemap/companies                        200
sitemap.xml entries: 50009
```

## What this verifies vs what it doesn't

Verified:
- File-level trace for each of the 16 items matches the intent.
- HTTP responses on every public route.
- Sitemap dynamic render + 50 009 URLs.
- Location filter semantic (unfiltered 20 vs filtered — only comparable once hotfix lands).

Not verified (needs operator eyes):
- Visual fidelity of the gradient / frosted-glass components.
- Actual behaviour of the Add-to-project Dialog with many projects + companies.
- Person-profile timeline on real complex mandates.
- The clipboard button on HTTPS production (tested on HTTP staging via execCommand fallback).
