# Profile page perf investigation — 2026-04-24

## Top 3 bottlenecks

### 1. AI Insights pre-generation (30–45% of profile load time)
- Where: `frontend/src/app/company/[cbe]/company-page-client.tsx:292-305`
- Why: `generateAiInsights()` fires via `requestIdleCallback` after enrichment fetch. No timeout. Backend hits OpenRouter multi-step pipeline → 5–15s.
- Fix: defer to a Web Worker (or drop from critical path). Show stale cache first, lazy-load fresh insights.
- Effort: **S**

### 2. Structure endpoint redundant queries (15–20%)
- Where: `backend/routers/companies/structure.py:81-145`
- Why: three separate `fetch_all()` calls for admins/shareholders/PIs, plus `merge_admins_with_staatsblad()` second pass in Python.
- Fix: batch into a single pre-merged query (windowed LEFT JOIN), or cache merged result.
- Effort: **M**

### 3. Financials pulls 45+ rubric codes (10–12%)
- Where: `backend/routers/companies/financials.py:645-651`
- Why: IN clause over `financial_data` with pivot in Python.
- Fix: push pivot into SQL (`json_agg()` + `GROUP BY`) or pre-pivot at ingest into `financial_latest`.
- Effort: **M**

## Secondary

- Sequential enrichment chain at `company-page-client.tsx:238-305` — batch enrichment + AI insights into one endpoint.
- NBB auto-load refetches structure/financials after `/load` — have `/load` return updated data.

## Minimal hit-list (50% load reduction)

1. Move AI Insights to background Web Worker with 2s defer — `company-page-client.tsx:292-305` (S)
2. Single `/enrichment-with-insights` endpoint (new) — `backend/routers/companies/enrichment.py` (M)
3. Merge structure admins in SQL via window CTE — `backend/routers/companies/structure.py:81-105` (M)

## Hypotheses needing server-side measurement

- Is `financial_summary` view materialized or re-aggregated per request? `EXPLAIN ANALYZE` on a mid-size company.
- Is the 1s politeness sleep in `/load` (line 291) the bottleneck or NBB response time?
- Does the Grok call in `ai_insights_pipeline` dominate, or is scraping/URL discovery the bottleneck?
