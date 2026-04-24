# 21-item backlog sprint — 2026-04-24

## Shipped to staging (16 items)

| # | Item | Where to test | Notes |
|---|------|--------------|-------|
| 1 | BTW copy button | Any `/company/[cbe]` header | Async clipboard + execCommand fallback for HTTP |
| 3 | Legal form (jf_label) shown on profile | Same as #1 | Uses existing `detail.jf_label` |
| 4 | Add-to-project Dialog overlay | `/favourites` ProjectCard → "+" button | Was cramped inline dropdown |
| 6 | Search location filter | `/search` → "Filter by location" row | Postal code / municipality / street; URL-synced |
| 7 | Gross margin milestone in P&L bridge | `/company/[cbe]` → P&L tab | Between Revenue and EBITDA |
| 9 | P&L bridge anchors on GM when no revenue | Same — test on abbreviated-scheme filer | Previously: bridge hidden entirely |
| 10 | Balance-sheet bridge 5-shade palette | `/company/[cbe]` → Balance sheet tab | Adaptive text-white on dark segments |
| 11 | EBITDA drill-down dialog | Click EBITDA KPI card on P&L tab | Revenue → CoS → GM → OpEx → EBITDA |
| 14 | Shareable company card | `/company/[cbe]` Export menu → Share card; or go direct `/s/[cbe]` | Public, no auth |
| 15 | SEO canonical + sitemap fix | `curl /sitemap.xml \| grep -c "<loc>"` now 50009 vs 9 | Route-handler implementation |
| 17 | Status page | `/status` | 60s auto-refresh of FE / API / DB |
| 18 | Glassmorphism marketing | `/showcase` | Separate from product routes |
| 19 | Person profile page | `/people/[name]` | Timeline of involvement, roles, holdings |
| 20 | Spiderweb layer toggles | `/company/[cbe]` → Network tab | Shareholders / directors / subsidiaries toggles |
| 21 (Tier 1) | Spiderweb legibility quick wins | Network tab | Saturated depth-3/4 colours, label-floor, hub-size |
| 16 | Use cases page (already done earlier) | `/use-cases.html` | Pre-existing |

## Deferred / blocked (7 items)

| # | Item | Blocker / reason |
|---|------|------------------|
| 2 | FTE audit | **Operator input needed**: code is consistent on rubric 9087 (report: `reports/fte-audit-2026-04-24.md`). Need 3 specific wrong-value companies to reproduce. |
| 8 | "Full P&L to net profit" | **Operator input needed**: the table already goes to net profit. Specific company + page where it doesn't? |
| 12 | Profile load perf | Diagnostic in `reports/profile-perf-2026-04-24.md`. Top fix = drop AI-insights pre-generation from critical path; non-trivial UX change, needs operator sign-off. |
| 13 | Conversational AI Q&A | Non-trivial (streaming backend + chat UI). Deferred pending operator scope call. |
| 21 (Tier 2/3) | Spiderweb hierarchical/dagre layout, density-adaptive, label-collision | Tier 1 shipped; operator to decide if Tier 1 is enough. |
| 22 | Admin revamp | Big effort. Deferred — operator to prioritise audit-first vs rewrite. |
| 23 | Interactive `/use-case.html` simulation | Non-trivial scripted flow; needs operator shape-call. |

## Reports filed

- `reports/fte-audit-2026-04-24.md` — all FTE references, code is correct
- `reports/profile-perf-2026-04-24.md` — top 3 bottlenecks, hit-list
- `reports/seo-indexing-2026-04-24.md` — root cause + fixes
- `reports/spiderweb-legibility-2026-04-24.md` — Tier 1-3 improvement plan
- `reports/batch-a-review.md` + `batch-a-security.md` — Ollama delegated review (clean)
- `reports/batch-a-security-manual.md` — manual security assessment
- `reports/batch-b-review.md` + `batch-b-security.md` — Ollama delegated review (clean)
- `reports/batch-b-review-manual.md` — manual review for D#6 additions

## Operational notes

- Staging Docker disk hit 98% during builds — I pruned 6 GB of orphaned
  "leadpeek" vs "leadpeek-staging" project duplicates to clear it.
- `docker-compose.staging.yml` currently includes `enrichment-worker-staging`
  and `staatsblad-bulk-worker-staging` which pull ~9 GB PyTorch images.
  Staging frontend-only rebuilds don't need them — consider splitting into
  a separate compose file to keep deploy disk-usage low.
- Staging nginx used to run under the old `leadpeek` compose project; I
  recreated it under the `leadpeek-staging` project so it shares a network
  with the new frontend/backend containers.

## Commits (master)

- `6d38fc8` Convert use-cases grid to horizontal carousel (pre-existing)
- `0be1f99` Batch A + D1 + SEO
- `4cb490e` Copy-CBE execCommand fallback
- `fb12c79` Batch B + D#6 + sitemap dynamic
- `da8b132` Sitemap: convert metadata route to Route Handler
- `50d9113` Batch E #19: Person profile page
- `52ea8d7` Batch F #14: Shareable company summary card at /s/[cbe]
- `bd708d6` Batch G #17: Public status page at /status
- `783f983` Batch G #18: Glassmorphism marketing page at /showcase
