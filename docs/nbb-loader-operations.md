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
works backwards from the most recent fiscal year to 2016.

**Schedule:** Two cron slots, both via `nbb_backload_cron.sh`:
```
0 2    * * *  MAX_CALLS=5000 PER_YEAR_CAP=3000 bash /opt/leadpeek/scripts/nbb_backload_cron.sh
0 6-22 * * *  MAX_CALLS=3000 PER_YEAR_CAP=3000 bash /opt/leadpeek/scripts/nbb_backload_cron.sh
```
Daytime runs are hourly but each takes ~82 min (3000 calls × 1.5 s/call), so
the host-side `flock` lock means only ~7–8 actually complete per day. Effective
throughput: **~26,000 API calls/day**.

**Year order:** `start_year` (2025) → `end_year` (2016), most recent first.
Older years are only reached once the recent year's candidate pool is exhausted.

**Log:** `/opt/leadpeek/scripts/_watchdog_state/nightly.log`

---

## Candidate selection — the critical logic

`candidates_for_year(fiscal_year, limit)` in `nbb_nightly_backload.py` decides
which companies to check. **Read this carefully before modifying.**

```sql
SELECT e.enterprise_number
FROM enterprise e
WHERE e.status = 'AC'
  AND e.type_of_enterprise = '2'          -- legal persons only
  AND e.juridical_form = ANY(...)         -- required-filer forms only (see below)
  AND NOT EXISTS (financial_by_year for this fiscal_year)
  AND NOT EXISTS (nbb_load_log NO_FILINGS or PDF_ONLY)
ORDER BY total_assets DESC NULLS LAST, enterprise_number
LIMIT %s
```

### KBO type_of_enterprise — counterintuitive!

Despite what the KBO schema doc says, the **actual data** is:
- `type_of_enterprise = '2'` → **legal persons** (NV, BV, VZW, etc.)
- `type_of_enterprise = '1'` → **natural persons** (sole traders, NULL juridical_form)

This is inverted from the written spec. Verified empirically: AB InBev
(NV/SA, definitely a legal person) has `type_of_enterprise = '2'`.

### Required-filer juridical forms (Tier 1 only)

Only these forms are checked. Everything else is excluded — they either never
file with NBB or file so rarely it wastes quota. ~786k companies total in KBO.

| Code | Form | KBO count | Notes |
|------|------|-----------|-------|
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
| + variants | publiek recht / sociaal oogmerk | small | |
| 027 | SE (Societas Europaea) | 14 | |

**Deliberately excluded:**
- `017` VZW/ASBL — only large non-profits file; added later if needed
- `070` VME (condominium associations) — never file with NBB CBSO
- `030` / `230` / `235` Foreign entities
- `124` / `301`–`420` Public bodies, government
- `026` Private foundations, `029` Public foundations
- `721` Entities without legal personality
- All other non-commercial forms

### NO_FILINGS / PDF_ONLY sentinels

When NBB returns an empty reference list for a company, it is marked
`NO_FILINGS` in `nbb_load_log`. This is **global and permanent** — the company
is excluded from ALL future year queries, not just the year being processed.
Companies with PDF-only model codes (m120/m211/m212) are marked `PDF_ONLY`.
Never delete these rows — doing so re-queues those companies for every year.

---

## NBB CBSO API — key facts

- **Base URL:** `https://ws.cbso.nbb.be`
- **Auth:** `NBB-CBSO-Subscription-Key` header (`NBB_AUTHENTIC_KEY` env var)
- **Rate limit:** 1.5 s between calls (`REQUEST_DELAY` in the script)
- **JSON/XBRL availability:** Only for filings with `end_date >= 2022-04-01`.
  Older filings exist in NBB but are PDF-only — the loader skips them.
  Going back to fiscal year 2016 in the backload is useful only for companies
  with unusual fiscal year-ends that push their filing date past April 2022.
- **`fiscalYear` query param is a no-op:** NBB always returns the full filing
  history regardless of the param. An empty response means the company has
  NO filings at all — not just none for that year.
- **401 response:** means the API key is revoked. The script stops immediately
  and lets the NBB watchdog (15-min cron) handle key rotation.
- **Per-visit efficiency:** When the script visits a company, it loads ALL
  available years in one API session. A company found as a candidate for FY2025
  will also have FY2024/2023/2022 loaded in the same visit.

---

## Coverage state (as of 2026-04-24)

| Fiscal year | Companies loaded |
|---|---|
| FY2026 | 162 (early filings) |
| FY2025 | 52,207 (growing daily via batch) |
| FY2024 | 143,388 |
| FY2023 | 143,773 |
| FY2022 | 144,715 |
| FY2021 and older | <100 (backload not yet reached) |

`financial_latest` (the materialised table used by screener): **176,424 rows**.

**Backload queue (remaining Tier 1 candidates per year):**
- FY2025: ~704k
- FY2024: ~612k (will collapse after FY2025 is done — same companies)
- FY2021–2016: ~755k each (but pre-April-2022 filings skipped anyway)

Estimated full Tier 1 coverage for FY2022–2025: **~3 months** at current pace
(~26k calls/day). The bottleneck is the first FY2025 pass which marks ~200–300k
dormant/newly-formed required filers as NO_FILINGS and clears them permanently.

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

**Rebuild trigger:** Both pipelines call `rebuild_materialized_tables()` after
loading. This takes ~2.5 min on the current DB size. Do not run concurrently.

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
/ `MAX_CALLS` / `PER_YEAR_CAP` here to adjust backload scope and speed.
The script is volume-mounted into the container, so a `git pull` on the server
is sufficient to deploy changes — no Docker rebuild needed.

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
| 2026-04-24 | Candidate query restricted to required-filer forms only — VZW, VME, foreign entities, public bodies excluded |
