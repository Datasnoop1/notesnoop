# Search (V2) — how it works

Last updated: 2026-04-24. This doc is the canonical reference for the
DataSnoop name / company / people search. Read this before touching any
search router, the DDL, or the frontend search surfaces — it saves
re-deriving all the constraints from code.

If you only read one section, read **"Mental model in 30 seconds"**.

---

## Mental model in 30 seconds

A user types free text in either the **header search bar** (every page
except landing and `/search` itself) or the **big input on `/search`**.

That text fans out to up to four public endpoints:

| Endpoint | Purpose | Typical latency |
|---|---|---|
| `GET /api/companies/search?q=…` | Companies — scored, bucketed into `commercial` and `nonprofit_or_public`. | 200–700 ms |
| `GET /api/people/search?q=…` | Directors, shareholders, Staatsblad-mentioned persons — scored. | 100–300 ms |
| `GET /api/staatsblad/events/search?q=…` | Recent Belgian Gazette events matching the text. | <50 ms |
| `GET /api/search/suggest?q=…` | Grouped autocomplete (companies + people + CBE + addresses) for the header dropdown. | <20 ms |

Every endpoint hits **Postgres with `pg_trgm` + `unaccent` +
`fuzzystrmatch`**. No Elasticsearch, no Meilisearch — pure Postgres
keeps the stack simple and the scale (~170 K active companies, ~1 M
admin rows) comfortable.

The three underlying data sources are KBO open-data, NBB XBRL filings,
and the Belgian Staatsblad OCR pipeline. All three feed the same
search tables; the search routers union across them.

---

## Data sources that feed the search

### 1. NBB XBRL filings (`backend/nbb_governance.py`)

**Biggest source. ~99.97 % of our admin data.**

`extract_governance_snapshot()` parses every NBB XBRL filing we ingest
and pulls out:

- `Administrators.NaturalPersons` → rows in `administrator` with
  `person_type='natural'`, `deposit_key=<NBB reference>`, full
  `FirstName LastName`, role (`fct:m10`…`fct:m40`), mandate dates.
- `Administrators.LegalPersons` → `administrator` with
  `person_type='legal'`, entity name, KBO identifier.
- `Shareholders.EntityShareHolders` + `IndividualShareHolders` →
  `shareholder` table.
- `ParticipatingInterests` → `participating_interest`.

Called from the nightly NBB backload (`scripts/nbb_nightly_backload.py`
via `scripts/nbb_backload_cron.sh`) and the hourly daytime drip-feed
(`0 6-22 * * *`).

**Coverage gap**: entities not required to file annual accounts don't
appear here. Small Commanditaire vennootschappen (`juridical_form=612`)
under the revenue / FTE threshold file nothing and therefore have no
admin rows from NBB.

### 2. KBO open-data (`src/kbo_loader.py`, `kbo_updater.py`)

Small residual (~265 rows in `administrator`). KBO publishes
structured director data for only a subset of legal forms — newer
entities and partnerships are frequently blank. Not relied on as the
primary admin source.

What we DO get from KBO: every `enterprise` row, every `company_info`
row (with `name`, `city`, `nace_code`, `zipcode`), every `denomination`
(trade names + alt names), every `address`. These are foundational —
without them the NBB admin rows couldn't be joined back to company
names.

Daily update at 03:00 UTC (`scripts/daily_update.sh`).

### 3. Staatsblad OCR pipeline (`backend/staatsblad_extraction/`)

Scrapes the Belgian Official Gazette daily, OCRs the PDFs, and runs
them through an Anthropic batch extractor (`prompt_v3.py`) that pulls
structured events. Those land in `staatsblad_event` rows with:

- `event_type='admin_event'` — appointments, resignations, etc.
- `person_name`, `person_role`, `entity_name`
- **New (2026-04-24)** `person_domicile_street` / `_house_number` /
  `_postcode` / `_city` / `_raw` / `_confidence` / `_extracted_at` —
  the person's home address as parsed from the publication text.
  Progressively populated by a re-extraction cron running under the
  `prompt_v3` extractor; rows touched by older prompts have these
  columns NULL until the cron gets to them.

Runs every 2 days via `staatsblad_batch_every_2d.py`. Embeddings
generated nightly by `staatsblad_embed.py` at 05:45 UTC.

**Used in search for**: (a) supplementing the admin data with events
the NBB hasn't captured yet, (b) providing authoritative person
domiciles for common-name disambiguation.

---

## Normalisation contract

The whole search stands on a single normalisation function, implemented
twice (once in SQL, once in Python) and kept byte-compatible.

### SQL side — `migrations/2026-04-24_search_v2.sql`

Extensions enabled: `unaccent`, `fuzzystrmatch`, `pg_trgm`.

Immutable helpers:

- `f_unaccent(text)` — wraps `unaccent()` in an IMMUTABLE function
  so it can appear in generated columns and expression indexes.
- `search_normalize(text)` — accent-strip, lowercase, strip trailing
  Belgian + foreign legal suffixes (NV, SA, BV, SPRL, SRL, CVBA,
  SCRL, VOF, SNC, SE, SCS, Comm.V, ASBL, VZW, AISBL, IVZW, GmbH,
  AG, Ltd, Inc, SAS, SARL, LLC, PLC, Corp, SpA, KG, OHG, UG, EURL),
  collapse whitespace. Trailing-anchor only — never kills leading
  "NV" in names like "NVidia".
- `search_name_reversed(text)` — sorted-tokens form. "Tim Braet" and
  "Braet Tim" both return "braet tim". Used for order-agnostic
  people matching.
- `search_phonetic_key(text)` — `dmetaphone` per token, space-joined.
  "Braet" / "Braete" / "Brait" collide on `FK HS`.

### Stored generated columns

Every search-relevant table has a STORED generated column for each of
the three derivatives:

| Table | Column | Source |
|---|---|---|
| `company_info` | `name_normalized` | `search_normalize(name)` |
| `administrator` | `name_normalized`, `name_reversed`, `name_phonetic` | from `name` |
| `shareholder` | same three | from `name` |
| `staatsblad_event` | `person_name_normalized`, `person_name_reversed`, `person_name_phonetic` | from `person_name` |
| `denomination` | `denomination_normalized` | from `denomination` |

GIN trigram index on every normalised and reversed column, plus a
btree prefix index on `company_info.name_normalized` for fast
`LIKE 'foo%'` prefix lookups.

### Reference data

- `juridical_form_category` — 146-row seed mapping every KBO juridical
  form code to one of `commercial | nonprofit | public | other`.
  Drives the two-bucket split in company search responses.
- `legal_form_synonyms` — 35 bidirectional mappings (NV↔SA,
  BV↔SPRL↔SRL, VZW↔ASBL, CVBA↔SCRL, plus GmbH / Ltd / Inc / SAS /
  SARL / EURL / SpA for paste-from-CRM tolerance). Loaded into a
  Python module cache at FastAPI startup (`backend/main.py`
  lifespan hook calls `search_normalization.set_synonyms_cache`).
- `company_popularity` — nightly-refreshed 28-day click count from
  `activity_log`. Multiplies the final score so trending companies
  rank higher. Refreshed by `scripts/refresh_popularity.py` at
  03:15 UTC.

### Python side — `backend/search_normalization.py`

Public API:

- `normalize_name(s)` — mirrors SQL `search_normalize`. Iterative
  multi-suffix stripping (up to 4 iterations) so "Acme NV SA" → "acme".
- `tokenize(s)`, `reversed_key(s)`, `phonetic_key(s)` — mirror the
  SQL helpers.
- `detect_query_type(q)` → `"cbe" | "zipcode" | "person_like" |
  "company_like"`. Regex router; drives which SQL path fires.
- `extract_cbe_digits(q)` — tolerates "BE 0403.170.701", "403170701",
  "0403-170-701" etc. Returns the canonical 10-digit form.
- `ilike_escape(s)` — escapes `%`, `_`, `\` so user-supplied tokens
  don't become wildcards (security + perf; a `%%%%` query previously
  fan-scanned the whole table).

---

## `/api/companies/search` — how it ranks

Single scored CTE in `backend/routers/companies/search.py::_SEARCH_SQL`.
Six candidate arms `UNION ALL`-ed, dedup by `enterprise_number` with
`MAX(base)`, then a composite score multiplier:

```
final_score = base
            * (1 + 0.15 * log10(max(10, revenue+10)))   -- size boost
            * CASE status WHEN 'AC' THEN 1.0 ELSE 0.3 END
            * (1 + 0.10 * min(1.0, click_count / 50.0)) -- popularity
```

### Base scores by arm

| Arm | Base | Condition |
|---|---|---|
| `exact_match` | 1.00 | `name_normalized = :nq` |
| `denom_exact` | 0.85 | `denomination_normalized = :nq` (covers trade names like "Viconco" where `company_info.name` is blank) |
| `prefix_match` | 0.70 | `name_normalized LIKE :nq || '%'` |
| `token_and` | 0.50 | every typed token is a substring of `name_normalized` (up to 4 tokens, AND-ed) |
| `denom_fuzzy` | 0.40 | trigram similarity on `denomination_normalized` > 0.45, query ≥ 4 chars |
| `trigram_match` | 0.00–0.40 | trigram similarity on `name_normalized` > 0.35, query ≥ 4 chars, capped linearly |
| `addr_match` | 0.20 | street / municipality / zipcode ILIKE on `address` (REGO), query ≥ 6 chars, no person_like qtype |

**Short-prefix gates**: `denom_*`, `trigram_match`, and `addr_match`
all require `length(nq) >= 4` (addr >=6) to avoid fan-out on 2-char
prefixes.

### CBE short-circuit

If `detect_query_type` returns `"cbe"`, the router bypasses the scored
CTE entirely and runs `_CBE_SQL`, a fast `enterprise_number LIKE :pfx`
prefix scan against the primary-key index. Supports 9-digit inputs
by also probing `digits[1:]` as a prefix (KBO sometimes drops the
leading zero on display).

### Response shape

```json
{
  "q": "Colruyt",
  "commercial": [
    {"enterprise_number": "0400378485",
     "name": "Colruyt Group",
     "status": "AC",
     "juridical_form": "014",
     "form_category": "commercial",
     "city": "Halle",
     "sector": "Detailhandel in…",
     "start_date": "1928-10-23",
     "revenue": 10600000000,
     "ebitda": 800000000,
     "ebitda_margin_pct": 7.5,
     "fte_total": 13000,
     "fiscal_year": 2024,
     "score": 1.52}
  ],
  "nonprofit_or_public": [...],
  "total": {"commercial": 20, "nonprofit_or_public": 0}
}
```

Categories `nonprofit`, `public`, `other` (foreign entities, VZW, public
bodies, co-owner associations) all land in `nonprofit_or_public`; the
rest land in `commercial`. Bucket size caps: 20 commercial, 10
nonprofit/public.

### Legacy callers

`frontend/src/lib/api.ts::searchCompanies` is a **flatten shim**:
callers from `aggregate/`, `compare/`, `favourites/`, `company/` pages
expect the V1 `SearchResult[]` shape, so the shim merges both buckets
and maps fields back to V1 names. Only `/search` page uses
`searchCompaniesBucketed` directly.

---

## `/api/people/search` — how it ranks

Same scoring philosophy, richer fan-out because people come from three
tables. `backend/routers/people.py::_PEOPLE_V2_SQL`.

### Base scores by arm

| Arm | Base | Condition |
|---|---|---|
| exact | 1.00 | `name_normalized = :nq` OR `name_reversed = :rev` |
| token-AND | 0.70 | all typed tokens present (any order), up to 4 tokens, wildcard-escaped |
| trigram | 0.00–0.40 | `similarity(name_normalized, :nq) > 0.3` |
| phonetic | 0.30 | `name_phonetic = :phon` (exact on Double-Metaphone key) |
| address fallback | 0.20 | person connected (as admin/shareholder) to company at matching street/city/zipcode; gated to ≥4 chars |

Each arm UNION ALL-s across `administrator`, `shareholder`, and
`staatsblad_event` with `event_type='admin_event'`. Per-arm LIMIT 500
(200 for phonetic/trigram) caps pathological fan-out.

### Grouping and disambiguation

After the UNION, rows are grouped by:

```
(lower(name), person_domicile_city || '', person_domicile_postcode || '')
```

This is where Staatsblad domicile data pays off: two "Jan De Clerck"s
with different `person_domicile_*` values become two distinct result
rows. When the re-extraction cron has NOT yet populated those fields
for a given person (still progressively backfilling), both rows fall
into the same group — same behaviour as before the feature landed.

`dominant_city` returned on the response prefers the Staatsblad
domicile when available; falls back to the highest-revenue connected
company's city. `has_domicile=true` means the authoritative path is
being used (frontend shows the tag in green).

### Denomination lookup is LATERAL, not CTE

Critical perf detail: the per-hit denomination lookup is a LATERAL
subquery, not a CTE scanning all 3.3 M denomination rows. This single
change cut people/search latency from ~2 s to ~300 ms. Do not
refactor back to a CTE without re-benchmarking.

### Response shape

```json
[
  {"name": "Vic Huys",
   "company_count": 1,
   "top_companies": [
     {"name": "Viconco", "cbe": "0561702947"}
   ],
   "score": 1.0,
   "dominant_city": "Damme",
   "dominant_postcode": null,
   "has_domicile": false}
]
```

`top_companies` is an array of `{name, cbe}` pairs (up to 20 inline)
so the frontend can render each as a clickable `/company/{cbe}` pill.
Legacy callers that expect `string[]` are still typed as
`(PersonTopCompany | string)[]` in `api.ts` for backward compatibility.

---

## `/api/search/suggest` — grouped autocomplete

New in V2. Single SQL round-trip via `json_build_object`, targets
sub-150 ms so the header dropdown feels instant. Fires on every
keystroke (with 150 ms debounce on the frontend and AbortController
cancellation on stale requests).

`backend/routers/search.py::suggest` + `_SUGGEST_SQL`.

Returns:

```json
{
  "q": "Colruyt",
  "companies": [{"cbe": "…", "name": "…", "city": "…", "category": "commercial"}],  // up to 5
  "people":    [{"name": "…", "company_count": 3}],                                  // up to 5
  "cbe_match": {"cbe": "0403170701", "name": "…"} | null,
  "addresses": [{"street": "…", "city": "…", "zipcode": "…", "cbe": "…"}]            // up to 3
}
```

All arms gated to `length(nq || '%') >= 4` to prevent 2-char-prefix
fan-out on the 1 M admin / 3.3 M denomination tables.

**Rate limit bucket**: `/api/search/suggest` is in the SEARCH_PATHS
rate-limit tier (60 req/min/IP) — same as `/api/companies/search` and
`/api/people/search`. Tightened deliberately so the per-keystroke
usage pattern can't melt Postgres under an abusive client.

**Warning about SQL comments**: psycopg2 interprets every `%` in the
SQL template as a parameter placeholder, including `%` inside `-- …`
comments. Never write `-- look for '%foo%' patterns`; escape as `%%`
or use the word "wildcard". A single unescaped `%` turns the whole
query into `ProgrammingError: argument formats can't be mixed` and
silently returns an empty payload.

---

## `/api/staatsblad/events/search` — text search over events

Separate router, unchanged by the V2 refactor. Uses the
`staatsblad_event_embedding` pgvector index + ILIKE fallback. Rendered
as the bottom "Events" section on `/search`. Typical latency <50 ms.

---

## Frontend

### `/search` page (`frontend/src/app/search/page.tsx`)

- 100 ms keystroke debounce (down from 300 ms).
- Three API calls (`searchCompaniesBucketed`, `searchPeople`,
  `searchEvents`) fire in parallel and render independently as they
  return. Previously `await Promise.all([…])` waited for all three;
  now the slowest (usually events, which can hit OpenRouter on an
  embedding-cache miss) no longer blocks commercial + people from
  painting.
- AbortController cancellation on every new keystroke. Stale responses
  check `signal.aborted` before `setState` so a slow cold-cache
  request from keystroke 3 doesn't overwrite keystroke 7's data.
- URL-synced via `history.replaceState` — no router push, so the back
  button returns the user to the pre-search snapshot.

### Section components (`frontend/src/app/search/_components/sections.tsx`)

Four sections, fixed hierarchy:

1. **Commercial companies** — primary grid, emerald-on-hover.
2. **People** — equally prominent on `lg+`, emerald pills for
   connected companies (each a clickable link to
   `/company/{cbe}`). If a person has more than 2 companies, a
   "+N more" toggle expands the full inline list.
3. **Non-profits & public entities** — demoted, collapsed behind a
   chevron by default. Uses a slate-toned card variant.
4. **Events** — smallest, at the bottom.

Top match in each section gets a subtle ring + 8 px bottom gap. The
ring only fires when `isExactEnoughMatch(query, name)` is true —
trigram / phonetic / address-fallback neighbours never steal the
top-match visual weight.

### Header autocomplete (`frontend/src/components/header-search.tsx`)

WAI-ARIA combobox. 150 ms debounce. Groups: companies / people /
enterprise number / addresses. Keyboard nav (↑/↓ across groups,
Enter opens, Escape closes, Tab commits and moves on). Match text is
not highlighted (future work).

Person domicile tag (`sections.tsx::PersonCard`):

- `has_domicile: true` → green text, tooltip "Domicile from
  Staatsblad publication".
- `has_domicile: false` → slate text, tooltip "Inferred from the
  person's main company (KBO does not expose private home
  addresses)".

---

## Performance targets + known bottlenecks

Post-V2 on prod, cold cache:

| Query shape | Target | Actual |
|---|---|---|
| `/api/search/suggest` any 3-char prefix | <150 ms | 8–20 ms |
| `/api/companies/search` name match | <500 ms | 200–700 ms |
| `/api/companies/search` address-fallback | <1500 ms | 1–1.5 s |
| `/api/people/search` name match | <300 ms | 100–300 ms |
| `/api/people/search` address-fallback | <1500 ms | 1–2 s |

Known remaining bottlenecks:

- **`companies/search` with 2-token queries on common words** (e.g.
  "Tim Braet"): ~800 ms. Both tokens' ILIKEs scan independently via
  GIN, then UNION. Optimising would need a denormalised token table;
  not worth the write amplification today.
- **Address-fallback without a street-level trigram index** on the
  3 M-row `address` table: ~1 s on "Rue Neuve". If this becomes a
  complaint, add `gin_trgm_ops` indexes on `address.street_nl` and
  `address.street_fr`. Skipped in V2 because the storage cost is
  significant and the use case is marginal.
- **`suggest` people arm on 2-character queries** would fan out; it's
  gated to ≥3 chars (`length(nq_pfx) >= 4`). Below that the dropdown
  shows no people.

---

## Known data gaps (not bugs)

- **Small commanditaire vennootschappen** (KBO juridical form `612`)
  under the NBB filing threshold don't file annual accounts → zero
  NBB admin data → zero search hits. Partnership data is fundamentally
  not open in Belgium. Example: Gayana BCE `0885927625` has zero
  admin rows in our DB even though it has known partners.
- **UBO register** (ultimate beneficial owners) is not open-data and
  not ingested. Chains of ownership through holding companies are
  only visible when each hop has admin / shareholder data of its own.
- **Staatsblad re-extraction lag**. `person_domicile_*` fields are
  progressively populated by a re-extraction cron. Rows touched by
  older prompt versions have NULL domicile until the cron revisits
  them. No automated ETA; track via
  `SELECT COUNT(*) FROM staatsblad_event WHERE person_domicile_city IS NULL AND event_type='admin_event'`.
- **KBO direct-marketing clause** — KBO data may not be used for
  direct marketing. Rate limits on search and per-user logging in
  `activity_log` are the enforcement mechanism.

---

## How to debug a "why doesn't X show up?" report

1. **Is the query hitting the right endpoint?** Header autocomplete
   uses `/api/search/suggest`. Full results page uses
   `/api/companies/search` + `/api/people/search`. Both can diverge
   if one is broken (pysopg2 comment bug history, length gates,
   rate limiter).
2. **Is the subject in the DB?** Run:
   ```
   SELECT enterprise_number, name FROM company_info WHERE name_normalized LIKE '%foo%';
   SELECT entity_number, denomination FROM denomination WHERE denomination_normalized = 'foo';
   SELECT name, enterprise_number FROM administrator WHERE name_normalized = 'foo';
   ```
3. **Is the request rate-limited?** Check
   `docker logs leadpeek-backend-1 | grep "429"`.
4. **Is the suggest endpoint returning empty payloads?** Check backend
   logs for `psycopg2.ProgrammingError`. Most often caused by a bare
   `%` character added to a SQL comment in a recent edit.
5. **Is the frontend cache stale?** Hard refresh (Ctrl-Shift-R).
   Next.js bundles aren't hashed on every change during rapid
   iteration.

---

## Files map

### Backend (production code)

| File | Purpose |
|---|---|
| `backend/search_normalization.py` | Canonical Python normalisation + query classifier. Mirrors SQL. |
| `backend/routers/companies/search.py` | `GET /api/companies/search` scored CTE. |
| `backend/routers/people.py` | `GET /api/people/search` scored CTE with Staatsblad JOIN. |
| `backend/routers/search.py` | `GET /api/search/suggest` + legacy `/semantic` endpoint. |
| `backend/routers/staatsblad_events.py` | `GET /api/staatsblad/events/search` for the Events section. |
| `backend/nbb_governance.py` | NBB XBRL → `administrator` / `shareholder` / `participating_interest` extractor. |
| `backend/main.py` | Rate limiter bucket config (SEARCH_PATHS), tier classification, synonym cache startup hook. |
| `backend/db.py` | Legacy `ensure_trgm_setup` guarded behind V2-detection probe. |
| `backend/tests/test_search_normalization.py` | Regression tests for the normaliser. |

### Migrations

| File | Purpose |
|---|---|
| `migrations/2026-04-24_search_v2.sql` | Six-phase idempotent migration: extensions + functions + 146-row KBO taxonomy + 35-row synonyms + generated columns + GIN indexes + popularity table. |
| `migrations/2026-04-24_search_v2_rollback.sql` | Reverse the above if V1 code is restored. |

### Scripts

| File | Purpose |
|---|---|
| `scripts/refresh_popularity.py` | Nightly 28-day click-count aggregator into `company_popularity`. Cron at 03:15 UTC. |
| `scripts/smoke_search_v2.sh` | 26-query integration test against a running instance. `BASE_URL=https://datasnoop.be bash scripts/smoke_search_v2.sh`. |

### Frontend

| File | Purpose |
|---|---|
| `frontend/src/app/search/page.tsx` | `/search` page entry. URL sync, debounce, progressive render. |
| `frontend/src/app/search/_components/sections.tsx` | Commercial / People / Nonprofit / Events section components + cards. |
| `frontend/src/components/header-search.tsx` | WAI-ARIA combobox for the header autocomplete dropdown. |
| `frontend/src/components/nav.tsx` | Wires `<HeaderSearch />` into the top nav. |
| `frontend/src/lib/api.ts` | `searchCompanies` (legacy shape shim), `searchCompaniesBucketed` (V2), `suggestSearch`, `searchPeople`, `searchEvents`. |
| `frontend/src/i18n/{en,nl,fr}.json` | `search.sections.*` + `search.noResultsBucket.*` + `search.showHidden` translation keys. |

### Docs

| File | Purpose |
|---|---|
| `docs/search.md` | **This document.** |
| `docs/architecture.md` | System overview (read alongside). |
| `docs/semantic-operations.md` | Semantic-pipeline operations; not search per se. |

---

## Operational runbook

### Deploying a change to search

Per CLAUDE.md: search changes touch shared-prod surface. Procedure:

1. Branch off master.
2. Make the code change. Add or update tests in
   `backend/tests/test_search_normalization.py` for any normaliser
   tweak.
3. `tsc --noEmit` clean in frontend.
4. Run two review agents in parallel (correctness + security) before
   merging to master (standing rule).
5. Operator approves the deploy.
6. On the Hetzner server:
   ```
   cd /opt/leadpeek
   git pull origin master
   docker compose build backend frontend
   docker compose up -d --force-recreate backend frontend nginx
   ```
   If Docker build skips the COPY layer because it thinks files
   haven't changed (happens when master moves while the build queue
   is running), add `--no-cache` to the build command.
7. Smoke-test against prod: `BASE_URL=https://datasnoop.be bash
   scripts/smoke_search_v2.sh`.

### Applying the V2 migration on a fresh environment

```
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/2026-04-24_search_v2.sql
GRANT SELECT ON juridical_form_category TO leadpeek;
GRANT SELECT, INSERT, UPDATE ON legal_form_synonyms TO leadpeek;
GRANT SELECT, INSERT, UPDATE ON company_popularity TO leadpeek;
```

(If the extensions CREATE EXTENSION statements fail, the DB user needs
superuser rights OR an admin needs to run those three `CREATE
EXTENSION` lines first as a postgres superuser.)

### Keeping Python and SQL normalisers in sync

If you change the Belgian legal-suffix regex in either side, you must
change BOTH. Tests in `backend/tests/test_search_normalization.py`
catch most divergences, but the SQL-side regex is regex-for-Postgres
dialect and the Python side is `re`-module — patterns like
`[[:space:][:punct:]]` translate to `[\s\W_]` in Python.

Decision procedure if they drift:

1. The **stored** column is the source of truth. If a user row is
   already in the DB with `name_normalized = "acme"`, any search
   query normalising the input to anything other than `"acme"` will
   miss it.
2. Changing the SQL regex means the generated columns recompute on
   the next write to that row. For a guaranteed full refresh, drop
   and re-add the generated column (rewrites the whole table — avoid
   on prod during business hours).

---

## Product-level intent (for future context)

From the field complaints that drove V2:

> "[Search is] too sensitive to spaces, special letters é, reversal of
> first and surname, if people add company type behind name its gets
> stuck (NV, BV etc), and in general, the findings its showing is not
> sufficiently organized (I also think we should put results of
> non profits or governmental entities in a separate box below people
> and company findings. People use this tool to look up people and
> commercial companies mainly)"

Product decisions that fell out of that, now encoded in V2:

1. **Commercial-first.** Non-profits and public entities are demoted
   to a collapsed section below commercial companies + people. This
   is more aggressive than industry norm ("demote-don't-hide") — do
   not revert without a product discussion.
2. **Instant-search.** 100 ms debounce on `/search` + AbortController
   cancellation. Any change that increases typing latency materially
   needs a new UX decision.
3. **Name-order is equivalent.** Tim Braet = Braet Tim. Users don't
   know or care how KBO stores the canonical form.
4. **Legal-suffix synonyms** (NV↔SA, BV↔SPRL, VZW↔ASBL) collide at
   normalisation. Users searching "Colruyt SA" find the Dutch "Colruyt
   NV". Do not narrow this without a product discussion.
5. **KBO direct-marketing clause.** Anonymous access is allowed but
   rate-limited. Any feature that could be abused for bulk harvesting
   (e.g. a "download all directors" button) must be gated behind
   authenticated tiers.
