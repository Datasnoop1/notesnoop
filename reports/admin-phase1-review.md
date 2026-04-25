- **backend/routers/admin.py: `_admin_stats_cache` is process-local and not invalidated on data mutations.**  
  The cache stores the result of heavy COUNT(*) queries for 10 seconds. If an admin (or any other process) inserts/updates/deletes rows in `enterprise`, `financial_data`, or `nbb_load_log` during that window, the stale data will be served. For a single-worker deployment this is a correctness issue; for multi-worker it is a consistency issue across workers.  
  **Why it matters:** Admin users may see incorrect counts (e.g., remaining backload, total companies) for up to 10 seconds after a mutation.  
  **Safest fix:** Either (a) add a `cache_clear` endpoint that can be called after mutations, or (b) reduce TTL to 2–3 seconds, or (c) document that the cache is intentionally stale and accept the trade-off.

- **backend/routers/admin.py: `nbb_backload_progress` refactored query may not be exactly equivalent for enterprises with multiple `nbb_load_log` rows.**  
  The old query applied the `NOT EXISTS` on `nbb_load_log` per row × per year inside the `FILTER` clause. The new query moves the `NOT EXISTS` into the `e_active` CTE, which is evaluated once. If an enterprise has a `NO_FILINGS` or `PDF_ONLY` log entry for one year but not another, the old query would exclude it only for the year where the log entry matched; the new query excludes it entirely from all year counts.  
  **Why it matters:** The stated equivalence (returns the same 664k for each year) may hold for the current data set, but the semantics differ. A future data change could cause divergence.  
  **Safest fix:** Move the `nbb_load_log` exclusion back into each per-year subquery, or add a comment explaining that the simplification is intentional and the data guarantees that `NO_FILINGS`/`PDF_ONLY` is enterprise-wide, not year-specific.

- **frontend/src/app/admin/page.tsx: `confirmDeleteFeedback` timer does not clear on unmount.**  
  The `window.setTimeout` in `deleteFeedback` sets a 5-second reset timer. If the component unmounts (e.g., user navigates away) before the timer fires, the callback will attempt to call `setConfirmDeleteFeedback` on an unmounted component, causing a React state update warning.  
  **Why it matters:** Minor console warning, no data corruption, but indicates a potential memory leak if many timers accumulate.  
  **Safest fix:** Store the timer ID in a ref and clear it in a `useEffect` cleanup function.

- **frontend/src/app/admin/page.tsx: `heavyPromise` is caught with an empty handler, swallowing errors.**  
  The line `void heavyPromise.catch(() => {});` silently discards any error from `loadHeavyData()`. If the heavy data fetch fails, the admin will see no error indication.  
  **Why it matters:** Admins may think data loaded successfully when it did not, leading to incorrect decisions.  
  **Safest fix:** Log the error to console or set an error state (e.g., `setHeavyError`) that can be displayed in the UI.

- **frontend/src/app/admin/page.tsx: `loadHeavyData` is called before `Promise.all` for core data, but the core data may depend on heavy data.**  
  The comment says heavy data is fired in parallel, but the code does not check whether any core data (e.g., `stats`, `users`) depends on heavy data results. If a future change introduces such a dependency, the parallel execution could cause a race condition.  
  **Why it matters:** No current regression, but the pattern is fragile.  
  **Safest fix:** Keep the parallel call but add a comment that core data must not depend on heavy data, or restructure to use `Promise.all` with both core and heavy.

- **backend/routers/admin.py: `_admin_stats_cache` is not thread-safe.**  
  The cache is a plain `dict` accessed without locks. Under FastAPI with async handlers, concurrent requests could race on `_admin_stats_cache["stats"] = (time.time(), stats)` and `cached = _admin_stats_cache.get("stats")`.  
  **Why it matters:** In rare cases, a stale or partially written tuple could be read, causing a `TypeError` or serving incorrect data.  
  **Safest fix:** Use `threading.Lock` or switch to `cachetools.TTLCache` which is thread-safe.

- **frontend/src/app/admin/page.tsx: `classify-all` uses `window.confirm` which is not accessible and blocks the event loop.**  
  The `window.confirm` dialog is a synchronous browser modal that cannot be styled and is not keyboard-navigable for screen readers.  
  **Why it matters:** Accessibility violation; also a poor UX pattern for modern web apps.  
  **Safest fix:** Replace with a custom modal component that can be styled and made accessible. For now, at minimum add `aria-label` and ensure the confirm dialog is focusable.</think>No material findings from provided context.