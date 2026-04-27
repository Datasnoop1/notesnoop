# NBB Loader — Operations & Architecture

Reference doc for new context windows. Read this before touching anything
related to NBB data loading, the backfill pipeline, or `financial_data`.

---

## What the NBB loader does

Pulls annual account filings from the **NBB CBSO API** (Belgium's National Bank
filing registry) and stores them in `financial_data`. Two separate pipelines
handle this — daily batch for new filings, backload for historical gap-fill.

---

## Pipeline 1 — Daily batch (`nbb_batch_pipeline.py`)

**Purpose:** Picks up every filing published by NBB on the previous calendar day.

**Schedule:** Cron at `01:00` daily.
```
0 1 * * * docker exec leadpeek-backend-1 python nbb_batch_pipeline.py >> /var/log/nbb_batch.log 2>&1
```

**How it works:**
1. Downloads the previous day's NBB extract ZIP via the NBB CBSO bulk extract API
2. Iterates all filing references in the extract
3. Skips references already in `nbb_load_log`
4. Fetches and stores new filings into `financial_data`
5. Rebuilds `financial_latest` and `financial_by_year` materialised tables
6. Refreshes `sector_percentiles`

**Log:** `/var/log/nbb_batch.log`

**Typical output (healthy run):**
```
Date 2026-04-23: 1070 filings loaded, 122742 rubrics, 1 skipped, 0 errors
Materialized tables rebuilt in 157s — financial_latest: 176424 rows
```

**Known gap:** The extract API requires `NBB_EXTRACT_KEY`. If that env var is
missing the run logs `ERROR: NBB_EXTRACT_KEY not set` and skips. The
`NBB_AUTHENTIC_KEY` (used by the backloader and on-demand profile loads) is a
separate credential.

---

## Pipeline 2 — Historical backload (`nbb-backload-worker` service)

**Purpose:** Fills coverage gaps for companies that have never been loaded —
works backwards from the most recent fiscal year to 2022. Older fiscal years
are intentionally out of scope: the loader skips any filing with
`end_date < 2022-04-01` (NBB only publishes JSON-XBRL from April 2022 onward),
so probing FY2021 and earlier burns API quota for zero data.

**Runtime:** Long-running container (`nbb-backload-worker` service in
`docker-compose.yml`) — same image as `backend`, but runs an infinite loop:

```
scripts/nbb_backload_loop.sh
  → python /app/scripts/nbb_nightly_backload.py
        --max-calls 3500 --per-year-cap 3500 --skip-rebuild
  → sleep 30 s
  → repeat
```

Each iteration takes ~73 min (3,500 calls × 1.25 s/call), so the daemon
runs near-continuously (~19 iterations/day = ~67k API calls/day theoretical
ceiling, well above the older cron-based ~35k/day target).

If an iteration finishes in under 5 min — meaning the script tripped 401
(key revocation), 429 (rate-limit), or an empty queue — the daemon sleeps
`BACKLOAD_BACKOFF_S` (default 600 s) before retrying, so we don't spam
NBB during outages or while waiting for the watchdog to rotate keys.

**Why a daemon, not cron?** The previous design (`docker exec leadpeek-backend-1`
fired by cron) was SIGKILLed every time auto-deploy rebuilt the backend
container, losing up to a full 73-min run on every push to master.
The worker container is independent of `backend` and `frontend`, so deploys
no longer interrupt it — same isolation pattern as `enrichment-worker` and
`staatsblad-bulk-worker`.

**Materialised-table rebuild:** Always runs in the daily 01:00 batch
(`nbb_batch_pipeline.py`). The daemon always passes `--skip-rebuild`.

**Year order:** `BACKLOAD_START_YEAR` (default 2025) → `BACKLOAD_END_YEAR`
(default 2022), most recent first. Older years are only reached once the
recent year's candidate pool is exhausted. FY2021 and earlier are not
backfilled — see purpose note above.

**Tunables (env vars on the `nbb-backload-worker` service):**

| Var | Default | Notes |
|---|---|---|
| `BACKLOAD_MAX_CALLS` | 3500 | Per-iteration call budget |
| `BACKLOAD_START_YEAR` | 2025 | Reverse-chrono start year |
| `BACKLOAD_END_YEAR` | 2022 | Reverse-chrono end year |
| `BACKLOAD_PER_YEAR_CAP` | 3500 | Per-fiscal-year cap per iteration |
| `BACKLOAD_SLEEP_S` | 30 | Sleep between normal iterations |
| `BACKLOAD_BACKOFF_S` | 600 | Sleep after a short (<5 min) iteration |

**Logs:** `docker logs leadpeek-nbb-backload-worker-1`. The legacy
`/opt/leadpeek/scripts/_watchdog_state/nightly.log` is no longer written —
historical entries from the cron era stay there for reference.

---

## Candidate selection — the critical logic

`candidates_for_year(fiscal_year, limit)` in `nbb_nightly_backload.py` decides
which companies to check. **Read this carefully before modifying.**

```sql
SELECT e.enterprise_number
FROM enterprise e
WHERE e.status = 'AC'
  AND e.type_of_enterprise = '2'          -- legal persons only (see KBO inversion note below)
  AND e.juridical_form = ANY(...)         -- required-filer forms only (see below)
  AND NOT EXISTS (financial_by_year for this fiscal_year)
  AND NOT EXISTS (nbb_load_log NO_FILINGS% or PDF_ONLY or NO_NEW_FILINGS)
ORDER BY (SELECT total_assets FROM financial_latest WHERE enterprise_number = e.enterprise_number)
         DESC NULLS LAST, enterprise_number
LIMIT %s
```

**Priority — known filers first.** `NULLS LAST` puts companies that already
have a row in `financial_latest` (i.e. they've filed with NBB at least once
in a prior year) at the **front** of the queue, ordered by total assets
descending. Unknowns — companies in KBO that have never filed JSON-XBRL
with NBB — are queued behind. Rationale: a known filer is much more likely
to have already filed FY-current than a random unknown, so we land NEW data
faster by hitting them first. Empirically (2026-04-27 distribution): ~127k
FY2025-missing known filers vs ~571k FY2025-missing unknowns; the first
~5 days of daemon time goes into the known-filer pool.

This was previously `NULLS FIRST` (2026-04-24 → 2026-04-27) when the
unknown pool was still rich in easy wins. After that pool depleted into a
long tail of "registered but doesn't actually file FY-current" companies,
runs were producing 0 loads / >1000 `no_new_filings` — which is what
prompted the flip. See change history below.

---

## KBO type_of_enterprise — counterintuitive!

Despite what the KBO schema doc says, the **actual data** is:
- `type_of_enterprise = '2'` → **legal persons** (NV, BV, VZW, etc.)
- `type_of_enterprise = '1'` → **natural persons** (sole traders, NULL juridical_form)

This is inverted from the written spec. Verified empirically: AB InBev
(NV/SA, definitely a legal person) has `type_of_enterprise = '2'`.

**The backload uses `'2'`.**  Using `'1'` (the mistake made before 2026-04-24) queries
sole traders who never file with NBB and produces 0 loaded companies.

---

## Juridical-form yield — Tier 1 (primary) vs Tier 2 (deferred)

Although KBO classifies many forms as "required filers", the actual NBB
filing rate varies enormously between forms. Per the 2026-04-27 measurement
(% of active KBO companies that have any row in `financial_latest`):

### Tier 1 — primary backload set (~685k active KBO companies)

Forms with empirical filing rates ≥10%, OR small populations with clean
signal. These are what `candidates_for_year` checks today.

| Code | Form | KBO active | % filed | Notes |
|------|------|-----------:|--------:|-------|
| 014 | NV (Naamloze Vennootschap) | 79k | **65.6%** | Highest yield. |
| 610 | BV (Besloten Vennootschap) | 523k | **20.2%** | Biggest pool — the bulk of the work is here. |
| 015 | BVBA (legacy BV form) | 77k | 26.2% | Being phased out post-2019 |
| 008 | CVBA | 4k | 30.3% | |
| 706 | CV (new form) | 2k | 33.9% | |
| 716 | CV van publiek recht | 8 | 87.5% | Tiny but clean |
| 013 | CommVA | 295 | 61.7% | |
| 114 | NV van publiek recht | 76 | 61.8% | |
| 108 | CVBA van publiek recht | 6 | 83.3% | |
| 508 | CVBA met sociaal oogmerk | 88 | 14.8% | |
| 027 | SE (Societas Europaea) | 14 | 14.3% | |
| 615, 614, 616, 010, 515 | Sociaal oogmerk / publiek recht variants | small | mixed | Kept as small-pop catch-alls |

### Tier 2 — deferred (~101k active KBO companies)

Forms whose empirical filing rate is so low (0.3–10%) that backloading
them burns API quota for trickle yield. They sit in a `TIER_2_DEFERRED_FORMS`
constant in the script and are NOT included in the primary candidate query.
To run a one-off backfill on these once the primary set is complete, set
`NBB_BACKLOAD_TIER2=1` on the `nbb-backload-worker` service (in the env or
`docker compose run`) — the script will then add the Tier 2 codes to the
candidate-form list and log a warning at start-up so it's obvious the
expanded set is in effect.

| Code | Form | KBO active | % filed | % NO_FILINGS confirmed |
|------|------|-----------:|--------:|-----------------------:|
| 612 | CommV (Commanditaire vennootschap) | 51k | **0.3%** | 2.3% sampled |
| 011 | VOF (Vennootschap onder firma) | 25k | **0.4%** | 8.8% sampled |
| 012 | GewComV (old CommV form) | 15k | **0.3%** | 10.7% sampled |
| 016 | CV oud statuut | 7k | 2.3% | **97.6%** confirmed non-filer |
| 006 | CVOA | 3k | 2.0% | 60.8% confirmed non-filer |
| 060, 065 | ESV / EESV | <0.5k | 9% | ~30–40% confirmed non-filer |
| 116 | CV oud publiek recht | small | 5.3% | |
| 001 | Europese Coöperatieve Vennootschap | small | 0% | |

### Deliberately excluded entirely

- `017` VZW/ASBL — only large non-profits file; added later if needed
- `070` VME (condominium associations) — never file with NBB CBSO
- `030` / `230` / `235` Foreign entities
- `124` / `301`–`420` Public bodies, government
- `026` Private foundations, `029` Public foundations
- `721` Entities without legal personality
- All other non-commercial forms

---

## NO_FILINGS / PDF_ONLY sentinels

When NBB returns an empty reference list for a company, it is marked
`NO_FILINGS` in `nbb_load_log`. This is **global and permanent** — the company
is excluded from ALL future year queries, not just the year being processed.

This is correct because the NBB `fiscalYear` query param is a no-op: NBB always
returns the full filing history regardless of the param. An empty response means
the company has NO filings at all — not just none for that year.

Companies with PDF-only model codes (m120/m211/m212) are marked `PDF_ONLY`.

**Never delete these rows** — doing so re-queues those companies for every year,
wasting API quota on companies that will never produce data.

---

## NBB CBSO API — key facts

- **Base URL:** `https://ws.cbso.nbb.be`
- **Auth:** `NBB-CBSO-Subscription-Key` header (`NBB_AUTHENTIC_KEY` env var)
- **Rate limit:** 1.25 s between calls (`REQUEST_DELAY` in the script)
- **JSON/XBRL availability:** Only for filings with `end_date >= 2022-04-01`.
  Older filings exist in NBB but are PDF-only — the loader skips them. This is
  why the backload is capped at fiscal year 2022; probing 2021 or earlier
  candidate pools just burns quota on filings that will be skipped anyway.
- **`fiscalYear` query param is a no-op:** NBB always returns the full filing
  history regardless of the param. An empty response means the company has
  NO filings at all — not just none for that year.
- **401 response:** means the API key is revoked. The script stops immediately
  and lets the NBB watchdog (15-min cron) handle key rotation.
- **429 response:** rate limit hit — script stops the run cleanly.
- **Per-visit efficiency:** When the script visits a company, it loads ALL
  available years in one API session. A company found as a candidate for FY2025
  will also have FY2024/2023/2022 loaded in the same visit. This means FY2024
  candidates will collapse dramatically once the FY2025 pass is complete.

---

## Coverage state (as of 2026-04-24)

| Fiscal year | Companies loaded |
|---|---|
| FY2026 | 162 (early filings) |
| FY2025 | 52,207 (growing daily via batch) |
| FY2024 | 143,388 |
| FY2023 | 143,773 |
| FY2022 | 144,715 |
| FY2021 and older | <100 (out of scope — backload caps at FY2022) |

`financial_latest` (the materialised table used by screener): **176,424 rows**.

**Backload queue (remaining Tier 1 candidates per year, approx):**
- FY2025: ~704k remaining
- FY2024: ~612k (will collapse after FY2025 pass — same companies)
- FY2023 / FY2022: side-effect coverage from FY2025/FY2024 visits (NBB returns full history per call)
- FY2021 and earlier: out of scope (pre-April-2022 filings are PDF-only)

**ETA for full Tier 1 FY2024/FY2025 coverage:** ~30 days from 2026-04-24, i.e. late May 2026.
At ~35,000 calls/day with ~50-60% hit rate (remainder NO_FILINGS), effective
new-company load rate is ~17,000–21,000 per day.

---

## Governance data — loaded inline with every filing

Both pipelines (daily batch and backload) call `store_filing()` per filing, which
in turn calls `store_governance_snapshot()` (`backend/nbb_governance.py`)
immediately after the rubric insert is committed. The governance write runs in a
**separate transaction** and is wrapped in a `try/except` that logs and continues
on failure, so a governance write error never rolls back the rubric data.
Result: every filing the loader touches also writes governance rows for that
filing (best-effort).

`store_governance_snapshot()` populates four tables:

| Table | What it stores | Approx scale |
|---|---|---|
| `administrator` | Directors and Representatives extracted from the filing's governance section | ~1.09M rows; ~140k distinct companies/year for FY2022–2024 |
| `shareholder` | Shareholder snapshot per filing | populated alongside |
| `participating_interest` | Equity participations declared in the filing | populated alongside |
| `affiliation` | Natural persons behind **legal-person** administrators (i.e. when a director is itself a company, the natural person who represents it) | small (~1k rows). Rare pattern: only fires when an admin is a legal entity. |

The `affiliation` block has a guard — `_affiliation_table_exists()` — so older
deployments without the migration applied skip silently rather than aborting
the whole governance write. On prod the table is present, so affiliations are
written inline.

### Affiliation catch-up cron (separate from the backload)

For filings loaded **before** the inline affiliation extraction was added to
`store_governance_snapshot()`, a nightly catch-up walks the already-loaded
deposit history and extracts affiliations from filings that had legal-person
admins but no affiliation rows.

```
0 4 * * * docker exec ... python /app/scripts/backfill_affiliation.py --max-filings 5000
```

Tracked in `affiliation_backfill_log` so re-runs never repeat work. **Not
redundant** with the inline path — only catches up historical filings; new
filings loaded going forward already get their affiliations inline.

---

## Database tables

| Table | Purpose |
|---|---|
| `financial_data` | Raw rubric rows: `(enterprise_number, deposit_key, fiscal_year, rubric_code, value)` |
| `nbb_load_log` | One row per deposit loaded, or sentinel `NO_FILINGS`/`PDF_ONLY` per company |
| `financial_latest` | Materialised: one row per company, most recent year's key figures |
| `financial_by_year` | Materialised: one row per (company, fiscal_year) |
| `financial_summary` | View: pivoted P&L / BS figures |
| `sector_percentiles` | Materialised: NACE-level percentile bands, used for benchmarking |
| `administrator` | Governance: directors / representatives per filing (loaded inline by `store_governance_snapshot`) |
| `shareholder` | Governance: shareholder snapshot per filing |
| `participating_interest` | Governance: equity participations per filing |
| `affiliation` | Governance: natural-person representatives behind legal-person admins (inline + nightly catch-up cron) |
| `affiliation_backfill_log` | Tracks which filings the affiliation catch-up cron has already processed |

**Rebuild trigger:** The nightly 02:00 run and the daily batch both call
`rebuild_materialized_tables()` after loading. This takes ~2.5 min on the current DB size.
Daytime backload runs skip rebuild (`--skip-rebuild`) to avoid blocking overlap.

---

## Log files

| File | Pipeline |
|---|---|
| `/var/log/nbb_batch.log` | Daily batch |
| `docker logs leadpeek-nbb-backload-worker-1` | Backload daemon (live) |
| `/opt/leadpeek/scripts/_watchdog_state/nightly.log` | **Dead** — backload cron-era log, kept for reference |
| `/var/log/nbb_backfill.log` | One-off backfill runs (manual) |
| `/var/log/nbb_continuous.log` | **Dead** — old continuous loader, crashed 2026-04-15 during disk incident |

---

## Configuration location

The backload daemon's behaviour is controlled by env vars on the
`nbb-backload-worker` service in `docker-compose.yml` (see Tunables table
above). Loop body lives in `scripts/nbb_backload_loop.sh`, mounted
read-only into the container — `git pull` on the server picks up loop
changes; tunable changes require a `docker compose up -d nbb-backload-worker`
to recreate the service with new env values.

The remaining NBB-related cron entries live in `crontab -e` on the server
host (not in the repo):
```
0 1 * * * docker exec leadpeek-backend-1 python nbb_batch_pipeline.py >> /var/log/nbb_batch.log 2>&1
0 4 * * * docker exec -e PYTHONPATH=/app leadpeek-backend-1 python /app/scripts/backfill_affiliation.py --max-filings 5000   # affiliation catch-up for pre-inline-extraction filings
*/15 * * * * cd /opt/leadpeek && bash scripts/nbb_watchdog.sh >> scripts/_watchdog_state/cron.log 2>&1
```

The two backload cron entries (`*/30 6-22` and `0 2`) were removed when the
daemon shipped — see change history below.

---

## History of significant changes

| Date | Change |
|---|---|
| 2026-04-15 | Old continuous loader (`nbb_loader_hetzner.py`) died during disk-full incident; replaced by cron-based backload |
| 2026-04-19 | Backfill run patched the gap for 2026-04-10 to 2026-04-17 (disk incident window) |
| 2026-04-24 | **Bug fix:** backload was querying `type_of_enterprise = '1'` (natural persons / sole traders) — zero NBB filings. Fixed to `'2'` (legal persons). |
| 2026-04-24 | **Bug fix:** juridical form priority had 610=VZW and 017=BV — exactly reversed. Fixed from KBO code table: 610=BV, 017=VZW. |
| 2026-04-24 | Backload scope extended from end_year=2022 to end_year=2016 |
| 2026-04-24 | start_year bumped to 2025 (FY2025 now has meaningful volume) |
| 2026-04-24 | Candidate query restricted to required-filer forms only — VZW, VME, foreign entities, public bodies excluded (~480k non-filer companies removed from queue) |
| 2026-04-24 | REQUEST_DELAY reduced 1.5s → 1.25s (~20% faster per call) |
| 2026-04-24 | Daytime cron frequency increased from hourly to every 30 min |
| 2026-04-24 | MAX_CALLS per daytime run increased from 3,000 → 3,500 |
| 2026-04-24 | `--skip-rebuild` flag added; daytime runs skip materialized table rebuild; nightly 02:00 run always rebuilds |
| 2026-04-24 | ORDER BY changed from `total_assets DESC NULLS LAST` → `NULLS FIRST` — unknown companies now queued first |
| 2026-04-24 | Combined throughput improvement: ~26,000 → ~35,000 API calls/day (+35%) |
| 2026-04-25 | Backload scope contracted from end_year=2016 back to end_year=2022. Pre-April-2022 filings are PDF-only and skipped by the loader, so older candidate pools were burning quota for zero gain. |
| 2026-04-25 | Doc clarified: the backload populates governance tables (`administrator`, `shareholder`, `participating_interest`, `affiliation`) inline via `store_governance_snapshot()` for every filing — not just `financial_data`. The 04:00 `backfill_affiliation.py` cron is a catch-up for filings loaded before inline extraction existed, not part of normal flow. |
| 2026-04-27 | **Crontab cleanup:** removed two duplicate pre-2026-04-24 backload entries (`0 2 * * * MAX_CALLS=5000 PER_YEAR_CAP=3000` and `0 6-22 * * * MAX_CALLS=1500 PER_YEAR_CAP=1500`) that were colliding with the post-04-24 entries via `flock` and starving the half-hour drip-feed. Backup: `/opt/leadpeek/scripts/_watchdog_state/crontab.bak.20260427T152633Z`. |
| 2026-04-27 | **Backload moved from cron to long-running daemon (`nbb-backload-worker` service).** Cron-fired `docker exec leadpeek-backend-1` was being SIGKILLed every time auto-deploy rebuilt the backend container (~1 hour of in-progress run lost per push). New service runs `scripts/nbb_backload_loop.sh` continuously, isolated from backend rebuilds — same pattern as `enrichment-worker` / `staatsblad-bulk-worker`. Both backload cron entries removed. |
| 2026-04-27 | **Priority flipped: known filers first.** ORDER BY changed from `total_assets DESC NULLS FIRST` → `NULLS LAST`. Companies already in `financial_latest` (proven NBB filers in a prior year) now sit at the front of the queue; unknowns follow. The previous policy (unknowns first) was rational while the unknown pool was rich, but by 04-27 the front of the queue had degraded into a long tail of registered-but-non-filing companies; recent runs were producing 0 loads / >1000 `no_new_filings`. ~127k FY2025-missing known filers now go first, then ~571k unknowns. |
| 2026-04-27 | **Tier 2 forms dropped from primary backload.** `REQUIRED_FILER_FORMS` tightened from 25 → 16 juridical-form codes. Removed `612` CommV (51k active, 0.3% filing rate), `011` VOF (25k, 0.4%), `012` GewComV (15k, 0.3%), `016` CV oud statuut (7k, 97.6% confirmed non-filer), `006` CVOA, `060`/`065` ESV/EESV, `116`, `001`. Total active-KBO pool drops ~101k companies. The deferred forms are documented as `TIER_2_DEFERRED_FORMS` for a future one-off backfill, but don't burn primary-pass quota. See Juridical-form yield table above. |
