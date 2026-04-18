# DataSnoop — Product Vision & Context

**Read this first** if you're a new assistant context window. Together with
`docs/architecture.md` and `CLAUDE.md`, it gives you the product, the
users, and the current direction. Without it you'll drift — drift
manifests as technically-correct decisions that go against how the
product is being shaped.

---

## What DataSnoop is

A **Belgian company intelligence platform** that combines three
public data sources into a single screener / profile / benchmark tool:

1. **KBO** (Kruispuntbank van Ondernemingen / Crossroads Bank for
   Enterprises) — Belgium's official company register. Covers every
   registered entity, directors, shareholders, addresses, NACE codes.
2. **NBB CBSO** (National Bank of Belgium, Central Balance Sheet Office) —
   annual accounts (P&L, balance sheet, cash flow) filed by every
   entity required to deposit (most formal corporate entities).
3. **AI enrichment** (OpenRouter + scraped company websites) — plain-
   English business descriptions, product lists, customer segments.

Think of it as a **self-hosted Belfirst / Graydon alternative**. The
reference points customers know are Belfirst (expensive, B2B),
Graydon, and the NBB's own consult.cbso.nbb.be (slow, scrapy).

---

## Who the users are

1. **Private equity deal-sourcers** — scanning Belgian SMEs by sector,
   revenue, EBITDA, ownership structure for acquisition targets.
2. **M&A / corporate finance advisors** — diligence support on specific
   targets, peer benchmarks, comparables lists.
3. **Professional curious** — accountants, lawyers, strategy
   consultants who need a quick company fact-sheet without paying
   Belfirst's €5k/year.
4. **Anonymous visitors** — we opened prod to public browsing recently.
   Free tier sees everything; pro-tier actions (expensive AI calls,
   bulk exports) are tier-capped.

The platform is not for:
- Direct marketing (KBO licence explicitly prohibits this — see
  tech-debt Group A on bulk-export guardrails).
- Credit scoring (we are not a credit bureau).
- Real-time news / market data (different product).

---

## Core product surfaces

| Surface | What the user does |
|---|---|
| **Landing** | Google-style search box. Types a company name, CBE, or VAT. |
| **Search results** | Top matches across companies + people, with revenue snapshot. |
| **Company profile** | Tabs: Summary · Financials (P&L / Cash Flow / Balance Sheet / Credit / Valuation) · Network · People & Ownership · Publications · Benchmark · Similar. |
| **Screener** | Filter by NACE sector, revenue / EBITDA / margin bands, region, FTE, age, ownership. Export CSV. |
| **Compare** | Side-by-side P&L / BS / ratios for up to ~5 companies. |
| **Aggregate** | Sum KPIs across a basket of companies (useful for "show me the total of these 40 targets"). |
| **Stats** | Platform-wide aggregates by sector / province / size / evolution. |
| **Outperformers** | Pre-computed leaderboards (revenue growers, margin leaders, etc.) by sector. |
| **Favourites + Projects** | Personal lists of companies to revisit. Free tier capped. |
| **Account** | Subscription mgmt, language, feedback. |
| **Admin** (internal) | Traction, readiness, users, feedback, polls, tiers, activity, costs, Stripe payments, settings. |

---

## Tiering model

Three tiers, enforced by `TierLimitMiddleware` in the backend, keyed by
`user_roles.role`:

- **anon** — unauthenticated. Sees everything, hits hard daily caps on
  expensive endpoints (AI insights, extract-admins, similar/AI).
- **pro** — paid subscription (€49/mo via Stripe). Higher caps, full
  AI features, CSV exports.
- **admin** — internal ops. Bypasses tier caps. Access to
  `/api/admin/*` routes.

**Design principle**: free users never hit a "please sign up" wall on
read-only surfaces. Limits only kick in on costly actions. This is an
explicit operator decision (2026-04-17 session) — any audit item
suggesting `Depends(get_current_user)` on a read path should be
reframed as "add a tier limit" instead.

---

## Where we are now (2026-04-17 snapshot)

**Live on prod:**
- Full feature set above, less a few admin pages still desktop-focused.
- Mobile pass (clusters A–E) shipped: landing / search / screener /
  nav / company profile + all tabs / compare / aggregate / stats /
  outperformers / favourites / people tuned for 375px.
- NBB integration using fresh subscription keys (rotated on 2026-04-17
  after the old key was revoked by NBB without notice).
- NBB `/load` open to anonymous callers with a 3-wide concurrency
  semaphore + 1.5s loader delay (politeness toward NBB's rate limit).
- AI insights + AI-similar anonymous (tier-capped).
- Stripe checkout redirects now Origin-aware (staging testers don't
  bounce to prod).
- Session persistence fix: rolled back the apex-domain cookie
  experiment that broke same-session nav.

**On deck (tech-debt.md):**
- PII bulk-export guardrails (regulatory pressure, KBO licence).
- Observability: half our NBB error paths swallow exceptions
  silently. Makes prod debugging painful.
- Performance hot paths: `TierLimitMiddleware` runs DB queries on
  every request, `/stats/sectors` pulls ~300k rows into Python.
- Async refactor: sync `requests` inside `async def` blocks the
  event loop during NBB calls.

**Closed investigations:**
- **SDMX-first NBB integration — REJECTED.** The SDMX endpoint at
  `https://nsidisseminate-stat.nbb.be/rest/` only publishes
  sector-aggregate statistics, not per-enterprise filings. It can't
  replace the CBSO subscription-keyed API. Decision recorded
  2026-04-18 by the operator after the prototype came back negative.
  Implication: we stay on CBSO, which means we keep paying the
  silent-key-rotation tax. Mitigation is the auto-rotation tool plus
  the hourly health-check alert.

---

## Direction / aspirations (not scheduled, but shaping decisions)

1. **Language**: Dutch / French / English UI. Backend data sometimes
   drifts between languages (NBB sends NL/FR/EN, we pick NL when both).
2. **Mobile parity**: we want a solo analyst on a phone in a meeting to
   pull a target's profile cleanly. Cluster E polish still has admin-
   page weaknesses.
3. **Bulk export with guardrails**: sophisticated users need CSV /
   Excel exports. But KBO's licence forbids personal-data exports for
   marketing. The tension is resolved by tier-gating export size, not
   blocking it.
4. **PE workflow primitives**: Favourites + Projects exist. Missing:
   deal pipeline states, notes with mentions, shared lists, task
   assignment. These are roadmap items, not urgent.
5. **LinkedIn enrichment**: placeholder page today. Scraping LinkedIn
   is legally fragile; will probably need a dedicated data provider.

---

## Non-goals

- **Real-time data**: annual accounts are filed once a year, sometimes
  with a 6–12 month lag. Don't chase "up-to-the-minute".
- **Pan-European coverage**: Belgian-first. Expansion to NL / LU is a
  future option, not this year.
- **Black-box scoring / ML-opaque outputs**: all "insight" outputs
  must have traceable source data (rubric code, filing date, etc.)
  so a PE analyst can defend the number to an IC.
- **Being a CRM**: we list companies and their relationships. We do
  not track sales reps, meetings, call notes. If someone wants that,
  they export and plug it into HubSpot.

---

## Operator profile

- **Non-technical founder.** Validates work by visual checks on staging.
- Speaks Dutch / English interchangeably.
- Uses Claude Code as full dev + ops (solo build).
- Expects: plain-English updates, no unexplained jargon; tight
  deploys (staging → prod, never prod-direct); review agents before
  every master merge; explicit approval for prod deploys.
- Will delegate broadly ("just do everything") when he trusts the
  process. Never take that as permission to skip review gates.

See also `~/.claude/projects/.../memory/user_profile.md`.
