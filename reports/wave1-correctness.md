# Correctness review — wave 1 acceleration (2026-04-25)

## Verdict: PASS

## Critical
None.

## Findings

**WORKER_CONCURRENCY 1 → 3**
- Semaphore wired correctly (`enrichment_worker.py:90`).
- DDG throttle (`scraper.py:158`) is process-global asyncio.Lock — 3 concurrent jobs serialise behind the new 12s interval, no deadlock.
- DB pool is `SimpleConnectionPool(2, 10)` — capacity for 6 concurrent ops (3 workers × write+embed).

**DDG_MIN_INTERVAL_S 20 → 12**
- Read at `scraper.py:145`, used in `_ddg_throttle()` at line 180.
- Dynamic backoff intact (auto-corrects on 429).

**`_persist_and_embed` helper**
- All 5 call sites correctly migrated.
- `asyncio.to_thread(_write_bulk_row, ...)` — `execute()` in `db.py:142–164` is thread-safe via the connection pool.
- `asyncio.gather` raises on first failure: matches previous semantics where embed failures were already best-effort (caught at line 601). Row write completes either way (committed before gather returns).
- No partial-state visibility: row + embedding write to separate tables, downstream consumers see both-or-neither.

**BULK_HAIKU_MODEL → ollama:kimi-k2.6**
- Valid identifier per `is_ollama_model()` at `ai_client.py:33-34`.
- Fallback wired via `BULK_HAIKU_FALLBACK_MODEL` env, resolved by `_resolve_bulk_fallback_model()` at `ai_client.py:1941-1945`.

**Rolling restart risk** — pre-existing (in-flight jobs killed on container recreate), not made worse by this patch.

## Files audited
- `backend/enrichment_worker.py` (90, 288-340, 466-583)
- `backend/scraper.py` (145, 158, 180-201)
- `backend/db.py` (30, 142-164)
- `backend/ai_client.py` (33-34, 1898-1987)
- `docker-compose.yml`, `docker-compose.staging.yml`
