# Security review — wave 1 acceleration (2026-04-25)

## Verdict: PASS

## Critical
None.

## Findings

**Concurrent DB writes** — `SimpleConnectionPool(2, 10)` accommodates up to 6 concurrent ops (3 workers × write+embed). `get_connection()`/`put_connection()` context managers scope each connection per-call. psycopg2 pool is thread-safe internally; `asyncio.to_thread` doesn't share session state across threads. Safe.

**Fallback model data flow** — On `ollama:kimi-k2.6` failure, same prompt body sent to `anthropic/claude-haiku-4.5` fallback. Both are intended LLM providers; KBO data is mostly public; no secrets in prompt. Expected behaviour.

**Concurrency × LLM budget** — Daily $10 budget enforced globally via `daily_spend_usd()` at `enrichment_worker.py:124` before each job launch. 3× concurrency increases throughput, not budget envelope. Budget guard fires per-poll-cycle, not per-job — cap holds.

**DDG rate-limit posture** — 12s/call × 3 concurrency = ~15 calls/min from our IP (vs ~3/min before). Backoff multiplier (2.0×) auto-corrects on 429. Per-IP ban is a provider-side risk; the Webshare-DDG rewrite (wave 2) removes this surface entirely.

**Env var logging** — `BULK_HAIKU_FALLBACK_MODEL` loaded at import in `ai_client.py:1674-1678`, never logged.

## Files audited
- `backend/db.py` (30-56)
- `backend/enrichment_worker.py` (124, 718-730, 334)
- `backend/ai_client.py` (1674-1678, 1941-1963)
- `docker-compose.yml`, `docker-compose.staging.yml`
