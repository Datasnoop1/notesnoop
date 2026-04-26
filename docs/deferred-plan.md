# Deferred Work Plan — post-2026-04-25 audit pass

This document captures the work that was scoped but **not** shipped in
the 2026-04-25 audit deploy, with concrete file refs, a recommended
sequence, effort estimates, and the risks/preconditions that made me
hold them back. The operator can pull individual items into a session
when ready.

---

## Sequencing recommendation

Five items, ordered by **leverage / risk** ratio:

1. **Sector benchmark perf + cache** (perf, low risk, big win on profile tab-2 click)
2. **Trigram index on `address.street_*`** (perf, low risk, fixes the documented 1–2 s address-fallback floor)
3. **Tier-limit middleware DB-query-per-request** (perf, medium risk — touches every request)
4. **HS256 fallback removal** (security, high risk — auth — needs careful staging burn-in)
5. **AI key_management validation against `administrator` table** (quality, low risk)

After those: the bigger feature work from `docs/todo.md` —
admin dashboard rebuild (#22), person profile page (#19), spiderweb
overhaul (#21).

---

## 1. Sector benchmark performance + caching

**Problem**
`/api/companies/{cbe}/sector-benchmark` runs seven `PERCENTILE_CONT`
window functions across every NACE peer of the target on each call.
For high-cardinality NACEs (retail, consulting) this stalls 1–3 s on
every benchmark-tab click. Already cached at 30 days for the *similar*
endpoint via `ai_similar_cache`, but the benchmark itself is recomputed
every call.

**Files**
- `backend/routers/companies/similar.py:68-186` — the seven-percentile
  query.
- `src/schema.sql` — would gain a new `sector_benchmark_cache` table
  (or a materialized view, see below).

**Approach**
Two options, pick one:

a) **Materialized view** `sector_benchmark_cache`, refreshed nightly by
   the daily NBB pipeline.
   - Schema: `(nace2 TEXT PRIMARY KEY, p10/p25/p50/p75/p90 numerics for
     revenue / ebitda / margin / fte / fixed_assets, peer_count, refreshed_at)`.
   - The endpoint reads from the cache; falls back to live computation
     only on cache miss.
   - Risk: the materialized view is on the shared prod DB. Build it via
     `CREATE MATERIALIZED VIEW IF NOT EXISTS` in the daily pipeline so
     no destructive migration is needed.

b) **In-memory `@ttl_cache`** with a 12 h TTL (256 keys ≈ 256 NACE2
   sectors).
   - Simpler, no schema. Loses the cache on every backend restart.

Recommend (a). The materialised view also pays off when `/stats/*` and
the screener percentile column are computed.

**Effort** 2–3 hours including the nightly refresh job + smoke tests.

**Risk** Low. The MV is additive — no impact on existing queries until
the endpoint is rewritten to read from it.

**Preconditions** None.

---

## 2. Trigram index on `address.street_nl` + `address.street_fr`

**Problem**
Address-fallback search (`addr_match` arm in
`backend/routers/companies/search.py:348-360`) does four `ILIKE` clauses
on a 3M-row `address` table. `docs/search.md` documents a 1–2 s floor
on address-typed queries like "Rue Neuve". Without GIN trigram indexes
on `street_nl` / `street_fr`, the `ILIKE %x%` patterns sequentially
scan the whole table.

**Files**
- One-off migration: `migrations/2026-XX-XX_address_trgm.sql`:
  ```sql
  CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_address_street_nl_trgm
    ON address USING GIN (street_nl gin_trgm_ops)
    WHERE type_of_address = 'REGO';
  CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_address_street_fr_trgm
    ON address USING GIN (street_fr gin_trgm_ops)
    WHERE type_of_address = 'REGO';
  CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_address_municipality_nl_trgm
    ON address USING GIN (municipality_nl gin_trgm_ops)
    WHERE type_of_address = 'REGO';
  CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_address_municipality_fr_trgm
    ON address USING GIN (municipality_fr gin_trgm_ops)
    WHERE type_of_address = 'REGO';
  ```
- The partial-index predicate (`type_of_address = 'REGO'`) keeps the
  index small — `addr_match` already filters on REGO.

**Approach**
1. Run the migration via psql with `CREATE INDEX CONCURRENTLY` so we
   don't lock writes during the build (~5–10 min on the full table).
2. Confirm `EXPLAIN ANALYZE` on a known address query uses the new
   indexes.
3. Drop the `len(raw) >= 6` gate in `search.py:127-131` — the old gate
   was protecting against the seq-scan, which is gone.

**Effort** 30 min for the migration; 30 min for re-tuning the gate +
smoke tests. Index build runs in the background.

**Risk** Low. `CREATE INDEX CONCURRENTLY` is non-blocking. Storage
cost ≈ 50 MB.

**Preconditions** Operator runs the migration on prod once
(non-destructive) and verifies `pg_class.relpages` for `address`
hasn't ballooned afterwards.

---

## 3. Tier-limit middleware: DB query per request

**Problem**
`TierLimitMiddleware` in `backend/main.py` runs a `SELECT COUNT(*)
FROM activity_log WHERE user_email = ? AND created_at >= today` on
**every** `/api/*` request. Even with the `idx_activity_log_user_date`
index added in `db.py:286`, this is two round-trips per request that
the middleware also re-queries `tier_config` for. At 200 req/min /
user that's 400 extra DB ops.

**Files**
- `backend/main.py` — `TierLimitMiddleware`, `_classify_endpoint`.

**Approach**
- Cache the (user_email, limit_type) → (count, count_window_start)
  per backend process for ~30 s. Refresh on first request after window
  expiry.
- `tier_config` is read-mostly; cache it for 5 min via `@ttl_cache`.
- Increment the count in-memory after every accepted request; refresh
  from DB only on TTL expiry or when the in-memory count crosses the
  limit (to confirm the limit is real before 429-ing).
- `docs/tech-debt.md` Group B already lists this. Keep the per-IP
  rate limiter on top — it's the DoS guard.

**Effort** 3–4 hours including a multi-instance correctness analysis
(eventually-consistent counts vs hard limits — pick a policy).

**Risk** Medium. Touches every request. Test thoroughly on staging.

**Preconditions** None. This is purely backend.

---

## 4. HS256 fallback removal in JWT verification

**Problem**
`backend/auth.py` falls back to HS256 with a shared secret if JWKS
fetch fails. `reports/ollama_review_security.md` flagged this as a
classic algorithm-confusion attack: an attacker who learns the public
JWKS key can forge tokens by setting `alg: HS256` and signing with
the public key as the HMAC secret.

**Files**
- `backend/auth.py` — JWKS cache + HS256 fallback path.
- `.env.production` — `SUPABASE_HS256_FALLBACK` env var (currently
  enabled per the runtime check).

**Approach**
1. Audit how often the HS256 fallback actually fires. If JWKS has
   been stable for months, removing the fallback is safe.
2. Remove the fallback. Replace with: if JWKS fetch fails, return
   401 with `Retry-After`, not "fall through and verify with the
   shared secret".
3. Keep the shared secret env var, but guard it behind `STAGING_MODE=1`
   only, never in production.
4. Test: bring backend up while Supabase is down; confirm 401s
   instead of HS256 acceptance.

**Effort** 2 hours code; needs 24-48 h staging burn-in to be sure
no legitimate users were depending on the fallback.

**Risk** **HIGH**. Auth change. Plan a rollback path: keep the env
var set, just gate it behind `STAGING_MODE`. Easy to flip back if
production sees auth failures.

**Preconditions** Confirm with the operator that no legitimate code
path relies on HS256. Run on staging first for at least 24 h with
the operator signing in/out via every channel (Google, password,
incognito, mobile Safari).

---

## 5. AI key_management validation against `administrator` table

**Problem**
`ai_client.py::ai_insights_pipeline` returns a `key_management` array
parsed from the website / LinkedIn scrape. There's no cross-check
against the structured `administrator` table — so the AI can return
people who left two years ago, or hallucinate names entirely. This
risks credibility hits (PE analyst sees a name they know is stale).

**Files**
- `backend/ai_client.py:1500-1530` — where the `key_management` array
  is built.
- `frontend/src/app/company/[cbe]/_tabs/insights-overlay.tsx` — where
  the array is displayed (likely; verify exact filename).

**Approach**
1. After the LLM returns `key_management`, fuzzy-match each name
   against the current `administrator` rows for this CBE
   (`mandate_end IS NULL` or `>= today`).
2. Annotate each entry with `source` and `mandate_status`:
   - `kbo_active` — name matches an active KBO admin → green badge.
   - `website_only` — only on website, no KBO match → yellow.
   - `kbo_resigned` — name matches a KBO admin whose `mandate_end`
     has passed → red, suppress from default view.
3. Frontend reads `source` and renders a discrete badge.

**Effort** 3 hours (matching logic + frontend chip + i18n strings).

**Risk** Low. Output is additive; existing consumers see the same
fields plus a new `source` field they can ignore.

**Preconditions** None.

---

## Other items pulled forward from `docs/todo.md`

These are bigger features, not bugs. Sketching the approach so the
operator knows what's involved before scheduling.

### Admin dashboard rebuild (#22)
Today: a single huge `backend/routers/admin.py` + ad-hoc tabs in
`frontend/src/app/admin/`. Operator says "slow, broken UX". Need a
fresh design pass before code: which tabs survive, which merge, what
KPIs land on the home view. Probably worth a separate planning
session with the operator before any code.

### Person profile page (#19)
New route `frontend/src/app/person/[id]/page.tsx`.
- Backend: `/api/people/{name}/timeline` aggregating `administrator`
  rows by `mandate_start` / `mandate_end` and joining
  `staatsblad_event` for resignation/appointment dates.
- Frontend: timeline component (vertical timeline, no third-party lib
  needed — recharts has scatter plot we can repurpose).
- Effort: ~2 days.

### Spiderweb / network graph polish (#20, #21)
Already uses `react-force-graph-2d`. Crowding on complex companies is
real. Three sub-tasks:
- Toggle buttons for shareholders / directors / subsidiaries layers.
- Zoom-to-fit on initial render.
- Label-collision avoidance (force-graph has built-in `nodeCanvasObject`
  hooks; can implement a simple "show label only when ≥1.5x zoom" rule).

### EBITDA drill-down (#11)
Click EBITDA on the summary tab → modal that shows rubric 9901
(operating profit) + rubric 630 (D&A) with each filing's value. The
data is already in `financial_data`; the modal is the only new UI.
Effort: ~3 hours.

### Conversational AI Q&A (#13)
Big undertaking: chat UI + RAG over the structured profile + financials
+ scraped narrative. Probably worth waiting until the bulk-summary
embeddings stabilise (they're on Phase 1 still).

---

## Pre-existing tech-debt (linked, not duplicated)

`docs/tech-debt.md` already triages the known auth, perf, and
PII-export items. The deferred plan above complements that doc — both
should stay in sync.

When you pick an item from this plan into an active session, move it
out of here and into a stage status (or just delete the section once
shipped).
