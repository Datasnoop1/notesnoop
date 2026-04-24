# Admin dashboard audit — 2026-04-24

Reconnaissance pass for #22. No code changes yet — this is what the
rebuild should target.

## Top-5 ranked issues (by impact)

### 1. `/api/admin/stats` is a performance killer
**What:** 25+ `COUNT(*)` subqueries fired in a single `fetch_one()` call (`backend/routers/admin.py:70-129`). Each scans a full table; on prod this is 2–5 s just to paint the top of the admin page.
**Fix:** Either (a) a materialized view refreshed by cron (~hourly), or (b) a 5–10 s in-memory TTL cache on the endpoint.
**Effort:** S (cache) / M (materialized view)

### 2. `/api/admin/nbb-backload` uses nested NOT EXISTS filters
**What:** Scans the entire `enterprise` table multiple times per fiscal year check; each filter does its own NOT EXISTS.
**Fix:** Single `LEFT JOIN` with `CASE … WHEN fd.fiscal_year = year THEN 1 END` aggregation per company.
**Effort:** M

### 3. Sequential tab loading kills UX
**What:** The admin front-end loads `/stats`, `/users`, `/feedback`, `/financials-by-year`, `/nbb-backload` one after the other. Combined with #1 this means 30 s+ of spinners on slow connections.
**Fix:** Fire all endpoints in parallel on mount via `Promise.all`; each tab renders as its data lands.
**Effort:** S

### 4. Destructive admin operations have no confirmation
**What:** `DELETE /feedback` clears the entire feedback table. `DELETE /users/{email}` removes a user. `POST /normalize-names` rewrites data at scale. None of these surfaces a confirmation dialog — one misclick = data loss.
**Fix:** Frontend double-confirm modal ("Type CLEAR to confirm"), ideally plus a server-side dry-run mode returning the affected row count before commit.
**Effort:** S (modal) / M (dry-run)

### 5. `/api/admin/traction` has dynamic SQL + N+1
**What:** Builds an `admin_filter` string dynamically and runs 6+ variants per request. Fetches every admin email then filters in each sub-query. Heavy timezone conversions (`AT TIME ZONE` × 6).
**Fix:** Cache the admin-email list once per process, use parameterised CTE that excludes admins in one pass. Pre-convert timezones in SQL once per window, not per sub-query.
**Effort:** M

## Other significant issues

- **`/api/admin/users`**: N+1 — per-user `COUNT(*)` for favourites + feedback. Fix: join + `GROUP BY` in a single query.
- **`/api/admin/feedback`**: hardcoded `LIMIT 200`, no pagination. Once past the 200th item, feedback silently disappears from the admin UI.
- **`/api/admin/insights` (top companies)**: uses `REPLACE`/string parsing on enterprise_number instead of the proper foreign key — fragile.
- **Frontend has no error states / retry logic**: network blips = silent blank page; operator has no idea why numbers are missing.

## Biggest single win

**Parallelise the front-end fetches + cache `/stats`.** Alone it drops admin page load from ~30 s to 5–10 s. Effort: S for both.

## Things worth killing outright

Agent flagged — needs a closer read by operator, but candidates:
- Any admin endpoint that's been superseded (e.g. `normalize-names` if already run once; `backfill` endpoints that became cron jobs).
- Dead tabs whose endpoints return `501 Not Implemented` or are commented out.

## Plan for #22 (when operator greenlights rebuild)

Phase 1 — the 80/20:
1. Wrap `/stats` with a 10s TTL cache
2. Parallelise front-end tab fetches
3. Add double-confirm modals to the three destructive endpoints
4. Rewrite `/nbb-backload` into a single aggregated query

Phase 2 — polish:
5. Rewrite `/traction` with cached admin list + fewer timezone passes
6. Paginate `/feedback`
7. Add front-end error+retry states

Phase 3 — only if still painful:
8. Materialise `/stats` rather than cache
9. Break the admin page into lazy-loaded sub-pages so tab 1 isn't blocked by tab 5's slow query

Total Phase 1 effort: ~1 day. Would materially unblock the "slow and broken" complaint without a rewrite.
