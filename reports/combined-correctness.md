# Correctness review — combined Zenrows + NBB diff (2026-04-25)

## Verdict: PASS

## Critical (block merge)
None.

## Non-blocking
- `last_exc` declared at `scripts/nbb_nightly_backload.py:208,249` is unused after the loop. Harmless dead code; leave or remove in a future cleanup.

## Findings

**Retry loop correctness** (`scripts/nbb_nightly_backload.py` ~L200, ~L245):
- Exactly 2 attempts via `for attempt in (1, 2)`.
- 5s sleep between attempts only; no sleep after the second failure.
- `break` on successful network call (after `resp = session.get(...)`).
- Terminal failure returns the original shape: `(0, [])` for refs, `None` for filings.
- `resp` is never accessed unbound — second-attempt failure returns from inside the except block.

**Quota interaction**: `MAX_CALLS` budget counts calls, not retry attempts. Worst case per-CBE: 30s + 5s + 30s + 1.25s ≈ 66s, well under the 4h cron timeout. No budget impact.

**Timeout bump (20s → 30s)**: No upstream tighter ceiling. Cron outer timeout is 4h. Safe.

**Change A (Zenrows disablement)** confirmed independent of Change B — different files, no cross-references. Previously reviewed PASS still holds.

## Files audited
- `scripts/nbb_nightly_backload.py` L200-273, L383-507
- `backend/scraper.py`, `backend/semantic_bootstrap.py`, `backend/routers/companies/enrichment.py`, `scripts/nightly_health_report.py`
- `CLAUDE.md`, `docs/architecture.md`, `docs/semantic-operations.md`
