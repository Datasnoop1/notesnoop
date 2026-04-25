## Approach

1. **Cache admin emails process-wide** — Add an `_admin_emails_cache` dict with `time.time()` TTL (30 s) next to the existing `_admin_stats_cache`. A `_get_admin_emails()` helper returns the cached list on hot paths and only hits Postgres on miss, eliminating the repeated `SELECT email FROM user_roles WHERE role = 'admin'`.
2. **Rewrite `hourly_today` with a single CTE** — Compute the Brussels day start/end once in a `bounds` CTE, then reference those `timestamptz` boundaries in the `WHERE` clause. This removes three redundant `AT TIME ZONE 'Europe/Brussels'` conversions from the filter predicates.
3. **Merge `guest_pages` + `registered_pages`** — Replace the two separate queries with one SQL statement that groups by `CASE WHEN COALESCE(email,'') = '' THEN 'guest' ELSE 'registered' END`. Python partitions the unified result set back into the two original response keys, saving one round-trip.
4. **Preserve response contract** — The endpoint still returns the exact same JSON shape (`kpis`, `engagement`, `daily_trend`, `hourly_today`, `guest_pages`, `registered_pages`, `signups`, `stickiness`, `top_guests`). Only internal query execution changes.

## File List

- **`backend/routers/admin.py`** (~line 45, near `_admin_stats_cache`): add  
  `_ADMIN_EMAILS_TTL_SECONDS = 30.0` and `_admin_emails_cache: dict[str, tuple[float, list[str]]] = {}`.
- **`backend/routers/admin.py`** (~line 55–75): add `_get_admin_emails() -> list[str]` helper that populates the cache on miss.
- **`backend/routers/admin.py`** (~lines 700–902, `/traction` endpoint body):
  - Replace the inline admin-emails query with a single call to `_get_admin_emails()`.
  - Swap in the CTE-based `hourly_today` SQL.
  - Replace the two page-stat queries with the merged `CASE ... GROUP BY` query and post-process rows into the two list values.

## Concrete SQL

**`hourly_today` — Brussels boundary CTE**
```sql
WITH bounds AS (
    SELECT
        (CURRENT_TIMESTAMP AT TIME ZONE 'Europe/Brussels')::date
            AT TIME ZONE 'Europe/Brussels' AS day_start,
        ((CURRENT_TIMESTAMP AT TIME ZONE 'Europe/Brussels')::date + INTERVAL '1 day')
            AT TIME ZONE 'Europe/Brussels' AS day_end
)
SELECT
    EXTRACT(hour FROM created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Europe/Brussels')::int AS hour,
    COUNT(*) AS hits
FROM activity_log, bounds
WHERE created_at >= bounds.day_start
  AND created_at < bounds.day_end
  AND email NOT IN %(admin_emails)s
GROUP BY hour
ORDER BY hour
```

**Merged `guest_pages` + `registered_pages`**
```sql
SELECT
    CASE WHEN COALESCE(email, '') = '' THEN 'guest' ELSE 'registered' END AS user_kind,
    endpoint,
    COUNT(*) AS hits
FROM activity_log
WHERE created_at > NOW() - INTERVAL '7 days'
  AND endpoint != '/api/health'
  AND email NOT IN %(admin_emails)s
GROUP BY user_kind, endpoint
ORDER BY user_kind, hits DESC
```
*Python splits the returned rows by `user_kind` into the existing `guest_pages` and `registered_pages` arrays (applying `LIMIT` in code if the old SQL had one).*

## Tests

1. **Baseline capture**  
   ```bash
   curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
     http://localhost:8000/api/admin/traction | jq -S . > before.json
   ```
2. **Deploy and compare** — Run the same curl after the change, save as `after.json`, then:  
   ```bash
   diff <(jq -S . before.json) <(jq -S . after.json)
   ```
   All leaf counts (`kpis.*`, `engagement.*`, `hourly_today.*`, `signups`, `stickiness`, `top_guests`, plus the combined cardinality of `guest_pages` + `registered_pages`) must be identical.
3. **Cache verification** — Add a temporary `logger.info` inside `_get_admin_emails` on the DB-miss path; rapid-fire curls should log the hit only once per 30-second window.

## Risks

- **Guest-definition drift** — If the legacy code used `email IS NULL` instead of `COALESCE(email,'') = ''`, the merged query could misclassify empty-string emails. Align the `CASE` predicate exactly with the old filters.
- **Admin-emails cache staleness** — A newly promoted admin will be treated as non-admin in metrics for up to 30 s. Acceptable for internal analytics, but worth documenting.
- **Timezone boundary edge cases** — The CTE uses `CURRENT_TIMESTAMP`; ensure this matches the old query’s clock source (`NOW()`) so day boundaries don’t shift.
- **Response-shape regression** — If the Python partition logic accidentally omits a key or changes an item schema, the Phase-2 frontend will break. The `diff` test above guards against this.