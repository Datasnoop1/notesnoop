# /search performance — handoff

Status: not done. Operator still says "not there yet" after ~14
incremental optimizations. Front page → /search navigation feels
fast; editing the search term while already on /search is the
problematic path. Latest deploy may have made the front-page case
*slightly* slower.

This document is the prompt for the next conversation to start from.
Read `docs/product.md`, `docs/architecture.md`, and `docs/search.md`
first per the standing onboarding rule.

---

## Operator complaint (verbatim, in order)

1. "for some reason, search is really really really slow"
2. "its still really slow.; between typing a company name in the search field and something showing up.. at least 5-10secs"
3. "it has to be almost instant"
4. "still 10sec to load"
5. "from landingpage/homepage, search is fast / but when you are on search page and change keyword, its slow again"
6. "but overall, still needs to improve and be way faster.. this is critical ux"
7. "(cannot open dev tab on datasnoop, no right mouse)" — operator can't help with browser-side profiling
8. "better, but honestly not great"
9. "same again, loading from frontpage is almost instant.. but changing search word messes it up"
10. "after hard reset it seems fast, but then it slows down" — accumulating-work signal
11. "would say that front page is a little slower, adjusting search term is a tad faster. Overall, not there yet."

The repeated "from front page fast / editing search term slow"
contrast is the most diagnostic signal. Both paths fire the same
backend endpoints. The difference is purely client-side state /
re-render behaviour, accumulating over time.

---

## What's been done (commits on master, all deployed to staging)

| # | Commit | What |
|---|---|---|
| 1 | `1e447bd` | Initial bundle: location-only search, multilingual muni aliases, status chip, related-company suggestions in Add-to-project |
| 2 | `d805586` | search/loc-only: split into two CTEs (avoid full financial_latest scan) |
| 3 | `1c6d8ec` | postal-code equality + alias substring dedup |
| 4 | `5a44aee` | Hide people+events when location filter active |
| 5 | `aedda5d` | Don't block loading spinner on events endpoint |
| 6 | `8d93991` | events/search: skip OpenRouter embedding (was 1.5-2 s/call) |
| 7 | `14d3953` | Drop events bucket from /search entirely |
| 8 | `936c005` | React.memo + useCallback + useDeferredValue on result sections |
| 9 | `a76b90e` | Cache TTL 60 s → 3600 s + btree on `denomination_normalized` |
| 10 | `6d6fd52` | Pre-warm cache with top-50 popular queries on startup |
| 11 | `ca7eca8` | URL sync moved off keystroke path, input extracted to memoised `SearchTextInput` |

Plus a new btree index built CONCURRENTLY on prod DB (staging shares prod DB):
```sql
CREATE INDEX CONCURRENTLY idx_denom_norm_btree
ON denomination(denomination_normalized)
WHERE denomination_normalized IS NOT NULL;
```

---

## Current backend timings (staging, post-warm)

```
q=colruyt     companies: 80 ms / people: 100 ms
q=holding     companies: 90 ms / people: 100 ms
q=consulting  companies: 100 ms / people: 100 ms
q=tim         companies: 80 ms
q=invm        companies: 100 ms
random/cold   companies: 80-130 ms
```

Backend is no longer the bottleneck. Pre-warm + 1 h TTL means
realistic operator queries hit warm cache.

---

## Frontend state after commit `ca7eca8`

`frontend/src/app/search/page.tsx`:

- Input is now a **memoised `<SearchTextInput>` sub-component** with
  its own internal value state. Typing only re-renders this small
  component. The parent's `query` state, the URL (`history.replaceState`),
  and the API fetch are all updated **once per debounce window** (100 ms).
- `useDeferredValue(query)` is still passed into result sections so
  even when the parent does re-render after debounce, sections lag a
  frame.
- Sections (`CommercialSection`, `PeopleSection`) wrapped in
  `React.memo` (commit 936c005, in `_components/sections.tsx`).
- `toggleCompanyFav` / `togglePersonFav` wrapped in `useCallback`.
- Events bucket is fully removed from /search.
- Location-only flow: empty `q` + non-empty postal/muni/street works
  end-to-end.

---

## What's likely still wrong

The operator's "fast on hard reset, slows down with use" signal
points at **accumulating client-side state**, not backend latency.
Hypotheses to investigate, ranked by likelihood:

### 1. Header autocomplete not isolated from /search input
The header (`<HeaderSearch />` in `frontend/src/components/header-search.tsx`)
is a separate component that fires `/api/search/suggest` on every
keystroke globally. It might be rendered (and re-rendering) on the
/search page itself. Check whether typing in the /search page input
also triggers re-renders / fetches in the header autocomplete.

### 2. Memory / DOM accumulation across searches
Every search overwrites `companies` / `people` state, but **React
keeps old DOM nodes alive briefly during reconciliation**. With many
heavy `<CompanyCard>` and `<PersonCard>` children (each containing
links, formatting, tooltips, hover animations), reconciliation cost
grows with use even with `memo`. Consider:
- Virtual scrolling on the result list (e.g. `react-window`).
- Use `key={enterprise_number}` consistently to maximise React's
  ability to reuse DOM (already done).
- Profile with the React DevTools Profiler "Highlight updates" mode
  to see what is actually re-rendering on each keystroke.

### 3. Network panel never inspected
We never confirmed the slow phase from the operator's perspective is
actually the API call vs. the page load vs. the render. Operator
can't open dev tools (mentioned in turn 7). Two ways forward:
- Add lightweight client-side timing logs that POST to a
  `/api/_perf` endpoint so we capture real-world numbers.
- Or build a one-off internal "perf check" route that the operator
  can navigate to and screenshot.

### 4. Front-page-to-/search regressed slightly
Latest commit (`ca7eca8`) added a `useEffect` on `externalValue` to
sync the input from parent state. On initial mount this fires once
extra. Check if this matters when arriving via `?q=foo` from the
front page.

### 5. Bundle size / hydration cost
`/search` page bundle may have grown across this session. Check:
```bash
ssh root@62.238.14.150 \
  'docker exec leadpeek-staging-frontend-staging-1 du -sh /app/.next/static/chunks/'
```
If chunks are large, check for accidental imports of heavy modules
in the search page. The `Add-to-project` suggestions feature pulls
`getSimilarCompanies` dynamically — that is fine — but other
imports might not be.

### 6. PostgreSQL contention / staging-prod DB shared
Staging shares the prod Postgres DB. If a long-running prod query
holds a lock or eats connections, staging searches feel slow.
Check `pg_stat_activity` during a slow phase. (Earlier attempt
showed no slow queries during smoke tests, but the operator's slow
phases may not coincide with our checks.)

### 7. The user is testing on a slow connection or weak device
Hetzner Frankfurt → operator's location should be <50 ms. If their
machine is old or saturated, every render feels heavy. We can't
fix this directly but we can reduce CPU work per keystroke further.

---

## Recommended next steps (priority order)

### A. Confirm what is slow with telemetry (1-2 hours)
Add a per-search client-side timer that captures:
- Time from keystroke to debounce fire
- Time from fetch start to first byte
- Time from response to result render

POST these to a `POST /api/_perf` endpoint that just logs. Have the
operator do a typing session and pull the logs server-side.

### B. Inspect bundle / Next.js render cost (30 min)
- `du -sh .next/static/chunks` on prod and staging.
- Run Lighthouse against both staging /search and prod /search,
  share the numbers.
- Check React Profiler output — specifically "what re-renders on
  each keystroke?"

### C. Virtual-scroll the result list (1 hour)
`react-window` over `commercialList` + `peopleList`. The cards are
heavy enough that a list of 30 with formatting + tooltips +
hover-animation re-renders is genuinely noticeable on weaker
hardware.

### D. Switch search to a precomputed FTS column (medium effort, 1 day)
The cold-cache problem is mitigated by pre-warm + 1 h TTL but not
solved. A real fix is a `tsvector` column on `company_info(name)`
with a GIN index, replacing the trigram path on common-term
queries. See `docs/search.md` § 'Performance targets'.

### E. Stop the URL sync entirely on /search and accept losing the deep-link?
The history-replace work was the most likely accumulating cost.
We've moved it to debounce — but it still runs once per search.
Possible to skip URL sync while typing (only sync on Enter or
blur)? Trade-off: shareable URL on every search vs. zero-cost
typing.

---

## Files touched in this session

- `backend/routers/companies/search.py` — location-only path, aliases, helpers, cache TTL, pre-warm support
- `backend/routers/companies/detail.py` — status_assessment SQL + LATERAL on staatsblad_event
- `backend/routers/people.py` — cache TTL bump
- `backend/routers/staatsblad_events.py` — disabled OpenRouter embedding
- `backend/main.py` — `startup_search_prewarm` hook
- `frontend/src/app/search/page.tsx` — multiple iterations; current state has `SearchTextInput` sub-component
- `frontend/src/app/search/_components/sections.tsx` — memo wrappers on `CommercialSection` + `PeopleSection`
- `frontend/src/app/company/[cbe]/company-page-client.tsx` — status chip in header
- `frontend/src/app/company/[cbe]/types.ts` — `status_assessment` field
- `frontend/src/lib/api.ts` — same field on `CompanyDetail`
- `frontend/src/app/favourites/page.tsx` — Add-to-project suggestions block
- `frontend/src/i18n/{en,nl,fr}.json` — new keys for status chip + suggested-heading

## Standing rules from CLAUDE.md (do not skip)

- Run two review agents (correctness + security) before merging
  changes touching shared-prod surface (search, loaders, schema, etc.).
- Staging-first; operator approves prod deploy.
- For frontend-only deploys, use `docker compose up -d --build frontend`
  on the server — do NOT run `deploy.sh` (it waits 2 h for NBB backload).
- After any push to master, SSH and rebuild — auto-deploy is unreliable
  per `memory/project_auto_deploy.md`.

## Known operator constraints

- Non-technical; can't open dev tools (right-click disabled for them).
- Verifies on staging by typing into the UI; cannot read network
  panel timings.
- Strong preference for terse, plain-English updates (`memory/feedback_workflow.md`).
- Standing rule: ALWAYS staging-first, prod requires explicit approval
  (`memory/feedback_deploy_process.md`).
