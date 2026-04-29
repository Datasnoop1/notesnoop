# DataSnoop — To-Do List

Last updated: 2026-04-29 (intake from emails daaaaaay/deaaaaaz/diaaaaa7/dmaaaaa9 — 3 new items + 1 question)

---

## Quick UX / UI fixes

| # | Item | Source | Status |
|---|------|---------|--------|
| 1 | ~~Add copy button next to BTW number on company profile~~ | Email 2026-04-22 | done |
| 2 | ~~FTE references incorrect in several places — audit and fix~~ | Email 2026-04-22 | done |
| 3 | ~~Company type (legal form) should be shown on the profile page~~ | Email 2026-04-22 | done |
| 4 | "Add to project" popup should hover/overlay — currently not readable (too little space) | Email 2026-04-22 | in review (branch `ux/add-to-project-popup-readability`) |
| 26 | Clicking a company in the screener should open its profile in a NEW tab | Email 2026-04-27 | in progress (`feat/screener-spider-perf-2026-04-27`) |
| 27 | Screener: column widths should be user-adaptable (drag-resize) | Email 2026-04-27 | in progress (`feat/screener-spider-perf-2026-04-27`) |
| 28 | Screener: add a column showing semantic keywords next to the company name | Email 2026-04-27 | in progress (`feat/screener-spider-perf-2026-04-27`) |
| 34 | When adding a company to a project, propose related companies (like the aggregate sheet does) | Email 2026-04-28 | pending |
| 35 | Company profile should show status (active / bankrupt / dissolved — example PLN) | Email 2026-04-28 | pending — needs source: not in `company_info` today; check KBO `EnterpriseStatusCode` and/or Staatsblad |

## Search improvements

| # | Item | Source | Status |
|---|------|---------|--------|
| 5 | ~~Search "invm bv" should still find INVM — strip / ignore legal form suffix~~ | Email 2026-04-22 | done |
| 6 | ~~Add location filter to search (postal code, town, street)~~ | Email 2026-04-22 | done (`/search/page.tsx` line 51) |
| 36 | **BUG** — Search "filter by address does not work" (operator-reported regression on location filter) | Email 2026-04-28 | pending — reproduce + fix |

## Financial display

| # | Item | Source | Status |
|---|------|---------|--------|
| 7 | ~~P&L bridge: show gross margin line (absolute + %)~~ | Email 2026-04-24 | done |
| 8 | ~~Full P&L tab should go all the way down to net profit~~ | Email 2026-04-22 | done |
| 9 | ~~P&L bridge: if no revenue known, show starting from gross margin instead of hiding the bridge~~ | Email 2026-04-20 | done |
| 10 | Balance sheet bridge: add more gray shades (currently too few tones) | Email 2026-04-20 | pending |
| 11 | EBITDA drill-down metric tree (click EBITDA → see contributing lines) | Memory 2026-04-19 | pending |

## Performance

| # | Item | Source | Status |
|---|------|---------|--------|
| 12 | ~~Company profile load is too slow — investigate and speed up~~ | Email 2026-04-22 | done |
| 29 | Company profile: financials section must finish loading in ≤ 15 sec | Email 2026-04-27 | in progress (`feat/screener-spider-perf-2026-04-27`) |
| 30 | Company profile: AI-insights section must finish loading in ≤ 15 sec | Email 2026-04-27 | in progress (`feat/screener-spider-perf-2026-04-27`) |
| 31 | ~~AI insights appear broken — investigate and fix~~ | Email 2026-04-27 | done (operator-confirmed 2026-04-27) |

## Admin

| # | Item | Source | Status |
|---|------|---------|--------|
| 22 | ~~Major admin dashboard revamp — slow, broken UX; full audit and rebuild~~ | 2026-04-24 | done |

## AI / Product features

| # | Item | Source | Status |
|---|------|---------|--------|
| 13 | Conversational AI Q&A on company profile page | Memory 2026-04-19 | pending |
| 14 | Shareable company summary card (link / image) | Memory 2026-04-19 | pending |

## People

| # | Item | Source | Status |
|---|------|---------|--------|
| 19 | Person profile page — companies involved in, timeline of involvement, roles | 2026-04-24 | pending |
| 33 | When a representative / admin is a legal entity, also surface who represents that entity (recursive lookup) | Email 2026-04-27 | in progress (`feat/screener-spider-perf-2026-04-27`) |

## Network graph (spiderweb)

| # | Item | Source | Status |
|---|------|---------|--------|
| 20 | ~~Add toggle buttons to show/hide shareholders / directors / subsidiaries layers~~ | 2026-04-24 | done |
| 21 | Spiderweb legibility deep-dive — network graph gets crowded on complex companies; investigate layout algorithm, clustering, label collisions, zoom/focus mode | 2026-04-24 | pending |
| 32 | Spiderweb: clicking an entity should also offer "open profile in new tab" | Email 2026-04-27 | in progress (`feat/screener-spider-perf-2026-04-27`) |

## SEO / Discoverability

| # | Item | Source | Status |
|---|------|---------|--------|
| 15 | Google Search Console: pages not being indexed — investigate cause and fix | Email fwd 2026-04-20 | pending — needs scope clarification |

## Marketing / Demo

| # | Item | Source | Status |
|---|------|---------|--------|
| 16 | ~~Write use cases page / section~~ | Email 2026-04-18 | done |
| 17 | Status page (uptime / service status) | Email 2026-04-18 | pending |
| 18 | Build glassmorphism-style demo page for DataSnoop | 2026-04-24 | pending |
| 23 | Build interactive tool simulation at `/use-case.html` on staging — same design as the real app, but scripted/fake data; variant on item 18 | 2026-04-24 | pending |

---

## Done

| # | Item | Shipped |
|---|------|---------|
| 1 | Copy button next to BTW number | shipped 5c85848 (deep-audit pass) |
| 2 | FTE references audit / fix | shipped (no broken refs found in current code) |
| 3 | Legal form (juridical form) on company profile | shipped 5c85848 (`detail.jf_short`) |
| 5 | Search strips legal form suffix (BV / NV / etc.) | 2026-04-24 |
| 7 | P&L bridge: gross margin line | shipped (`pnl-waterfall.tsx`) |
| 8 | Full P&L tab to net profit | shipped (`pnl-tab.tsx`) |
| 9 | P&L bridge fallback to gross margin when revenue missing | shipped (`pnl-waterfall.tsx`) |
| 12 | Company profile load speed | shipped 5c85848 (deep-audit pass) |
| 6 | Search location filter (postal code / municipality / street) | shipped (`/search/page.tsx`) |
| 16 | Write use cases page / section | 2026-04-24 |
| 20 | Spiderweb: shareholder / director / subsidiary layer toggles | shipped (`network-graph.tsx`) |
| 22 | Admin dashboard revamp | shipped (Phase 1/2 + Admin rebuild Phase-22) |
| 24 | Spiderweb: current-only by default + "Show historical" toggle | 2026-04-26 |
| 25 | Removed misleading "merged" provenance badge from people pages | 2026-04-26 |
