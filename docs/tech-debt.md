# Tech debt backlog

Findings from the four parallel audits run on 2026-04-17 (correctness,
performance, security, server resources). Ordered by severity within
each section. File paths and line numbers were accurate at the time
of the audit; numbers drift as files change.

This doc is for triage only — nothing here is scheduled work. Any
item the operator wants to tackle becomes its own branch.

---

## CRITICAL — prod-affecting, should be scheduled

### 1. Security: anonymous PII exposure on people / structure / network endpoints
Several endpoints return director and shareholder names + mandates
without any auth check. GDPR lawful-basis is weak when bulk lookup
is possible without a binding T&Cs acceptance.

Endpoints:
- `backend/routers/people.py:35` `GET /api/people/search`
- `backend/routers/people.py:93` `GET /api/people/{name}/connections`
- `backend/routers/people.py:321` `GET /api/people/{name}/enrichment`
- `backend/routers/companies/structure.py:28` `GET /api/companies/{cbe}/structure`
- `backend/routers/companies/structure.py:124` `POST /api/companies/{cbe}/extract-admins` *(no auth at all — also burns OpenRouter credits on every anonymous call)*
- `backend/routers/companies/network.py:27, 342` network + deep-network
- `backend/routers/graveyard.py:229` bankrupt-companies-per-person lookup

Recommended: require `Depends(get_current_user)` (not admin, just signed
in so requests are attributable), add a T&Cs acceptance flow binding
the user to KBO's direct-marketing prohibition. `extract-admins`
specifically needs auth AND a per-user cap because of the OpenRouter cost.

### 2. Correctness: Stripe checkout URLs hardcoded to datasnoop.be
`backend/routers/stripe_pay.py:53-54, 84-85` — success/cancel redirect
URLs are literal `https://datasnoop.be/…`. Anyone testing billing on
staging gets bounced to prod after payment. Fix: read a
`FRONTEND_BASE_URL` env var and thread it through.

### 3. Correctness: blocking HTTP + `time.sleep(1)` inside `async def`
`backend/routers/companies/financials.py:57, 110, 120` and
`backend/routers/staatsblad.py:32`. Synchronous `requests.get` inside
an `async` route blocks the uvicorn event loop — one slow NBB filing
call stalls every other concurrent request on that worker. The
`time.sleep(1)` between filings makes it worse (up to 5s of frozen
loop per /load call). Fix: switch to `httpx.AsyncClient` +
`await asyncio.sleep`.

### 4. Security: no server-side guardrail against bulk director exports
The tier table has an `export_per_day` column but no route enforces
it — CSV exports happen entirely client-side after `/api/screener`
returns rows. A single authenticated call can page 1000+ rows per
minute, harvesting director names in bulk. GDPR recital 47 and the
KBO open-data licence both prohibit direct-marketing use, and we have
no technical backstop. Fix: cap `limit` on `/api/screener` for
non-premium tiers, add a server-side `GET /api/screener/export`
that is tier-gated.

---

## HIGH — user-visible or risk-adjacent

### 5. Performance: tier-limit middleware runs a DB query on every API request
`backend/main.py:238-279` issues `COUNT(*) FROM activity_log WHERE
user_email = %s AND created_at >= CURRENT_DATE` for every API hit,
plus a synchronous `INSERT` into `activity_log`. Two blocking round-
trips per request. Fix: cache counts in Redis (`quota:{user}:{type}:
{YYYY-MM-DD}`) with daily TTL.

### 6. Performance: `/stats/sectors` and `/stats/provinces` pull all rows into Python
`backend/routers/stats.py:182-247, 265-273`. `SELECT fl.*, ci.nace_code
FROM financial_latest fl JOIN company_info ci` returns hundreds of
thousands of rows; aggregation happens in a Python `defaultdict`.
Fix: push the `GROUP BY` + `percentile_cont` into SQL.

### 7. Performance: `/companies/{cbe}/similar` fires 20+ correlated subqueries
`backend/routers/companies/similar.py:77-128` runs a scalar subquery
per metric against the same NACE peer set, 20× per company profile
page load. Fix: one `CROSS JOIN LATERAL` or window-function pass.

### 8. Performance: people-search double-ILIKE without trigram index
`backend/routers/people.py:50-66` does `WHERE name ILIKE '%q%'` on
`administrator` (millions of rows) and `shareholder`. Hot endpoint,
fires on every keystroke. Fix: `CREATE EXTENSION pg_trgm` (already
present) + GIN trigram index on `administrator(name)` and
`shareholder(name)`, switch to `name %% q`.

### 9. Performance: company profile cascade — 6-8 sequential round trips
`frontend/src/app/company/[cbe]/company-page-client.tsx:174-236, 338-346,
359-378, 397-416`. Initial `Promise.all` is good, but then the auto-
load overlay chains `getEnrichment` → AI insights → admin extraction
→ lazy tab fetches. First interaction can issue 6-8 sequential
HTTP calls. Fix: batch enrichment + insight preload; parallelise
admin-extract with the initial triple.

### 10. Security: GET /api/polls is user-gated instead of admin-gated
`backend/routers/polls.py:125-142`. Comment calls it "admin
endpoint" but uses `get_current_user`, so any signed-in user can
read per-choice vote breakdowns. Fix: swap to `_require_admin`.

### 11. Correctness: pervasive silent `except Exception: pass` in NBB ingest
`backend/routers/companies/financials.py:213-214, 229-230, 257-258,
281-282, 293-294` plus `backend/routers/companies/enrichment.py:38-39,
54-55, 104-105, 110-111, 196-197, 220-221`. Failures disappear into
the void; a broken enrichment cache looks like "every request is
slow" with no signal. Fix: at minimum `logger.debug(..., exc_info=True)`.

### 12. Correctness: N+1 in admin insights endpoint
`backend/routers/admin.py:318-333`. Loops over up to 10 CBEs and
fetches the name one at a time. Fix: one `WHERE enterprise_number IN (...)`
and build a dict.

### 13. Security: JWT verification fallbacks are permissive
`backend/auth.py:80-81, 89, 102`. Missing `kid` falls back to
`jwks["keys"][0]` (accepts tokens signed with any key during rotation
windows); `verify_aud=False` accepts tokens minted for a different
Supabase app. Fix: require exact `kid` match, enable `verify_aud`
with `"authenticated"`.

### 14. Security: no Content-Security-Policy header
`nginx/default.conf:21-24`. Sets X-Frame-Options, X-Content-Type-
Options, X-XSS-Protection, Referrer-Policy, HSTS, but no CSP. For a
Next.js app loading Stripe Checkout + Supabase JS, a CSP adds real
XSS defence.

### 15. Correctness: React stale-closure races in company-page-client
`frontend/src/app/company/[cbe]/company-page-client.tsx:174-239, 328-355`
use `useEffect` with `[cbe]` deps but no `AbortController` / `ignored`
flag. If `cbe` changes mid-flight a stale response overwrites newer
state. Masked today by the `key={cleanCbe}` in `page.tsx:34` which
force-remounts; bites if that key is ever removed.

### 16. Correctness: `similar-tab` triggered-ref guard blocks refetch on cbe change
`frontend/src/app/company/[cbe]/_tabs/similar-tab.tsx:57, 158-164` —
`triggered.current` is set true on first fire and never reset. Same
pattern in `publications-tab.tsx:156-161`. Same `key=` masking.

---

## MEDIUM — cleanup / footguns

### 17. Dead code: compare-tab state in company-page-client
`company-page-client.tsx:22, 124-125, 409-410, 605-628` — `setSimilarSort`
never called; `sortedSimilar` memo, `similarCompanies` state, and the
`getSimilarCompanies` call in `handleTabChange` are all orphaned
since SimilarTab fetches its own data.

### 18. Admin: users-table row actions don't fit mobile
`backend/routers/admin.py:2052` renders 4× `Button size="xs"` inline
actions (Block / Pro / Admin / Trash). At <sm, they force horizontal
scroll off-screen. Fix: collapse to a kebab dropdown on mobile.

### 19. Admin: tier-config + poll-option inputs trigger iOS zoom
`admin/page.tsx:2789, 2802` (`h-8 text-sm`) and `2541-2556`
(`h-7 text-xs`). 18+ fields across tier and poll admin pages.
Fix: `h-10 text-base sm:h-7 sm:text-xs`.

### 20. Stats evolution clause string-interpolates province via allow-list
`backend/routers/stats.py:13-30, 140-156` — safe today because
`VALID_PROVINCES` whitelist, but fragile. Fix: parameterise the
12-way CASE as a `WHERE ci.zipcode BETWEEN %s AND %s`.

### 21. People search nested tables — now wrapped; still no sticky col
`frontend/src/app/people/page.tsx:308, 356` (addressed in today's
cluster C pass — wrapped in `overflow-x-auto`, `min-w-[640px]`).
Further polish: sticky first column on scroll.

### 22. FormulaTooltip in-tooltip click closes it
`frontend/src/app/company/[cbe]/helpers.tsx` — the outside-click
listener fires on any click including inside the tooltip bubble,
preventing text selection. Fix: add `aria-expanded` and stop-
propagation on bubble clicks (stop-prop already added, but document
listener needs a target check).

### 23. Console.logs left in production
`frontend/src/app/company/[cbe]/_tabs/valuation-tab.tsx:78`,
`frontend/src/components/copy-protection.tsx:61, 65`.

### 24. TypeScript `as any` cluster
`company-page-client.tsx:566-573` hides real shape mismatches between
`StructureData`/`FinancialsData` and the exporter's expected inputs.
Refactoring either side will silently break exports.

### 25. `setTimeout(..., 3000)` in company-page-client never cleared
Line 323. If the user navigates away while the load overlay is
dismissing, React warns about state update on unmounted component.
Fix: store id in a ref, clear in cleanup.

### 26. Hardcoded datasnoop.be in multiple places
Beyond the Stripe URLs (CRITICAL #2), various docs/comments assume
production hostname. Mostly benign; worth centralising for future
white-label / multi-env work.

### 27. Tier-limit middleware doesn't classify `/api/people/*` or `/structure`
`backend/main.py:156` — these PII-read endpoints are uncapped under
any tier. Pairs with CRITICAL #1.

---

## LOW — notes, nice-to-haves

- `admin/page.tsx:444, 2919` label hashed tokens as "ip" in admin UI —
  operators may think they're raw IPs.
- Several `text-[9px]`/`text-[10px]` font sizes still scattered
  across `admin/page.tsx`, `screener/page.tsx`, `compare/page.tsx`
  (mobile clusters A–E touched the obvious ones; admin is deepest).
- Stats tooltip widths are fixed; on a 375px screen a wide tooltip
  can overflow. Recharts usually flips position, but not guaranteed.
- `.env.example` — clean (no real secrets, only placeholders).

---

## Server resources — audit result

See the 2026-04-17 server audit. Summary: 82% disk usage, driven
almost entirely by docker build cache (3.03 GB reclaimable) and two
stale staging images (~681 MB). Single zero-risk prune would take
the server to ~74%. No data hoarding, no log leaks, all containers
healthy, no rogue screen sessions. Recommended prunes await
operator approval.
