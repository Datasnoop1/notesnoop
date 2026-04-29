# Phase 5.0 — Unified-summary schema migration

**Status:** Spec, not yet applied. Approval gate before any DDL touches staging or prod.

**Goal:** Add the schema scaffolding so semantic and AI-insights pipelines can share one source of truth, without breaking either pipeline today. This is the foundation for Phase 5.1 (cached scrape text), 5.2 (qwen+kimi critic-refine elaboration), and 5.3 (embedding backfeed).

This phase is **additive only** — no columns are dropped, no application code changes. The legacy `bulk_summary` and `ai_insights` columns continue to be written and read exactly as they are today. Phase 5.0 just creates the slots that Phase 5.2 will fill.

---

## 1. New columns on `company_enrichment`

```sql
ALTER TABLE company_enrichment
  ADD COLUMN IF NOT EXISTS unified_summary       JSONB,
  ADD COLUMN IF NOT EXISTS quality_tier          TEXT,
  ADD COLUMN IF NOT EXISTS quality_tier_at       TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS model_chain           JSONB,
  ADD COLUMN IF NOT EXISTS bulk_website_text     TEXT,
  ADD COLUMN IF NOT EXISTS bulk_website_text_at  TIMESTAMPTZ;

ALTER TABLE company_enrichment
  ADD CONSTRAINT enrichment_quality_tier_check
  CHECK (quality_tier IS NULL OR quality_tier IN
    ('bulk_only', 'bulk_escalated', 'narrative_lite', 'narrative_full'));
```

| Column | Purpose |
|---|---|
| `unified_summary` | The single canonical narrative blob. Populated by both pipelines after Phase 5.2; pre-Phase-5.2 it's just a backfill mirror of whichever existing column we have. |
| `quality_tier` | One of: `bulk_only` (Q2 only) → `bulk_escalated` (Q2 + Haiku-equivalent) → `narrative_lite` (qwen+kimi refine) → `narrative_full` (refine + review pass). Tier only ever climbs up. |
| `quality_tier_at` | When the current tier was last achieved. Used to prune stale narratives. |
| `model_chain` | Audit trail. Array of `{step, model, latency_ms, tokens, completed_at}` so we can debug regressions and track which model produced which field. |
| `bulk_website_text` | Cached cleaned-scrape text that the bulk worker just stored. Phase 5.1 makes the elaboration path read it instead of re-scraping. |
| `bulk_website_text_at` | When the cached scrape was captured. Read it only if recent (configurable, default 30 days). |

## 2. Backfill

```sql
-- One-time backfill. Runs on staging first, then prod.
-- Best-effort: copies whichever existing summary is richest into unified_summary.

UPDATE company_enrichment
SET
  unified_summary = COALESCE(
    -- Prefer ai_insights when it exists and parses (richer 9-field shape)
    NULLIF(ai_insights, '')::jsonb,
    bulk_summary
  ),
  quality_tier = CASE
    WHEN ai_insights IS NOT NULL AND ai_insights <> '' THEN 'narrative_lite'
    WHEN bulk_summary IS NOT NULL                       THEN 'bulk_only'
    ELSE NULL
  END,
  quality_tier_at = COALESCE(
    -- Use whichever timestamp matches the source we copied from
    CASE WHEN ai_insights IS NOT NULL AND ai_insights <> ''
         THEN generated_at
         ELSE bulk_summary_at
    END
  ),
  model_chain = jsonb_build_array(
    jsonb_build_object(
      'step', 'legacy_backfill',
      'source_column', CASE
        WHEN ai_insights IS NOT NULL AND ai_insights <> '' THEN 'ai_insights'
        WHEN bulk_summary IS NOT NULL                       THEN 'bulk_summary'
      END,
      'completed_at', NOW()
    )
  )
WHERE unified_summary IS NULL
  AND (ai_insights IS NOT NULL OR bulk_summary IS NOT NULL);
```

**Notes:**
- Some `ai_insights` rows may be malformed JSON (legacy free-form text). The cast to `jsonb` will fail on those — wrap in a function that catches and falls back to `bulk_summary`. (Working draft: a `try_parse_jsonb()` helper.)
- We do NOT backfill `bulk_website_text`. That column is only populated going forward in Phase 5.1.
- Historical bulk rows can't be reliably classified as `bulk_only` vs `bulk_escalated` — we don't know which model produced them. All backfilled bulk rows get `bulk_only`. Phase 5.2 onward, the worker writes the tier explicitly.

## 3. Indexes

```sql
CREATE INDEX IF NOT EXISTS idx_enrichment_quality_tier
  ON company_enrichment (quality_tier, quality_tier_at);
```

Used for: "which companies need an upgrade?" admin queries (`WHERE quality_tier = 'bulk_only' ORDER BY quality_tier_at`).

No index on `unified_summary` content — JSONB GIN index isn't worth it until Phase 5.4 when we drop the duplicate columns and search starts reading from `unified_summary`.

## 4. Rollback

The migration is fully additive. Rollback is:

```sql
DROP INDEX IF EXISTS idx_enrichment_quality_tier;
ALTER TABLE company_enrichment
  DROP CONSTRAINT IF EXISTS enrichment_quality_tier_check,
  DROP COLUMN IF EXISTS bulk_website_text_at,
  DROP COLUMN IF EXISTS bulk_website_text,
  DROP COLUMN IF EXISTS model_chain,
  DROP COLUMN IF EXISTS quality_tier_at,
  DROP COLUMN IF EXISTS quality_tier,
  DROP COLUMN IF EXISTS unified_summary;
```

Application code is unchanged in this phase, so dropping these columns has zero functional impact.

## 5. Verification queries (run after backfill)

```sql
-- (a) all rows that have a legacy summary should now have unified_summary
SELECT COUNT(*) AS unbackfilled
  FROM company_enrichment
 WHERE unified_summary IS NULL
   AND (ai_insights IS NOT NULL AND ai_insights <> '' OR bulk_summary IS NOT NULL);
-- expected: 0 (or close to 0 if some ai_insights rows had malformed JSON)

-- (b) tier distribution
SELECT quality_tier, COUNT(*)
  FROM company_enrichment
 GROUP BY quality_tier
 ORDER BY 2 DESC;

-- (c) sanity: any quality_tier set without unified_summary?
SELECT COUNT(*)
  FROM company_enrichment
 WHERE quality_tier IS NOT NULL AND unified_summary IS NULL;
-- expected: 0
```

## 6. Deploy procedure

1. **Staging.** Apply migration script to staging DB. Run verification queries. Smoke-test that `/api/companies/{cbe}/ai-insights` and `/api/search/semantic` still work — they should be entirely unaffected since application code doesn't read the new columns yet.
2. **Operator review.** Eyeball the staging tier distribution. Sanity check a handful of rows: `SELECT enterprise_number, quality_tier, unified_summary FROM company_enrichment LIMIT 5`.
3. **Prod.** Apply during a low-traffic window. The `UPDATE` will touch every row with a legacy summary — expect 5-15 minutes on a table that size. Use `ALTER TABLE` first (cheap), then `UPDATE` in batches of 50k via a small Python script if the single-statement update locks too long.
4. **Done.** Phase 5.1 (write `bulk_website_text` from the bulk worker) is the next deliverable.

## 7. What's deliberately out of scope for 5.0

- **No schema changes to legacy columns.** `bulk_summary`, `ai_insights`, `bulk_summary_at`, etc. are untouched.
- **No application code changes.** Nothing reads `unified_summary` yet.
- **No model behavior changes.** Bulk pipeline runs identically.
- **No view/alias creation for backwards compat.** Not needed at this stage; the legacy columns continue to serve their existing readers directly.

These all come in Phases 5.1–5.4.

## 8. Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| Backfill UPDATE locks `company_enrichment` longer than expected | Low-med | Run in batches if single statement runs > 60s on staging |
| Some `ai_insights` JSON is malformed and casts fail | Medium | Wrap cast in a try-parse helper; rows that fail just don't get backfilled — they'll get `unified_summary` written by the next on-profile elaboration call |
| Backfill exhausts disk on prod (column adds + populated JSONB ≈ +1-2GB) | Low | Hetzner has 80GB; current Postgres data ~15GB. Headroom is fine. Confirm via `df -h` before running. |
| Migration runs on staging while staging worker is enriching | Low | Pause staging worker during migration window |

## 9. Approval gate

Operator approval needed for:
- Schema additions (the 6 new columns + constraint + index)
- Backfill SQL (the single UPDATE)
- Deploy order (staging → prod, with operator-confirmed window for prod)

Once approved, I'll write the actual migration script (`scripts/migrate_phase_5_0.py`), test on staging, report results, then ask for the prod-window confirmation separately.
