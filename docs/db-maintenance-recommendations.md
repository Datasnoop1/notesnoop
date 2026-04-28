# DB maintenance recommendations — 2026-04-28 audit

Output of the scheduled `cleanup--security` audit on 2026-04-28. Each
item below was identified as a low-risk maintenance opportunity but
**requires operator approval before running** because staging and prod
share the same Postgres (per `docs/architecture.md`).

DB total: **27 GB**. Server disk: **48 / 75 GB** (67%, down from 82%
on 2026-04-17 — Sunday `docker system prune -af` cron is working).

---

## 1. ANALYZE the seven KBO core tables (HIGHEST PRIORITY)

`pg_stat_user_tables` shows seven tables with **`n_live_tup = 0` and
no record of `last_analyze` or `last_autoanalyze`**, even though
`pg_class.reltuples` is in the millions. The planner is operating on
stale or empty stats for the largest tables in the database — every
join touching these tables risks a bad plan.

| Table | Planner rows | Last analyzed |
|---|---:|---|
| `activity` | 34,871,708 | never |
| `address` | 2,863,449 | never |
| `enterprise` | 1,941,155 | never |
| `establishment` | 1,676,490 | never |
| `contact` | 697,284 | never |
| `code` | 21,468 | never |
| `branch` | 7,306 | never |

Fix (read-only stats refresh, brief `SHARE UPDATE EXCLUSIVE` lock per
table — does not block reads):

```sql
ANALYZE VERBOSE activity;
ANALYZE VERBOSE address;
ANALYZE VERBOSE enterprise;
ANALYZE VERBOSE establishment;
ANALYZE VERBOSE contact;
ANALYZE VERBOSE code;
ANALYZE VERBOSE branch;
```

Or one-shot for the whole DB (longer but simpler):

```sql
VACUUM ANALYZE;
```

Estimated runtime: ~5–10 min total. Data is not modified; only
`pg_statistic` is updated.

**Prevention:** the KBO loaders bulk-COPY into these tables and
sometimes skip the post-load `ANALYZE`. Suggest adding `ANALYZE
<table>;` to the end of `src/kbo_loader.py` and `src/kbo_updater.py`
post-commit.

---

## 2. Queue retention — three tables with high terminal-status backlog

| Queue | Active | Terminal (`done`+`excluded`) | Dead pct |
|---|---:|---:|---:|
| `staatsblad_bulk_queue` | 0 | 1,166,902 (`done`) + 21 (`failed`) | 11.6% |
| `staatsblad_llm_queue`  | 11 | 92,803 (`done`) + 680 (`failed`) | 13.4% |
| `enrichment_job` | 1,126,230 | 340,722 (`done`) + 127,057 (`excluded`) + 4 (`dead`) | 9.2% |

`done` rows in the staatsblad queues are pure history — the data they
produced lives elsewhere (`staatsblad_event`, `staatsblad_publication_text`).
`excluded` rows in `enrichment_job` document why a CBE was skipped
(legal-form filter etc.) — they are referenced by the worker before
re-queue, so **do not prune them**.

Recommended retention (after operator approval):

```sql
-- staatsblad_bulk_queue: keep last 30 days of done, drop the rest
DELETE FROM staatsblad_bulk_queue
WHERE status = 'done' AND finished_at < now() - interval '30 days';

-- staatsblad_llm_queue: keep last 30 days of done
DELETE FROM staatsblad_llm_queue
WHERE status = 'done' AND finished_at < now() - interval '30 days';

-- enrichment_job: ONLY done rows (NOT excluded). Keep last 90 days.
DELETE FROM enrichment_job
WHERE status = 'done' AND finished_at < now() - interval '90 days';

-- Reclaim space (offline VACUUM FULL would be faster but requires lock).
VACUUM (VERBOSE, ANALYZE) staatsblad_bulk_queue;
VACUUM (VERBOSE, ANALYZE) staatsblad_llm_queue;
VACUUM (VERBOSE, ANALYZE) enrichment_job;
```

Estimated reclaim: ~400–600 MB. Verify column names before running —
the schema may use `processed_at` / `completed_at` instead of
`finished_at`. Check with `\d <table>`.

**Long-term:** add a daily cron (e.g. `04:30 UTC`) that runs the same
`DELETE` with the same retention windows. Adding it to the existing
managed-cron block in `/var/spool/cron/crontabs/root` keeps it
visible alongside the other 18 jobs.

---

## 3. Unused indexes — 6 candidates for drop, 1 to investigate

`pg_stat_user_indexes.idx_scan = 0` since the last stats reset
(server was last rebooted 2026-04-17 per the disk-resize work).
Eleven days of zero scans is a strong unused signal but not
definitive — verify against `pg_stat_statements` before dropping.

**Safe to drop (clearly redundant with `company_info` materialised):**

| Index | Size | Notes |
|---|---:|---|
| `idx_activity_classification` | 269 MB | NACE filtering goes via `company_info.nace_code` |
| `idx_activity_nace`           | 228 MB | Same — duplicate path |
| `idx_establishment_enterprise`| 61 MB  | Verify no admin route uses establishment |
| `idx_actlog_time`             | 4.7 MB | Tier middleware uses `(user_email, created_at)` composite |
| `idx_activity_log_ua_date`    | 336 KB | Bot-filter middleware doesn't use it currently |
| `idx_branch_enterprise`       | 248 KB | Branches table is mostly inert |

Total reclaim: ~563 MB.

**INVESTIGATE before dropping (do NOT drop blindly):**

- `idx_ce_embedding_hnsw` — **2.56 GB**, on `company_embedding`. Zero
  scans is suspicious because `/api/search/semantic` is supposed to
  query this. Either:
  1. The route currently does sequential cosine scan (perf bug), or
  2. Stats reset happened after the last semantic query, or
  3. The route hits a different code path.

  Check `EXPLAIN (ANALYZE, BUFFERS) SELECT ... <-> '...'::vector ORDER
  BY ... LIMIT 10` against `company_embedding`. If the index isn't
  used, that's a separate perf bug, not an unused-index find.

---

## 4. Logs — already managed, one note

| Path | Size | Status |
|---|---:|---|
| `/var/log/postgresql` | 298 MB | rotated by `logrotate` |
| `/var/log/journal`    | 298 MB | rotated by `journald` |
| `/var/log/btmp`       | 15 MB  | failed-login log; growing |
| `/var/log/auth.log.1` | 11 MB  | rotated weekly |
| `/var/log/staatsblad-consumers` | 27 MB | bulk worker logs |

`btmp` at 15 MB indicates ongoing failed-login traffic on the public
SSH port. `fail2ban.log` at 1 MB suggests fail2ban is active and
catching them. Worth confirming fail2ban is configured for `sshd`
with a sensible ban window — but no code change needed.

No log retention policy is missing today. The Sunday `docker system
prune -af` cron handles container churn.

---

## 5. Code-only items addressed in this branch

- Deleted accidental `nul` file from repo root (Windows-redirect
  artifact containing a stale RunPod SSH host key).
- Added `nul`/`NUL`/`con`/`CON`/`prn`/`PRN`/`aux`/`AUX` to
  `.gitignore` to prevent recurrence on Git Bash / WSL.
- Updated `backend/routers/companies/search.py:170` TODO — the
  referenced `migrations/2026-04-26_address_trgm.sql` is applied
  (4 GIN trigram indexes confirmed on the `address` table).

---

## 6. Out-of-scope for this audit (explicit operator policy)

- **Auth on PII endpoints** (`/api/people/*`, `/api/companies/*/structure`,
  `/api/companies/*/network`, `/api/companies/*/extract-admins`,
  `/api/person/*/companies`). Per `docs/architecture.md` "Pending
  decisions" and `docs/tech-debt.md` Group A: operator chose
  tier-rate-limiting over auth-gating; implementation pending.
  Tier classifier was extended on 2026-04-23 to cover these paths.
- **Bulk export gate** on `/api/screener` (tech-debt CRITICAL #4).
- **Stripe redirect URL hardening** beyond the env-var default
  (tech-debt CRITICAL #2 partial fix landed 2026-04-23).
- **Bare `except Exception:`** sweep (~150 instances; tech-debt
  HIGH #11). Too large for an automated cleanup pass.

---

## Audit cross-check

Findings already addressed since the 2026-04-17 audit (verified
against current `master`):

- ✅ JWT `verify_aud=True` enforced (`backend/auth.py:103-106, 124`)
- ✅ JWT `kid` fallback to `keys[0]` removed (`backend/auth.py:168-183`)
- ✅ CSP header present (`nginx/default.conf:109`)
- ✅ `GET /api/polls` admin-gated (`backend/routers/polls.py:126`)
- ✅ Stripe redirect URL reads `FRONTEND_BASE_URL` env var
  (`backend/routers/stripe_pay.py:23`)
