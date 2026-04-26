# DataSnoop — To-Do List

Last updated: 2026-04-26

---

## Quick UX / UI fixes

| # | Item | Source | Status |
|---|------|---------|--------|
| 1 | Add copy button next to BTW number on company profile | Email 2026-04-22 | pending |
| 2 | FTE references incorrect in several places — audit and fix | Email 2026-04-22 | pending |
| 3 | Company type (legal form) should be shown on the profile page | Email 2026-04-22 | pending |
| 4 | "Add to project" popup should hover/overlay — currently not readable (too little space) | Email 2026-04-22 | pending |

## Search improvements

| # | Item | Source | Status |
|---|------|---------|--------|
| 5 | ~~Search "invm bv" should still find INVM — strip / ignore legal form suffix~~ | Email 2026-04-22 | done |
| 6 | Add location filter to search (postal code, town, street) | Email 2026-04-22 | pending |

## Financial display

| # | Item | Source | Status |
|---|------|---------|--------|
| 7 | P&L bridge: show gross margin line (absolute + %) | Email 2026-04-24 | pending |
| 8 | Full P&L tab should go all the way down to net profit | Email 2026-04-22 | pending |
| 9 | P&L bridge: if no revenue known, show starting from gross margin instead of hiding the bridge | Email 2026-04-20 | pending |
| 10 | Balance sheet bridge: add more gray shades (currently too few tones) | Email 2026-04-20 | pending |
| 11 | EBITDA drill-down metric tree (click EBITDA → see contributing lines) | Memory 2026-04-19 | pending |

## Performance

| # | Item | Source | Status |
|---|------|---------|--------|
| 12 | Company profile load is too slow — investigate and speed up | Email 2026-04-22 | pending |

## Admin

| # | Item | Source | Status |
|---|------|---------|--------|
| 22 | Major admin dashboard revamp — slow, broken UX; full audit and rebuild | 2026-04-24 | pending |

## AI / Product features

| # | Item | Source | Status |
|---|------|---------|--------|
| 13 | Conversational AI Q&A on company profile page | Memory 2026-04-19 | pending |
| 14 | Shareable company summary card (link / image) | Memory 2026-04-19 | pending |

## People

| # | Item | Source | Status |
|---|------|---------|--------|
| 19 | Person profile page — companies involved in, timeline of involvement, roles | 2026-04-24 | pending |

## Network graph (spiderweb)

| # | Item | Source | Status |
|---|------|---------|--------|
| 20 | Add toggle buttons to show/hide shareholders / directors / subsidiaries layers | 2026-04-24 | pending |
| 21 | Spiderweb legibility deep-dive — network graph gets crowded on complex companies; investigate layout algorithm, clustering, label collisions, zoom/focus mode | 2026-04-24 | pending |

## SEO / Discoverability

| # | Item | Source | Status |
|---|------|---------|--------|
| 15 | Google Search Console: pages not being indexed — investigate cause and fix | Email fwd 2026-04-20 | pending |

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
| 5 | Search strips legal form suffix (BV / NV / etc.) | 2026-04-24 |
| 16 | Write use cases page / section | 2026-04-24 |
| 24 | Spiderweb: current-only by default + "Show historical" toggle | 2026-04-26 |
| 25 | Removed misleading "merged" provenance badge from people pages | 2026-04-26 |
