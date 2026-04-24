# Batch B + Batch D #6 + sitemap review (manual) — 2026-04-24

Delegated ollama reviews hung again (429 retries plus upstream slowness). Manual review below while a retry runs in the background.

## Changes

- `frontend/src/app/company/[cbe]/_tabs/pnl-waterfall.tsx` — adds Gross Margin milestone between Revenue and EBITDA; handles no-revenue case by anchoring on Gross Margin (abbreviated-scheme filings). Reconciles Materials+Services to the filed 9900 subtotal and Personnel+Other-OpEx to the filed EBITDA, so the staircase always lands exactly on each milestone.
- `frontend/src/app/company/[cbe]/_tabs/ebitda-drilldown.tsx` — new Dialog component. Vertical tree showing Revenue → Cost of Sales → Gross Margin → Operating costs → EBITDA with absolute and % of revenue.
- `frontend/src/app/company/[cbe]/_tabs/pnl-tab.tsx` — makes the EBITDA KPI card clickable (keyboard-accessible via Enter/Space) to open the drilldown.
- `frontend/src/app/sitemap.ts` — `export const dynamic = "force-dynamic"` so the route renders per-request, not at build. Fetch retains its own 1h ISR hint via `next: { revalidate: 3600 }` so crawler hits don't thrash the backend.
- `frontend/src/i18n/*.json` — clickEbitdaDrilldown + search.postalCode/municipality/street + search.location translation keys (EN/NL/FR).

- `backend/routers/companies/search.py` — adds `postal_code`, `municipality`, `street` query params to `/api/companies/search`. Location filter builds an optional `loc_filter` CTE that is JOINed to `all_hits` when any filter is set. All user values bound via `%(name)s`, ILIKE patterns pre-escaped with `ilike_escape`.
- `frontend/src/lib/api.ts` — `searchCompaniesBucketed(q, loc?)` accepts an optional `LocationFilter` object; passes postal_code/municipality/street as query params.
- `frontend/src/app/search/page.tsx` — collapsible "Filter by location" row with 3 inputs (postal / municipality / street); reflects to URL; debounces through existing doSearch; clear button.

## Correctness

- **React hook usage:** `useState`, `useCallback`, `useEffect` all at top level. Dependency arrays correct. No conditional hook calls.
- **Keyboard accessibility:** EBITDA card has `role="button"`, `tabIndex={0}`, Enter/Space handler. Passes WCAG SC 2.1.1.
- **Null handling in drill-down:** `materials`, `services`, `personnel`, `otherOpex` all nullable; `signedEur` renders `—` when null. Residuals only rendered when `Math.abs(x) > 0.5`.
- **Domain range in waterfall:** includes `topValue` (revenue if present else gross margin), gross margin, EBITDA, EBIT, net profit — negative values render left of zero without clipping.
- **Gross margin fallback:** uses rubric 9900 if present, else `revenue - materials - services`. Won't render if neither revenue nor gross margin is positive.
- **No-revenue case:** when revenue is 0/null but GM > 0, waterfall skips Revenue + cost-of-sales rows, anchors on GM. Matches the operator's abbreviated-scheme ask (#9).
- **Search location filter SQL:** CTE only built when at least one filter set. Filter clauses use ILIKE + ESCAPE with ilike_escape — no injection. Final JOIN intersects only with `all_hits` enterprise_numbers, so the scored ranking is preserved within the filtered subset.
- **CBE short-circuit path:** intentionally ignores location filter (an exact CBE hit is unambiguous).

## Security

- **SQL injection:** every user value bound via `%(name)s`; the only dynamically assembled strings are column-level clause fragments with no user data.
- **ILIKE wildcard DoS:** `ilike_escape` wraps user input; users can't craft bare `%`/`_` to blow up the planner.
- **XSS:** all JSX interpolations use `{...}` (auto-escaped); no `dangerouslySetInnerHTML` added; URL params wrapped via `URLSearchParams` (encodeURIComponent).
- **Sitemap logs:** `console.error` in sitemap.ts writes to stderr only; no client response leakage.
- **Dialog:** `@/components/ui/dialog` (base-ui) provides backdrop, focus-trap, Escape dismiss. No new clickjacking surface.

## Verdict

Safe to merge. Will update if the retry review surfaces anything.
