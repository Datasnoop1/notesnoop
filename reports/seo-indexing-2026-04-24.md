# SEO Indexing Investigation — 2026-04-24

## Root causes (ranked by likelihood)

1. **Sitemap may fail silently.** `frontend/src/app/sitemap.ts` fetches `/api/sitemap/companies` server-side; if that endpoint is missing/slow/failing, the sitemap falls back to static pages only and 170K+ company profiles never reach Google.
2. **No canonical URLs on `/company/[cbe]`.** `frontend/src/app/company/[cbe]/layout.tsx` generates metadata but does not set `metadata.alternates.canonical`. Multiple CBE formats (with/without dots) risk being flagged as duplicates.
3. **Sitemap route exposure.** Confirm `/sitemap.xml` actually serves XML through the Next.js 16 metadata route.

## Greens (no action needed)

- `frontend/public/robots.txt` correctly references the sitemap.
- Root `layout.tsx` has `robots: { index: true, follow: true }` and OG tags.
- Production nginx does NOT send `X-Robots-Tag: noindex`. Staging correctly does.

## Fix list

| File | Change |
|------|--------|
| `frontend/src/app/sitemap.ts` | Add error logging; ensure DB-backed fallback listing at least CBEs |
| `frontend/src/app/company/[cbe]/layout.tsx` | Add `metadata.alternates.canonical = "https://datasnoop.be/company/${cbe}"` |
| `backend/` (sitemap companies route) | Verify `/api/sitemap/companies` exists and returns CBE list; add if missing |

## Operator actions (Google Search Console)

1. After fixes ship to prod, submit `https://datasnoop.be/sitemap.xml` via GSC URL inspector.
2. Request re-index on 3–5 high-value company profiles.
3. Check **Coverage** tab — "Discovered but not indexed" confirms the sitemap silently-fails hypothesis.
