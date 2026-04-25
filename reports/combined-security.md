# Security review — combined Zenrows + NBB diff (2026-04-25)

## Verdict: PASS

## Critical (block merge)
None.

## Non-blocking
None of material concern.

## Findings

**NBB retry — DoS / amplification risk: LOW**
- Hard-bounded at 2 attempts via `for attempt in (1, 2)` (`scripts/nbb_nightly_backload.py` L209, L250).
- Fixed 5s sleep between attempts; no exponential growth.
- 5xx responses are not exceptions in `requests`, so they don't trigger the retry path — only network exceptions do.

**API key handling**:
- `_headers()` constructs the auth header inside the try block.
- Warning log lines (~L223, L264) emit only `(cbe, fiscal_year, exception)` / `(cbe, reference_number, exception)`.
- `requests` exception strings do not contain `NBB_AUTHENTIC_KEY`.
- `/opt/leadpeek/scripts/_watchdog_state/nightly.log` will not leak the key.

**Postgres lock hold**:
- `fetch_references` / `fetch_filing` called outside any transaction scope (run loop ~L422, L487).
- `candidates_for_year` query is read-only.
- Extended 30s timeout governs network I/O only; no DB connection held during the fetch.

**Change A — Zenrows disablement** confirmed safe in combination:
- `backend/scraper.py` `_zenrows_fetch` empty-key guard (L504).
- `backend/semantic_bootstrap.py` removal of `ZENROWS_API_KEY` from required env doesn't degrade auth/permission posture.
- Neutralised error strings in `routers/companies/enrichment.py` no longer reference internal env-var names.
- Health-report YELLOW path still detects genuine ERROR/FAIL log patterns separately.

**Pre-verified (skipped re-investigation)**:
- `.env` not tracked by git (`git ls-files .env` empty, `git log --all -- .env` empty, `.gitignore:12` matches).
- `_scratch_rp/` correctly gitignored (`.gitignore:49`).

## Files audited
- `scripts/nbb_nightly_backload.py` L200-274, L383-499
- `backend/scraper.py` L22, L496-527
- `backend/semantic_bootstrap.py` L32-37
- `backend/routers/companies/enrichment.py` L50-65
- `scripts/nightly_health_report.py` L353-382
- Docs (CLAUDE.md, architecture.md, semantic-operations.md)
