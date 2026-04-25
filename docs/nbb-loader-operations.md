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

## Pipeline 2 — Historical backload (`nbb_nightly_backload.py`)

**Purpose:** Fills coverage gaps for companies that have never been loaded —
works backwards from the most recent fiscal year to 2022. Older fiscal years
are intentionally out of scope: the loader skips any filing with
`end_date < 2022-04-01` (NBB only publishes JSON-XBRL from April 2022 onward),
so probing FY2021 and earlier burns API quota for zero data.

**Schedule:** Two cron slots, both via `nbb_backload_cron.sh`:
```
*/30 6-22 * * *  MAX_CALLS=3500 PER_YEAR_CAP=3500 SKIP_REBUILD=1 bash /opt/leadpeek/scripts/nbb_backload_cron.sh
0 2    * * *     MAX_CALLS=5000 PER_YEAR_CAP=5000 SKIP_REBUILD=0 bash /opt/leadpeek/scripts/nbb_backload_cron.sh
```

- **Daytime:** Runs every 30 minutes, 06:00–22:00. Each run is 3,500 calls × 1.25 s/call ≈ 73 min.
  The host-side `flock` lock means only ~2 runs complete per hour (one finishes before the
  next start, the other start is skipped). Roughly 26–28 daytime run-slots complete per day.
- **Nightly:** 02:00 run with 5,000 calls and full materialized table rebuild.
- **Skip-rebuild on daytime:** Daytime runs pass `--skip-rebuild` so they don't spend 2.5 min
  on a rebuild that the next run would immediately undo. The nightly 02:00 run always rebuilds,
  so screener data is fresh by morning.
- **Effective throughput:** ~35,000 API calls/day.

**Year order:** `start_year` (2025) → `end_year` (2022), most recent first.
Older years are only reached once the recent year's candidate pool is exhausted.
FY2021 and earlier are not backfilled — see purpose note above.

**Log:** `/opt/leadpeek/scripts/_watchdog_state/nightly.log`

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
  AND NOT EXISTS (nbb_load_log NO_FILINGS% or PDF_ONLY)
ORDER BY (SELECT total_assets FROM financial_latest WHERE enterprise_number = e.enterprise_number)
         DESC NULLS FIRST, enterprise_number
LIMIT %s
```

`NULLS FIRST` is intentional: companies with no prior financial data come
**first** in the queue. These are the unknown companies we want to discover most.
Companies already in `financial_latest` (with known assets) follow after, ordered
by size.

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

## Required-filer juridical forms (Tier 1)

Only the following forms are checked. Everything else is excluded — they either never
file with NBB or file so rarely it wastes quota. The Tier 1 universe is ~787k
active companies in KBO.

| Code | Form | KBO count (approx) | Notes |
|------|------|--------------------|-------|
| 610 | BV (Besloten Vennootschap) | 523k | New form since 2019. **Biggest group.** |
| 014 | NV (Naamloze Vennootschap) | 79k | |
| 015 | BVBA (legacy BV form) | 77k | Being phased out post-2019 |
| 612 | CommV (Commanditaire vennootschap) | 51k | |
| 011 | VOF (Vennootschap onder firma) | 25k | |
| 012 | GewComV (old CommV form) | 15k | |
| 016 | CV oud statuut | 7k | |
| 008 | CVBA | 4k | |
| 006 | CVOA | 3k | |
| 706 | CV (new form) | 2k | |
| 013 | CommVA | 295 | |
| 065 | EESV | 269 | |
| 060 | ESV | 128 | |
| 508 | CVBA met sociaal oogmerk | 88 | |
| 114 | NV van publiek recht | 76 | |
| 616 | BV van publiek recht | 75 | |
| 615, 614, 515, 010, 108, 116, 716 | Sociaal oogmerk / publiek recht variants | small | |
| 001 | Europese Coöperatieve Vennootschap | small | |
| 027 | SE (Societas Europaea) | 14 | |

**Deliberately excluded:**
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
| `/opt/leadpeek/scripts/_watchdog_state/nightly.log` | Backload cron |
| `/var/log/nbb_backfill.log` | One-off backfill runs (manual) |
| `/var/log/nbb_continuous.log` | **Dead** — old continuous loader, crashed 2026-04-15 during disk incident, not restarted (replaced by cron-based backload) |

---

## Cron config location

`/opt/leadpeek/scripts/nbb_backload_cron.sh` — edit `START_YEAR` / `END_YEAR`
/ `MAX_CALLS` / `PER_YEAR_CAP` / `SKIP_REBUILD` here to adjust backload scope and speed.
The script is volume-mounted into the container, so a `git pull` on the server
is sufficient to deploy changes — no Docker rebuild needed.

The actual cron entries live in `crontab -e` on the server host (not in the repo).
Current entries:
```
*/30 6-22 * * * MAX_CALLS=3500 PER_YEAR_CAP=3500 SKIP_REBUILD=1 bash /opt/leadpeek/scripts/nbb_backload_cron.sh
0 2 * * *      MAX_CALLS=5000 PER_YEAR_CAP=5000 SKIP_REBUILD=0 bash /opt/leadpeek/scripts/nbb_backload_cron.sh
0 4 * * *      docker exec -e PYTHONPATH=/app leadpeek-backend-1 python /app/scripts/backfill_affiliation.py --max-filings 5000   # affiliation catch-up for pre-inline-extraction filings
```

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
