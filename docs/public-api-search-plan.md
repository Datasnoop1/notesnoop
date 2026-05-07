# Public API — Broader Database Access (Search Endpoint) Plan

**Status:** DRAFT v4 — rounds 1-3 panel feedback incorporated.

## Goal

Give Ascot's API key the ability to **list / rank companies by financial
metrics** (e.g. "top 100 companies by total assets"), without expanding
Feneko's surface or any future default-tier customer's surface.

Today every active key sees `/health` + `/financials`. We need:

1. A way to gate endpoints **per key**, not globally.
2. A new endpoint that returns ranked, filtered company lists.
3. Documentation, error envelope, and rate-limit semantics consistent
   with the existing API.

## Non-goals (v1)

- Full-text name search — separate endpoint, deferred.
- Free-form SQL or GraphQL — too much surface area.
- Director / shareholder / network search — KBO licence concern.
- Time-series export — that's a bulk-download problem, separate endpoint.
- Province / region filter — `company_info` has only `city` + `zipcode`;
  province must be derived. Deferred to a follow-up.

## 1 — Schema change: per-key scopes

Add a `scopes` column to `api_keys`:

```sql
-- Migration: 00XX_api_keys_scopes.sql
ALTER TABLE api_keys
  ADD COLUMN scopes TEXT[] NOT NULL DEFAULT ARRAY['lookup'];

-- Belt-and-suspenders: existing rows get the DEFAULT, but make it
-- explicit so a future audit doesn't have to reason about it.
UPDATE api_keys
   SET scopes = ARRAY['lookup']
 WHERE scopes IS NULL OR cardinality(scopes) = 0;

-- Constraint that ACTUALLY rejects empty arrays. The naive
-- `array_length(scopes, 1) >= 1` evaluates to NULL on an empty array
-- (NULL >= 1 is unknown, not false), so the CHECK doesn't trigger.
-- `cardinality()` returns 0 for empty arrays — safe.
ALTER TABLE api_keys
  ADD CONSTRAINT api_keys_scopes_not_empty
  CHECK (cardinality(scopes) >= 1);

-- Typo protection: every element must be a known scope. Rejects rows
-- with `'seach'`, `'admin'`, etc. The vocabulary lives in code AND in
-- this constraint — both must be updated when adding a new scope.
ALTER TABLE api_keys
  ADD CONSTRAINT api_keys_scopes_known
  CHECK (scopes <@ ARRAY['lookup','search']::TEXT[]);
```

Two scopes for v1:

| Scope    | Endpoints |
|----------|-----------|
| `lookup` | `GET /api/v1/company/{vat}/financials` |
| `search` | `GET /api/v1/companies` (new) |

`/health` is unauthenticated and not scope-gated.

The `scopes TEXT[]` shape is intentionally simple. A junction table
or PG ENUM would catch typos statically, but adds migration friction
for two values; we revisit if the scope vocabulary grows past ~5.

## 2 — Auth dependency: `require_scope()`

Update `require_api_key()` in `backend/routers/public_api.py` to also
SELECT `scopes` (one extra column on the existing query — no caching
layer to invalidate; no Pydantic model to update; the function returns
a plain `dict` from `fetch_one`). Add a thin scope-check dependency:

```python
_VALID_SCOPES = frozenset({"lookup", "search"})

def require_scope(required: str):
    # Validated at module load time — guards against typos like
    # `require_scope("seach")` that would silently 403 every call.
    if required not in _VALID_SCOPES:
        raise RuntimeError(
            f"require_scope({required!r}): unknown scope. "
            f"Add it to _VALID_SCOPES + the api_keys_scopes_known CHECK."
        )

    def dep(api_key: dict = Depends(require_api_key)) -> dict:
        scopes = api_key.get("scopes") or []
        if required not in scopes:
            _log_call(api_key["id"], None, f"scope_check:{required}", 403, 0)
            raise HTTPException(
                status_code=403,
                detail={"error": "scope_denied",
                        "message": f"This key lacks the '{required}' scope"},
            )
        return api_key
    return dep
```

**`/financials` IS gated on `lookup` from day one.** Round-1 panel was
unanimous: relying on the DB default for authorization is brittle. The
explicit backfill in §1 + the CHECK constraint guarantee every existing
key has `lookup`, so gating breaks no customer. Pattern:

```python
@router.get("/company/{vat}/financials")
async def get_company_financials(..., api_key=Depends(require_scope("lookup"))):
    ...

@router.get("/companies")
async def list_companies(..., api_key=Depends(require_scope("search"))):
    ...
```

## 3 — New endpoint: `GET /api/v1/companies`

### URL & query parameters

| Name | Type | Default | Constraints | Notes |
|------|------|---------|-------------|-------|
| `sort` | string | `total_assets:desc` | enum, see allowlist | `<metric>:<asc\|desc>` |
| `limit` | int | 50 | 1 ≤ N ≤ 250 | Hard ceiling per call |
| `cursor` | string | None | opaque base64 | Keyset pagination (§4) |
| `year` | int | (latest filed) | 2000 ≤ N ≤ current+1 | Specific fiscal year — switches source table |
| `min_revenue` | int | None | 1 ≤ N ≤ 1e15 | `min_revenue=0` is a no-op filter that confuses the planner — rejected as `400 invalid_filter`. Customer should omit the parameter instead |
| `min_total_assets` | int | None | 1 ≤ N ≤ 1e15 | Same |
| `min_ebitda` | int | None | -1e15 ≤ N ≤ 1e15 | Negative legit (loss-making companies) |
| `min_equity` | int | None | -1e15 ≤ N ≤ 1e15 | Negative legit (insolvency) |
| `min_net_profit` | int | None | -1e15 ≤ N ≤ 1e15 | Negative legit |
| `juridical_form` | string | None | `^[A-Za-z]{1,8}$` | Exact match, case-insensitive |
| `nace_prefix` | string | None | `^\d{2}(\.\d{1,3})?[A-Za-z]?$` | NACE Rev. 2 (digits + optional dot + optional letter) |

`offset` from earlier drafts is **removed** — replaced by `cursor` (§4)
which is stable under live data and O(1) per page regardless of depth.

### Sort allowlist

Implementation maps `sort` to a fixed ORDER BY string and a fixed
metric column via two server-side dicts. Both are populated at module
load time from a single source of truth and **never** built from user
input. Unrecognised `sort` values return `400 invalid_sort`.

```python
# Single source of truth: (metric, direction) → (sql_column, sql_order_by)
_SORT_TABLE: dict[str, tuple[str, str]] = {
    "total_assets:desc": ("fl.total_assets",
                          "fl.total_assets DESC NULLS LAST, fl.enterprise_number ASC"),
    "total_assets:asc":  ("fl.total_assets",
                          "fl.total_assets ASC NULLS FIRST, fl.enterprise_number ASC"),
    "revenue:desc":      ("fl.revenue",       "..."),
    # ...etc for ebitda, equity, net_profit, fte_total, fiscal_year
}
```

The implementation MUST treat `_SORT_TABLE` keys as the only valid
`sort` values. It MUST resolve both the column and the ORDER BY clause
from this single dict; deriving one from the other (e.g. parsing the
ORDER BY string for the column) is forbidden.

### Response shape

```json
{
  "data": [
    {
      "vat": "0752984076",
      "name": "COOVER",
      "legalForm": "BV",
      "fiscalYear": 2024,
      "totalAssets": 800000,
      "revenue": 1234000,
      "ebitda": 99000,
      "equity": 412000,
      "netProfit": -58000,
      "fteTotal": 5,
      "naceCode": "46.731",
      "city": "Brussels"
    }
  ],
  "meta": {
    "limit": 50,
    "sort": "total_assets:desc",
    "nextCursor": "eyJzIjoidG90YWxfYXNzZXRzOmRlc2MiLCJtIjo4MDAwMDAsImUiOiIwNzUyOTg0MDc2In0",
    "hasMore": true,
    "appliedFilters": {
      "year": 2024,
      "minRevenue": 1000000
    },
    "schemaVersion": "1.0",
    "currency": "EUR"
  }
}
```

`appliedFilters` echoes filters AFTER server-side defaults are
resolved (e.g. shows the actual `year` used when the caller didn't pass
one). Defaults that haven't been resolved (i.e. truly unset) are
omitted. `nextCursor` is present only when `hasMore: true`; it's
opaque — clients don't decode it.

`city` and `naceCode` may be `null` when `company_info` lacks the row.

## 4 — Implementation: keyset pagination, NULL safety

Source tables (no new tables added):

- `financial_latest` (table, **PK on `enterprise_number`** — uniqueness
  already enforced; verified against `src/schema.sql:425`). Used when
  no `?year=` is passed.
- `financial_by_year` (table, **non-unique** `(enterprise_number,
  fiscal_year)` — this combination is unique per row, but neither alone
  is). Used when `?year=N` is passed; pagination tiebreak still uses
  `enterprise_number`.
- `company_master` — JOIN for `name` + `juridical_form`.
- `company_info` (PK on `enterprise_number`) — LEFT JOIN for `city` +
  `nace_code`.

### Required indexes

Each sort metric needs a composite index that ALSO carries the ASC/DESC
direction the query uses. PostgreSQL can walk an index backwards only
when **all** index columns reverse direction together — so a
`(metric DESC, en ASC)` index serves `ORDER BY metric DESC, en ASC`
forward and `ORDER BY metric ASC, en DESC` reversed, but **not**
`ORDER BY metric ASC, en ASC`. Therefore one composite index per
(metric, direction) variant we expose:

```sql
-- Built CONCURRENTLY to avoid locking financial_latest during the
-- migration. Each statement runs OUTSIDE the migration transaction.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_fl_total_assets_desc_en
  ON financial_latest (total_assets DESC NULLS LAST, enterprise_number ASC);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_fl_total_assets_asc_en
  ON financial_latest (total_assets ASC NULLS FIRST, enterprise_number ASC);
-- ...same pair for revenue, ebitda, equity, net_profit, fte_total
-- = 12 indexes total on financial_latest.

-- year-filtered variant on financial_by_year (one pair per metric × per
-- direction = 12 more, partitioned implicitly by fiscal_year being the
-- equality predicate):
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_fby_year_total_assets_desc_en
  ON financial_by_year (fiscal_year, total_assets DESC NULLS LAST, enterprise_number ASC);
-- ...

-- Functional index for case-insensitive juridical_form filter
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cm_juridical_form_lower
  ON company_master (LOWER(juridical_form));

-- B-tree LIKE prefix scan needs *_pattern_ops* for collation-safe use.
-- A plain B-tree on `nace_code` would not be picked for `LIKE 'prefix%'`
-- on a non-C collation database — text_pattern_ops gives the planner
-- a left-anchored prefix index it WILL pick.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ci_nace_code_pattern
  ON company_info (nace_code text_pattern_ops);
```

24 composite indexes is significant write amplification. Mitigations:

- `financial_latest` and `financial_by_year` are rewritten per-company
  in `_refresh_materialized_for_company()` ([routers/companies/financials.py:544](backend/routers/companies/financials.py:544)) — only the
  affected rows pay the index-update cost, not the whole table.
- We can ship a subset (e.g. just DESC variants for the most common
  sorts: `total_assets`, `revenue`, `ebitda`) and add the rest after
  observing real usage.

### Cursor encoding + decoding

Cursor encodes the sort identifier alongside the seek tuple, so the
server can detect cursor/sort mismatch.

```python
import base64, json

def _encode_cursor(sort: str, metric_val: float | None, en: str) -> str:
    raw = json.dumps({"s": sort, "m": metric_val, "e": en},
                     separators=(",", ":"), sort_keys=True)
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")

def _decode_cursor(cursor: str, expected_sort: str) -> tuple[float | int, str]:
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        obj = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, json.JSONDecodeError, base64.binascii.Error):
        raise HTTPException(400, {"error": "invalid_cursor",
                                  "message": "Cursor is malformed"})

    if not isinstance(obj, dict):
        raise HTTPException(400, {"error": "invalid_cursor", "message": "Cursor payload not an object"})

    sort = obj.get("s")
    metric = obj.get("m")
    en = obj.get("e")

    if sort != expected_sort:
        raise HTTPException(400, {"error": "invalid_cursor",
                                  "message": "Cursor was issued for a different sort; restart pagination"})
    if not isinstance(metric, (int, float)):
        raise HTTPException(400, {"error": "invalid_cursor",
                                  "message": "Cursor metric value missing or non-numeric"})
    if not isinstance(en, str) or not en.isdigit() or len(en) != 10:
        raise HTTPException(400, {"error": "invalid_cursor",
                                  "message": "Cursor enterprise number malformed"})

    return metric, en
```

**Cursor integrity / HMAC.** Cursors are unsigned base64 JSON. A client
can decode + tamper + re-encode. The exposed surface is "skip to row N"
on a public ranking — no different from passing your own filters. We
explicitly accept this risk for v1; if the audit log shows abuse we'll
add an HMAC signature scheme later.

**NULL on cursor metric.** Cursors are minted only from the last row of
`data` whose sort metric IS NOT NULL. The server-side filter `WHERE
sort_metric IS NOT NULL` (added only when a cursor is present, see
below) ensures we never paginate into the NULL tail.

### NULL-metric handling — uniform exclusion

Round-3 panel was right that the page-1 vs page-2+ split was leaky:
a cursor minted from a page-1 row near the NULL boundary would
encode `metric=NULL`, and the seek `(NULL, en) < (last_v, last_en)`
evaluates to NULL (drops everything). Simpler design: **always
exclude `WHERE sort_metric IS NOT NULL` for the column being sorted,
regardless of cursor presence.**

Companies with no value for the sort metric simply don't appear in
that ranking — which matches the doctrine "a NULL metric has no
defensible position in a ranking". A customer who wants to see them
can sort by a different metric, or `?year=` a year they did file.

This eliminates the page-boundary tie risk entirely: every row on
every page has a defined metric, so the cursor seek is well-defined
and ties resolve via the `enterprise_number` tiebreak in the index.

### Query construction

Built fragment-by-fragment with **bound parameters only** for all user
input. The only string interpolation is from `_SORT_TABLE` (server-
controlled, allowlisted, indexed by validated `sort` value):

```python
sort_metric_col, sort_order_by = _SORT_TABLE[sort]   # KeyError → 400 invalid_sort
sort_dir = "DESC" if sort.endswith(":desc") else "ASC"

# Source table from a server-side dict — no string interpolation
# of any value derived from user input or boolean ternary, even
# though both options are server-controlled today. Closes the
# refactor footgun the panel flagged.
_SOURCE_TABLES: dict[bool, str] = {
    True:  "financial_by_year",
    False: "financial_latest",
}
source_table = _SOURCE_TABLES[year is not None]

where_parts = [f"{sort_metric_col} IS NOT NULL"]   # uniform NULL exclusion
params: list = []

# Numeric filters: conditional pattern — no sentinel.
for col, val in [
    ("fl.total_assets", min_total_assets),
    ("fl.revenue",      min_revenue),
    ("fl.ebitda",       min_ebitda),
    ("fl.equity",       min_equity),
    ("fl.net_profit",   min_net_profit),
]:
    if val is not None:
        where_parts.append(f"{col} >= %s")     # `col` from server allowlist only
        params.append(val)

# Year filter (only when source_table is financial_by_year).
if year is not None:
    where_parts.append("fl.fiscal_year = %s")
    params.append(year)

# Case-insensitive exact match — uses idx_cm_juridical_form_lower.
if juridical_form is not None:
    where_parts.append("LOWER(cm.juridical_form) = LOWER(%s)")
    params.append(juridical_form)

# nace_prefix: regex-validated, then bind `prefix + "%"` — single param,
# never concatenated into SQL.
if nace_prefix is not None:
    where_parts.append("ci.nace_code LIKE %s")
    params.append(nace_prefix + "%")

# Cursor seek (keyset). The IS NOT NULL guard is already in
# `where_parts` from the start, so the seek tuple comparison is
# always well-defined.
if cursor is not None:
    last_v, last_en = _decode_cursor(cursor, expected_sort=sort)
    if sort_dir == "DESC":
        where_parts.append(f"({sort_metric_col}, fl.enterprise_number) < (%s, %s)")
    else:
        where_parts.append(f"({sort_metric_col}, fl.enterprise_number) > (%s, %s)")
    params.extend([last_v, last_en])

where_clause = " AND ".join(where_parts) if where_parts else "TRUE"

sql = f"""
    SELECT
        fl.enterprise_number, fl.fiscal_year, fl.filing_model,
        fl.total_assets, fl.revenue, fl.ebitda, fl.equity,
        fl.net_profit, fl.fte_total,
        cm.name, cm.juridical_form,
        ci.city, ci.nace_code
    FROM {source_table} fl
    JOIN company_master cm USING (enterprise_number)
    LEFT JOIN company_info ci USING (enterprise_number)
    WHERE {where_clause}
    ORDER BY {sort_order_by}
    LIMIT %s
"""
params.append(limit + 1)   # +1 for hasMore detection
```

`source_table` and `sort_order_by` come exclusively from server-side
constants. `where_parts` interpolates only `sort_metric_col` (also
server-side) and column names (literal in code). All user input flows
through `params` and bound `%s` placeholders.

### `hasMore` detection

`limit + 1` is fetched. If the result set has `limit + 1` rows:

- `data` = first `limit` rows
- `nextCursor` = encoded from the `limit`-th row (the last in `data`,
  not the dropped `limit+1`-th — guarantees the next page seeks past
  the boundary correctly even with ties)
- `hasMore` = true

Otherwise `data` = all rows, `nextCursor` absent, `hasMore` = false.

## 5 — Daily cap & rate limit

**Per-endpoint rate limits.** A shared 60/min budget would let
`/companies` traffic starve `/financials` for the same key:

- `/financials` — 60 calls / min, per key (unchanged)
- `/companies` — 30 calls / min, per key (lower because each call is
  more expensive and returns up to 250 rows)

**Weighted daily cap.** Each `/companies` call costs `ceil(limit / 50)`
units against the daily cap; `/financials` costs 1 unit. So Ascot's
25 000-unit cap = either 25 000 lookups, or 5 000 max-size search
calls (= 1.25 M rows max), or any mix.

Implementation:

- Add `cost INTEGER NOT NULL DEFAULT 1` to `api_call_log`.

  ```sql
  ALTER TABLE api_call_log ADD COLUMN cost INTEGER NOT NULL DEFAULT 1;
  ```

  PG ≥ 11 stores a non-volatile DEFAULT in pg_attrdef and synthesises
  it on read for rows written before the column existed — no table
  rewrite, no separate `UPDATE` needed, no lock-time spike. Existing
  rows logically read as `cost = 1` from day one, so the cap math is
  consistent immediately after migration.

- The cap check changes from `COUNT(*)` to `COALESCE(SUM(cost), 0)`
  over the last 24 h. `api_call_log` already has
  `idx_api_call_log_key_date` on `(api_key_id, created_at DESC)`
  (migration 0011); the new aggregate uses the same index.

**TOCTOU on daily cap.** The check-then-log pattern can overshoot
under burst load (multiple concurrent calls each see "cap not yet
hit"). Acceptable for a circuit breaker — overshoots are bounded by
the rate limit (30 req/min × 5 cost = 150 units max above the cap),
which is small relative to a 25 000-unit cap. Same semantics as the
existing `/financials` daily cap; not regressing.

## 6 — Error envelope

Every error response carries a `field` property when the failure is
parameter-specific, so customers know which input to fix:

| HTTP | `error` | When |
|------|---------|------|
| 400  | `invalid_sort`    | `sort` not in allowlist |
| 400  | `invalid_filter`  | Filter value out of range or unparseable; `field` names which one |
| 400  | `invalid_cursor`  | Cursor malformed, sort mismatch, or non-numeric metric |
| 403  | `scope_denied`    | Key lacks the required scope |
| 429  | `rate_limited`    | Per-minute throttle |
| 429  | `daily_cap_exceeded` | Weighted daily cap exhausted |
| 500  | `server_error`    | Unhandled — logged with key id + sanitised params |

`200` with `data: []` and `hasMore: false` when filters match nothing
(not a 404).

## 7 — Documentation

- `docs/api.md` — new endpoint section + scope concept intro.
- `docs/public-api-orientation.txt` — scope architecture, the new
  endpoint, cursor encoding, weighted-cap math, the page-1-vs-cursor
  NULL semantics.

## 8 — Migration & rollout sequence

Eliminating the 403-window: scope grant **precedes** code deploy.

1. **Schema migration** (PR #A) — adds `scopes` column with default,
   explicit backfill, and CHECK; adds `cost` column; creates 24
   composite indexes on `financial_latest` + `financial_by_year` (each
   `CREATE INDEX CONCURRENTLY`, run outside the migration transaction);
   adds the functional index on `LOWER(juridical_form)`. Apply on
   staging, smoke-test, apply on prod. Index builds may take minutes
   on a multi-million-row table — monitor `pg_stat_progress_create_index`.
2. **Operator one-shot** (manual `psql` on prod) —
   `UPDATE api_keys SET scopes = ARRAY['lookup','search'] WHERE id = 4;`
   Wrap in `BEGIN`/`COMMIT` so a connection drop mid-statement leaves
   no half-applied row.
3. **Backend deploy** (PR #B) — `require_scope()`, `/financials` gated
   on `lookup`, new `/companies` gated on `search`, weighted-cost
   accounting in `_log_call`. Deploy to staging; smoke-test with a
   `lookup`-only test key (Feneko equivalent) AND with a key holding
   both scopes; then prod.
4. **Verify** with curl from outside that Ascot's key gets data on
   `/companies` and Feneko's gets `403 scope_denied`.

Rollback: revert PR #B; PR #A's additions (column with default, indexes)
are read-only-compatible with the pre-PR-B code (which doesn't SELECT
the new column). Existing `SELECT *`/explicit-column queries are
unaffected. The scope grant on Ascot's row is a no-op for the rolled-
back code path.

## 9 — Backward compatibility

- Existing `/financials` behaviour unchanged from a customer's
  perspective. Now scope-gated, but every existing key has `lookup`
  via the explicit backfill in §1.
- Response shape for `/financials` unchanged (the existing `coldLoad`
  flag stays).
- `api_call_log.cost` defaults to 1; old rows read as cost 1 in the
  cap math; weighted cap math is correct on day one.

## 10 — Implementation safeguards (must be in unit tests)

Round-2 panels flagged subtle bugs in code sketches. The implementation
PR must include tests covering:

- Empty `scopes` array rejected by the CHECK constraint at INSERT time.
- `_decode_cursor` raises `400 invalid_cursor` on: bad base64, bad JSON,
  non-dict payload, missing `s`, sort mismatch, non-numeric metric,
  malformed `e`.
- Page-1 result for a sort metric where some companies have NULL
  includes the NULL-metric companies (NULLS LAST).
- Page-2+ result via cursor does NOT include NULL-metric companies and
  does not produce duplicates around the boundary.
- Cursor minted from the last `data` row (not the `limit+1`-th) to
  prevent boundary tie skips.
- `nace_prefix=46` and `nace_prefix=46.7` both LIKE-match correctly;
  `nace_prefix=` containing `%` is rejected by regex before binding.
- `juridical_form` lookup uses the functional index (verify with
  `EXPLAIN`).
- `min_revenue=-1` rejected as `400 invalid_filter` (revenue/total_assets
  are clamped to ≥ 0); `min_ebitda=-1000000` accepted.
- Daily-cap check sums `cost` not `count(*)`.

## 11 — Estimated effort

- Schema migration + index builds + verification: 2 h
  (largely waiting on `CREATE INDEX CONCURRENTLY`)
- Backend code (require_scope, /companies, weighted cost, cursor codec): 3 h
- Unit tests covering §10: 2 h
- Two-review gate + correctness/security review iterations: 2 h
- Staging smoke test: 1 h
- Production deploy + grant + verify: 1 h

**Total: ~1.5 working days** (~12 h) including review buffer. Round-2
panel flagged the previous "1 day" as optimistic; this is the corrected
estimate.
