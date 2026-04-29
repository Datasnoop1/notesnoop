"""Companies enrichment router — AI summaries, scraping, insights, feedback."""

import asyncio
import json
import logging
import re
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from db import fetch_all, fetch_one, execute
from auth import get_current_user, optional_user
from ai_client import (
    ai_complete,
    ai_insights_pipeline,
    call_elaboration_narrative,
    PHASE_5_ELABORATION_ENABLED,
)
from utils import clean_cbe
from ._helpers import _serialize_row

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# POST /api/companies/{cbe}/summarize-publications
# ---------------------------------------------------------------------------

class SummarizePublicationsBody(BaseModel):
    refresh: bool = False


def _importance_for_event_type(event_type: str, sub_type: str | None) -> str:
    """Map an 8-category event_type onto the UI's routine/notable/significant
    axis, used for the publication-tab summary cards."""
    sub = (sub_type or "").lower()
    if event_type == "liquidation_event" and sub in (
        "liquidation_open", "bankruptcy", "judicial_reorganisation"
    ):
        return "significant"
    if event_type in ("ma_event",):
        return "significant"
    if event_type in ("capital_event", "share_transfer", "ownership_change"):
        return "notable"
    if event_type in ("admin_event", "corporate_change"):
        return "notable"
    return "routine"


def _synthesise_structured_summary(events: list[dict]) -> dict:
    """Build a structured `events[]` array for the publication-summary
    card UI directly from staatsblad_event rows, no LLM call required.

    Shape matches the existing publication_summary cache format so the
    frontend keeps working unchanged.  When the caller wants prose, a
    separate lightweight Haiku call can be layered on top.
    """
    ui_events = []
    for ev in events:
        t = (ev.get("event_type") or "other_notable").strip()
        sub = (ev.get("sub_type") or "").strip()
        pub_date = ev.get("pub_date")
        date_str = str(pub_date) if pub_date else None
        if ev.get("event_date"):
            date_str = str(ev["event_date"])
        what_pieces = [ev.get("summary") or ""]
        if ev.get("person_name") and ev.get("person_role"):
            what_pieces.append(f"({ev['person_name']}, {ev['person_role']})")
        what = " ".join(p for p in what_pieces if p).strip() or "Filing recorded"
        ui_events.append({
            "date": date_str,
            "type_raw": f"{t}/{sub}" if sub else t,
            "what": what,
            "context": ev.get("summary") or "",
            "importance": _importance_for_event_type(t, sub),
        })
    significant = any(e["importance"] == "significant" for e in ui_events)
    notable_count = sum(1 for e in ui_events if e["importance"] == "notable")
    pattern_note = None
    if significant:
        pattern_note = "Includes at least one significant event (M&A / dissolution / bankruptcy)."
    elif notable_count >= 3:
        pattern_note = f"{notable_count} notable events in the recent window — board / capital activity."
    return {
        "events": ui_events,
        "pattern_note": pattern_note,
        "risk_flag": significant,
    }


@router.post("/{cbe}/summarize-publications")
async def summarize_publications(
    cbe: str,
    body: Optional[SummarizePublicationsBody] = None,
    lang: str | None = None,
    user=Depends(optional_user),
):
    """Generate structured AI analysis of recent Staatsblad events.

    Phase 3d rewire: instead of running the LLM over
    publication-type labels, we synthesise the structured summary
    DIRECTLY from `staatsblad_event` rows (already extracted by the
    backfill + daily incremental). This is cheaper, faster, and
    accurate — we're reading actual filing content, not guessing from
    labels.

    When fewer than 3 structured events exist for this CBE, we fall
    back to the legacy label-based LLM summarisation so profiles with
    no Stage-3 coverage yet still get a useful card.

    ``lang`` (``nl``/``fr``/``en``) still controls the output
    language of the fallback LLM path; the structured path emits
    English `what`/`context` strings extracted from the filing itself.
    """
    cbe = clean_cbe(cbe)
    refresh = body.refresh if body else False

    # Ensure column exists (idempotent)
    try:
        execute("ALTER TABLE company_enrichment ADD COLUMN IF NOT EXISTS publication_summary TEXT")
    except Exception:
        pass

    if not refresh:
        cached = fetch_one(
            "SELECT publication_summary FROM company_enrichment WHERE enterprise_number = %s AND publication_summary IS NOT NULL",
            (cbe,),
        )
        if cached and cached.get("publication_summary"):
            raw = cached["publication_summary"]
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict) and "events" in parsed:
                    return {"summary": parsed, "cached": True}
            except Exception:
                pass

    # Structured path: pull the last 10 events for this CBE.  10 is a
    # bit larger than the 5-publication window because one filing can
    # produce multiple events (e.g. capital_event + admin_event).
    structured_events = fetch_all(
        """SELECT id, pub_reference, pub_date, event_type, sub_type,
                  event_date, person_name, person_role, entity_name,
                  amount_eur, amount_shares, summary
           FROM staatsblad_event
           WHERE enterprise_number = %s
           ORDER BY pub_date DESC, id DESC
           LIMIT 10""",
        (cbe,),
    )

    if len(structured_events) >= 3:
        parsed = _synthesise_structured_summary(structured_events)
        cache_str = json.dumps(parsed, ensure_ascii=False)
        try:
            execute(
                "INSERT INTO company_enrichment (enterprise_number, publication_summary) VALUES (%s, %s) "
                "ON CONFLICT (enterprise_number) DO UPDATE SET publication_summary = EXCLUDED.publication_summary",
                (cbe, cache_str),
            )
        except Exception as e:
            logger.error("Failed to cache publication summary for %s: %s", cbe, e)
        return {"summary": parsed, "cached": False, "source": "staatsblad_event"}

    # Fallback: legacy label-based LLM summary for CBEs with no Stage-3 coverage.
    pubs = fetch_all(
        "SELECT pub_date, pub_type, reference FROM staatsblad_publication WHERE enterprise_number = %s ORDER BY pub_date DESC LIMIT 5",
        (cbe,),
    )
    if not pubs:
        return {"summary": None, "cached": False}

    company = fetch_one("SELECT name FROM company_info WHERE enterprise_number = %s", (cbe,))
    company_name = company["name"] if company else cbe

    pub_lines = [f"- {p.get('pub_date', '?')}: {p.get('pub_type', 'Unknown')}" for p in pubs]

    system_prompt = (
        "You are a corporate events analyst. Describe Belgian Staatsblad publications "
        "for a non-specialist audience doing initial company screening.\n\n"
        "IMPORTANT: You only see publication TYPE and DATE — not the actual content. "
        "Be factual and cautious. Describe what the publication type typically means, "
        "not what specifically happened. Use phrases like 'likely involves', 'typically indicates', "
        "'may relate to'. Never state conclusions as fact.\n\n"
        "Return valid JSON only — no markdown, no code fences, no explanation. Structure:\n"
        '{"events": [{"date": "YYYY-MM-DD", "type_raw": "original type code", '
        '"what": "1-sentence plain-language description of what this publication type typically covers", '
        '"context": "1-sentence general context for someone unfamiliar with Belgian corporate law", '
        '"importance": "routine | notable | significant"}], '
        '"pattern_note": "1-sentence observation about the pattern of publications, or null if nothing notable", '
        '"risk_flag": false}\n\n'
        "Importance: routine = standard administrative filings. notable = board changes, capital events, "
        "relocations. significant = multiple board changes in short period, merger/demerger, dissolution.\n\n"
        "Translate all Dutch/French legal terms to plain English. "
        "Keep language neutral and informative — never alarmist. Return ONLY the JSON object.\n\n"
        f"Company: {company_name}"
    )

    prompt = "Publications (most recent first):\n" + "\n".join(pub_lines)

    try:
        raw = await ai_complete(prompt, system=system_prompt, max_tokens=512, model="openai/gpt-4o-mini", lang=lang)
    except Exception as e:
        logger.error("Publication summary failed for %s: %s", cbe, e)
        return {"summary": None, "error": "Summary generation failed"}

    parsed = None
    try:
        parsed = json.loads(raw)
    except Exception:
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            parsed = json.loads(cleaned)
        except Exception:
            parsed = {"raw_text": raw, "parse_error": True}

    cache_str = json.dumps(parsed, ensure_ascii=False)
    try:
        execute(
            "INSERT INTO company_enrichment (enterprise_number, publication_summary) VALUES (%s, %s) "
            "ON CONFLICT (enterprise_number) DO UPDATE SET publication_summary = EXCLUDED.publication_summary",
            (cbe, cache_str),
        )
    except Exception as e:
        logger.error("Failed to cache publication summary for %s: %s", cbe, e)

    return {"summary": parsed, "cached": False, "source": "fallback_label"}


# ---------------------------------------------------------------------------
# AI Enrichment — company profile summaries via OpenRouter
# ---------------------------------------------------------------------------

_enrichment_table_ensured = False


async def generate_light_summary(cbe: str) -> Optional[str]:
    """Generate and cache a short NACE + financials-only company summary.

    Intended for internal reuse from other routers (e.g. valuation's sector
    classifier). Idempotent: returns the cached summary if one already exists,
    otherwise generates one, stores it in company_enrichment, and returns it.
    Returns None if generation failed or the company isn't in company_info yet.
    """
    _ensure_enrichment_table()
    cbe = clean_cbe(cbe)

    existing = fetch_one(
        "SELECT summary FROM company_enrichment WHERE enterprise_number = %s",
        (cbe,),
    )
    if existing and existing.get("summary"):
        return existing["summary"]

    company = fetch_one("""
        SELECT ci.name, ci.city, ci.nace_code,
               COALESCE(nl.description, ci.nace_code) AS sector,
               fl.revenue, fl.ebitda, fl.fte_total, fl.fiscal_year
        FROM company_info ci
        LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
        LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
        WHERE ci.enterprise_number = %s
    """, (cbe,))
    if not company:
        return None

    parts: list[str] = []
    if company.get("name"): parts.append(f"Company: {company['name']}")
    if company.get("sector"): parts.append(f"Sector: {company['sector']}")
    if company.get("city"): parts.append(f"Location: {company['city']}, Belgium")
    if company.get("revenue"): parts.append(f"Revenue: EUR {company['revenue']:,.0f}")
    if company.get("ebitda"): parts.append(f"EBITDA: EUR {company['ebitda']:,.0f}")
    if company.get("fte_total"): parts.append(f"FTE: {company['fte_total']:,.0f}")
    if company.get("fiscal_year"): parts.append(f"Fiscal year: {company['fiscal_year']}")
    if not parts:
        return None

    prompt = (
        "Based on the following data about a Belgian company, write a concise "
        "2-3 sentence company profile summary suitable for an investor audience. "
        "Be factual, do not speculate.\n\n" + "\n".join(parts)
    )
    system = (
        "You are a financial analyst assistant. Write concise, professional "
        "company summaries for private equity deal sourcing."
    )

    summary = await ai_complete(prompt, system=system)
    if not summary:
        return None

    try:
        execute("""
            INSERT INTO company_enrichment (enterprise_number, summary, generated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (enterprise_number)
            DO UPDATE SET summary = EXCLUDED.summary, generated_at = NOW()
        """, (cbe, summary))
    except Exception:
        logger.exception("Failed to store light summary for %s", cbe)

    return summary


def _ensure_enrichment_table():
    """Create enrichment table if it does not exist (idempotent)."""
    global _enrichment_table_ensured
    if _enrichment_table_ensured:
        return
    execute("""
        CREATE TABLE IF NOT EXISTS company_enrichment (
            enterprise_number VARCHAR(10) PRIMARY KEY,
            summary TEXT,
            generated_at TIMESTAMP DEFAULT NOW()
        )
    """)
    # Add website/LinkedIn scraping columns + ai_insights (idempotent)
    for col in ("website_summary", "linkedin_summary", "website_url", "ai_insights"):
        try:
            execute(f"""
                ALTER TABLE company_enrichment ADD COLUMN IF NOT EXISTS {col} TEXT
            """)
        except Exception:
            pass  # column already exists or DB doesn't support IF NOT EXISTS

    # Phase 1: bulk-summary columns used by the enrichment worker +
    # /api/search/semantic. Decoupled from the narrative `ai_insights`
    # column above — see `docs/architecture.md` for the split.
    for col, typ in (
        ("bulk_summary",        "JSONB"),
        ("bulk_summary_at",     "TIMESTAMPTZ"),
        ("bulk_website_hash",   "TEXT"),
        ("bulk_website_url",    "TEXT"),
        ("bulk_confidence",     "TEXT"),
    ):
        try:
            execute(
                f"ALTER TABLE company_enrichment "
                f"ADD COLUMN IF NOT EXISTS {col} {typ}"
            )
        except Exception:
            pass
    # AI insights feedback table
    execute("""
        CREATE TABLE IF NOT EXISTS ai_insights_feedback (
            id SERIAL PRIMARY KEY,
            enterprise_number VARCHAR(10) NOT NULL,
            user_email TEXT,
            overall TEXT NOT NULL,
            website_correct BOOLEAN,
            linkedin_correct BOOLEAN,
            insight_correct BOOLEAN,
            comment TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    _enrichment_table_ensured = True


@router.post("/{cbe}/enrich")
async def enrich_company(
    cbe: str,
    lang: str | None = None,
    user=Depends(optional_user),
):
    """Generate an AI company profile summary via OpenRouter.

    Gathers existing company data (name, sector, city, financials) and asks
    the LLM to write a concise 2-3 sentence company profile in ``lang``
    (``nl``/``fr``/``en``) — defaults to English.

    Open to anonymous callers — operator policy is that AI features have
    no sign-in wall. Cost protection comes from TierLimitMiddleware
    classifying this endpoint into the ``ai_enrichments_per_day`` bucket
    (anon tier capped per day) plus the global per-IP rate limiter.
    """
    _ensure_enrichment_table()

    cbe = clean_cbe(cbe)

    # Gather company data for the prompt
    company = fetch_one("""
        SELECT ci.name, ci.city, ci.nace_code,
               COALESCE(nl.description, ci.nace_code) AS sector,
               fl.revenue, fl.ebitda, fl.fte_total, fl.fiscal_year
        FROM company_info ci
        LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
        LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
        WHERE ci.enterprise_number = %s
    """, (cbe,))

    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    # Build the prompt from available data
    parts = []
    if company.get("name"):
        parts.append(f"Company: {company['name']}")
    if company.get("sector"):
        parts.append(f"Sector: {company['sector']}")
    if company.get("city"):
        parts.append(f"Location: {company['city']}, Belgium")
    if company.get("revenue"):
        parts.append(f"Revenue: EUR {company['revenue']:,.0f}")
    if company.get("ebitda"):
        parts.append(f"EBITDA: EUR {company['ebitda']:,.0f}")
    if company.get("fte_total"):
        parts.append(f"FTE: {company['fte_total']:,.0f}")
    if company.get("fiscal_year"):
        parts.append(f"Fiscal year: {company['fiscal_year']}")

    if not parts:
        raise HTTPException(
            status_code=422, detail="Not enough data to generate a profile"
        )

    prompt = (
        "Based on the following data about a Belgian company, write a concise "
        "2-3 sentence company profile summary suitable for an investor audience. "
        "Be factual, do not speculate.\n\n"
        + "\n".join(parts)
    )

    system = (
        "You are a financial analyst assistant. Write concise, professional "
        "company summaries for private equity deal sourcing."
    )

    summary = await ai_complete(prompt, system=system, lang=lang)

    if not summary:
        raise HTTPException(
            status_code=503,
            detail="AI service unavailable — check OPENROUTER_API_KEY",
        )

    # Store (upsert) the enrichment
    execute("""
        INSERT INTO company_enrichment (enterprise_number, summary, generated_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT (enterprise_number)
        DO UPDATE SET summary = EXCLUDED.summary, generated_at = NOW()
    """, (cbe, summary))

    return {"summary": summary}


@router.get("/{cbe}/enrichment")
async def get_enrichment(cbe: str, lang: str | None = None, user=Depends(optional_user)):
    """Fetch existing AI-generated enrichment for a company.

    ``lang`` (``nl``/``fr``/``en``) translates the cached ``summary`` and
    ``ai_insights`` blobs on the fly via a cheap LLM call so the user sees
    the page in their site language without forcing a full regeneration.
    Translations are memoised per ``(cbe, kind, lang)`` for the day.

    Per operator policy, translation runs for everyone (anonymous + auth).
    Cost is bounded by the in-process 24h cache (10k entries cap) and the
    global per-IP 200 req/min rate-limit; once a CBE+lang is translated,
    subsequent reads for that combo are free.
    """
    from ai_client import translate_cached_json, translate_cached

    _ensure_enrichment_table()

    cbe = clean_cbe(cbe)

    row = fetch_one("""
        SELECT summary, generated_at, website_summary, linkedin_summary, website_url, ai_insights
        FROM company_enrichment
        WHERE enterprise_number = %s
    """, (cbe,))

    if not row:
        return None

    serialized = _serialize_row(row)

    # Translate user-visible fields when the site language is set. Other
    # fields (website_url, structured website/linkedin metadata) stay as
    # source — they're URLs and tags, not narrative text.
    if lang:
        if serialized.get("summary"):
            serialized["summary"] = await translate_cached(cbe, "summary", serialized["summary"], lang)
        if serialized.get("ai_insights"):
            # ai_insights is a JSON blob; translate per-string-field rather
            # than passing the whole blob to the LLM (which would translate
            # the keys too and break the frontend's `insights.business_description`
            # destructuring).
            serialized["ai_insights"] = await translate_cached_json(
                cbe, "ai_insights", serialized["ai_insights"], lang,
                value_fields=("business_description", "customers", "market_position",
                              "history", "group_context"),
                list_fields=("products",),
            )

    return serialized


# ---------------------------------------------------------------------------
# POST /api/companies/{cbe}/scrape-website
# ---------------------------------------------------------------------------

@router.post("/{cbe}/scrape-website")
async def scrape_company_website(cbe: str, user=Depends(optional_user)):
    """Scrape company website via Zenrows and extract structured data with AI.

    Looks up the company website from the contact table (contact_type='WEB'),
    scrapes it, then uses AI to extract a description, products/services,
    employee mentions, and key people.

    Anonymous-friendly per operator policy. Tier-bucketed under
    ``ai_enrichments_per_day``.
    """
    from scraper import scrape_url, _strip_html

    _ensure_enrichment_table()
    cbe = clean_cbe(cbe)

    # 1. Find the company's website
    row = fetch_one("""
        SELECT value FROM contact
        WHERE entity_number = %s AND contact_type = 'WEB'
        LIMIT 1
    """, (cbe,))

    if not row or not row.get("value"):
        raise HTTPException(status_code=404, detail="No website found for this company")

    website_url = row["value"].strip()
    # Ensure URL has a scheme
    if not website_url.startswith("http"):
        website_url = "https://" + website_url

    # 2. Scrape the website
    html = await scrape_url(website_url)
    if not html:
        raise HTTPException(
            status_code=502,
            detail="Could not retrieve website data — proxy scraping is temporarily unavailable, please try again later",
        )

    # 3. Extract text from HTML
    page_text = _strip_html(html)
    if len(page_text) < 50:
        raise HTTPException(status_code=422, detail="Website returned too little content to analyse")

    # 4. AI extraction
    prompt = (
        "Analyse the following text scraped from a Belgian company's website. "
        "Extract and return a JSON object with these fields:\n"
        '- "summary": A concise 2-3 sentence company description\n'
        '- "products": A comma-separated list of main products or services\n'
        '- "employees": Any mentioned number of employees, or "unknown"\n'
        '- "key_people": Names and roles of key people mentioned, or "none found"\n\n'
        "Return ONLY valid JSON, no markdown fences.\n\n"
        f"Website text:\n{page_text}"
    )

    system = (
        "You are a data extraction assistant. Return only valid JSON. "
        "Be concise and factual. If information is not available, use sensible defaults."
    )

    ai_response = await ai_complete(prompt, system=system)
    if not ai_response:
        raise HTTPException(status_code=503, detail="AI service unavailable")

    # 5. Try to parse AI response as JSON, fall back to raw text
    import json
    try:
        extracted = json.loads(ai_response.strip())
    except json.JSONDecodeError:
        # AI didn't return clean JSON — wrap the raw text
        extracted = {
            "summary": ai_response.strip(),
            "products": "unknown",
            "employees": "unknown",
            "key_people": "none found",
        }

    # 6. Store in company_enrichment
    website_summary = json.dumps(extracted, ensure_ascii=False)
    execute("""
        INSERT INTO company_enrichment (enterprise_number, website_summary, website_url, generated_at)
        VALUES (%s, %s, %s, NOW())
        ON CONFLICT (enterprise_number)
        DO UPDATE SET website_summary = EXCLUDED.website_summary,
                      website_url = EXCLUDED.website_url,
                      generated_at = NOW()
    """, (cbe, website_summary, website_url))

    return {
        "summary": extracted.get("summary", ""),
        "products": extracted.get("products", ""),
        "employees": extracted.get("employees", "unknown"),
        "key_people": extracted.get("key_people", "none found"),
        "website_url": website_url,
    }


# ---------------------------------------------------------------------------
# POST /api/companies/{cbe}/scrape-linkedin
# ---------------------------------------------------------------------------

@router.post("/{cbe}/scrape-linkedin")
async def scrape_company_linkedin(cbe: str, user=Depends(optional_user)):
    """Scrape company LinkedIn profile via Zenrows and extract data with AI.

    Constructs a LinkedIn company URL from the company name, scrapes it
    with JS rendering and premium proxies, then uses AI to extract
    description, employee count, industry, and specialties.

    Anonymous-friendly per operator policy. Tier-bucketed under
    ``ai_enrichments_per_day``.
    """
    from scraper import scrape_url, _strip_html, slugify_company_name

    _ensure_enrichment_table()
    cbe = clean_cbe(cbe)

    # 1. Get company name to build LinkedIn URL
    company = fetch_one("""
        SELECT COALESCE(ci.name, d.denomination) AS name
        FROM enterprise e
        LEFT JOIN company_info ci ON ci.enterprise_number = e.enterprise_number
        LEFT JOIN denomination d ON d.entity_number = e.enterprise_number
             AND d.type_of_denomination = '001' AND d.language IN ('2','1')
        WHERE e.enterprise_number = %s
        LIMIT 1
    """, (cbe,))

    if not company or not company.get("name"):
        raise HTTPException(status_code=404, detail="Company not found")

    company_name = company["name"]
    slug = slugify_company_name(company_name)
    linkedin_url = f"https://www.linkedin.com/company/{slug}"

    # 2. Scrape LinkedIn (requires JS rendering + premium proxy)
    html = await scrape_url(linkedin_url, js_render=True, premium_proxy=True)
    if not html:
        raise HTTPException(
            status_code=502,
            detail="Could not retrieve LinkedIn data — proxy scraping is temporarily unavailable, please try again later",
        )

    # 3. Extract text from HTML
    page_text = _strip_html(html)
    if len(page_text) < 50:
        raise HTTPException(
            status_code=422,
            detail="LinkedIn page returned too little content — the company page may not exist",
        )

    # 4. AI extraction
    prompt = (
        "Analyse the following text scraped from a LinkedIn company page. "
        "Extract and return a JSON object with these fields:\n"
        '- "summary": A concise 2-3 sentence company description\n'
        '- "employee_count": Number of employees listed, or "unknown"\n'
        '- "industry": The industry listed on the page, or "unknown"\n'
        '- "specialties": A comma-separated list of specialties, or "none found"\n\n'
        "Return ONLY valid JSON, no markdown fences.\n\n"
        f"LinkedIn page text:\n{page_text}"
    )

    system = (
        "You are a data extraction assistant. Return only valid JSON. "
        "Be concise and factual. If information is not available, use sensible defaults."
    )

    ai_response = await ai_complete(prompt, system=system)
    if not ai_response:
        raise HTTPException(status_code=503, detail="AI service unavailable")

    # 5. Try to parse AI response as JSON
    import json
    try:
        extracted = json.loads(ai_response.strip())
    except json.JSONDecodeError:
        extracted = {
            "summary": ai_response.strip(),
            "employee_count": "unknown",
            "industry": "unknown",
            "specialties": "none found",
        }

    # 6. Store in company_enrichment
    linkedin_summary = json.dumps(extracted, ensure_ascii=False)
    execute("""
        INSERT INTO company_enrichment (enterprise_number, linkedin_summary, generated_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT (enterprise_number)
        DO UPDATE SET linkedin_summary = EXCLUDED.linkedin_summary,
                      generated_at = NOW()
    """, (cbe, linkedin_summary))

    return {
        "summary": extracted.get("summary", ""),
        "employee_count": extracted.get("employee_count", "unknown"),
        "industry": extracted.get("industry", "unknown"),
        "specialties": extracted.get("specialties", "none found"),
        "linkedin_url": linkedin_url,
    }


# ---------------------------------------------------------------------------
# POST /api/companies/{cbe}/ai-insights
# ---------------------------------------------------------------------------

@router.post("/{cbe}/ai-insights")
async def generate_ai_insights(
    cbe: str,
    lang: str | None = None,
    force: bool = False,
    user=Depends(optional_user),
):
    """Generate structured AI company insights via a multi-step LLM pipeline.

    Step 1 (cheap): Discover website + LinkedIn URLs
    Step 2 (Grok):  Scrape & generate structured insights
    Step 3 (cheap): Review & validate output
    Step 4:         Store validated result in database

    ``lang`` (``nl``/``fr``/``en``) controls the language of the generated
    narrative so it matches the user's site language. Cached prior insights
    are served regardless of language; pass ``force=true`` for explicit
    regeneration (e.g. an admin "refresh" button).

    ``force=false`` short-circuits when ``company_enrichment.ai_insights``
    already holds a non-null payload — avoids burning 4-6 LLM calls + 2
    scraper hits on every profile re-open. Cache is invalidated either
    by feedback (3+ down votes nulls the row, see /ai-insights/feedback)
    or by the next bulk-pipeline write.
    """
    _ensure_enrichment_table()
    cbe = clean_cbe(cbe)

    # `force=true` is for explicit admin/operator regeneration only.
    # Anonymous callers must not be able to bypass the cache — that
    # would let a bot burn 4-6 LLM calls per request just by passing
    # `?force=true`, which the per-endpoint tier counter (1 hit) would
    # not catch. Auth required → tier limits still bound damage.
    effective_force = bool(force) and user is not None

    # ── Cache short-circuit ─────────────────────────────────────────
    # When the row already has a non-null `ai_insights` payload, return
    # it directly. The frontend's enrichment endpoint already loads this
    # JSON via /api/companies/{cbe}/enrichment, but profile clients still
    # call this POST endpoint in parallel as a regeneration trigger —
    # without this guard, every profile open burns LLM credits.
    if not effective_force:
        try:
            cached_row = fetch_one(
                "SELECT ai_insights FROM company_enrichment WHERE enterprise_number = %s",
                (cbe,),
            )
            if cached_row and cached_row.get("ai_insights"):
                raw = cached_row["ai_insights"]
                cached: Optional[dict] = None
                if isinstance(raw, dict):
                    cached = raw
                elif isinstance(raw, str):
                    try:
                        cached = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        cached = None
                if cached and not cached.get("error"):
                    if lang:
                        try:
                            from ai_client import translate_cached_json
                            translated = await translate_cached_json(
                                cbe,
                                "ai_insights",
                                json.dumps(cached, ensure_ascii=False),
                                lang,
                                value_fields=(
                                    "business_description",
                                    "customers",
                                    "market_position",
                                    "history",
                                    "group_context",
                                ),
                                list_fields=("products",),
                            )
                            cached = json.loads(translated)
                        except Exception:
                            logger.debug(
                                "ai_insights cached translation failed for %s",
                                cbe,
                                exc_info=True,
                            )
                    cached["from_cache"] = True
                    return cached
        except Exception:
            # Cache lookup failure must never block regeneration. Fall
            # through to the pipeline path on any DB / parse error.
            logger.debug("ai_insights cache lookup failed for %s", cbe, exc_info=True)

    conn_helpers = {
        "fetch_one": fetch_one,
        "fetch_all": fetch_all,
        "execute": execute,
    }

    # ── Phase 5 fast path ───────────────────────────────────────────
    # If we already have a bulk_summary for this CBE, serve it immediately
    # (instant) and kick off the qwen+kimi elaboration in the background.
    # The next time the user opens this profile, the narrative_lite
    # version will be served from the ai_insights cache. This decouples
    # perceived latency from the 30-60s cost of the full elaboration.
    if PHASE_5_ELABORATION_ENABLED and not effective_force:
        try:
            bulk_row = fetch_one(
                """
                SELECT bulk_summary, quality_tier
                  FROM company_enrichment
                 WHERE enterprise_number = %s
                """,
                (cbe,),
            )
        except Exception:
            bulk_row = None
        if bulk_row and bulk_row.get("bulk_summary") and bulk_row.get("quality_tier") in (
            "bulk_only", "bulk_escalated"
        ):
            bulk = bulk_row["bulk_summary"]
            if isinstance(bulk, str):
                try:
                    bulk = json.loads(bulk)
                except (json.JSONDecodeError, TypeError):
                    bulk = None
            if isinstance(bulk, dict) and bulk.get("business_description"):
                # Schedule the elaboration on a fire-and-forget task. It will
                # write narrative_lite + ai_insights when done; the next call
                # to this endpoint will hit the ai_insights cache short-circuit
                # above and return the upgraded version.
                async def _background_elaborate():
                    try:
                        await call_elaboration_narrative(cbe, conn_helpers, lang=lang)
                    except Exception:
                        logger.exception(
                            "ai_insights background elaboration failed for %s", cbe
                        )

                asyncio.create_task(_background_elaborate())
                bulk["from_cache"] = True
                bulk["upgrade_in_progress"] = True
                bulk["quality_tier"] = bulk_row["quality_tier"]
                return bulk

    t_total = time.perf_counter()
    try:
        t0 = time.perf_counter()
        if PHASE_5_ELABORATION_ENABLED:
            insights = await call_elaboration_narrative(cbe, conn_helpers, lang=lang)
            pipeline_label = "phase5_elaboration"
        else:
            insights = await ai_insights_pipeline(cbe, conn_helpers, lang=lang)
            pipeline_label = "legacy_4step"
        logger.info(
            "ai_insights.pipeline cbe=%s pipeline=%s ms=%.0f",
            cbe, pipeline_label, (time.perf_counter() - t0) * 1000,
        )
    except Exception as e:
        logger.exception("AI insights pipeline failed for %s ms=%.0f", cbe, (time.perf_counter()-t_total)*1000)
        raise HTTPException(
            status_code=503,
            detail=f"AI insights generation failed: {str(e)}",
        )

    if insights.get("error"):
        raise HTTPException(status_code=404, detail=insights["error"])

    # Auto-generate embedding in background (non-blocking)
    try:
        t0 = time.perf_counter()
        from embeddings import embed_company
        await embed_company(cbe, force=True)
        logger.info("ai_insights.embed cbe=%s ms=%.0f", cbe, (time.perf_counter()-t0)*1000)
    except Exception as e:
        logger.warning("Auto-embedding failed for %s (non-fatal): %s", cbe, e)

    logger.info("ai_insights.total cbe=%s ms=%.0f", cbe, (time.perf_counter()-t_total)*1000)
    return insights


# ---------------------------------------------------------------------------
# POST /api/companies/{cbe}/ai-insights/feedback
# ---------------------------------------------------------------------------

class InsightsFeedbackBody(BaseModel):
    overall: str  # "up" or "down"
    websiteCorrect: Optional[bool] = None
    linkedinCorrect: Optional[bool] = None
    insightCorrect: Optional[bool] = None
    comment: Optional[str] = None


@router.post("/{cbe}/ai-insights/feedback")
async def submit_insights_feedback(cbe: str, body: InsightsFeedbackBody, user=Depends(optional_user)):
    """Submit user feedback on AI-generated insights."""
    _ensure_enrichment_table()
    cbe = clean_cbe(cbe)

    if body.overall not in ("up", "down"):
        raise HTTPException(status_code=400, detail="overall must be 'up' or 'down'")

    email = user.get("email") if user else None

    try:
        execute(
            """INSERT INTO ai_insights_feedback
               (enterprise_number, user_email, overall, website_correct, linkedin_correct, insight_correct, comment)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (cbe, email, body.overall, body.websiteCorrect, body.linkedinCorrect, body.insightCorrect, body.comment),
        )

        # If 3+ users flagged "down", clear cached insights to force regeneration
        if body.overall == "down":
            row = fetch_one(
                """SELECT COUNT(DISTINCT COALESCE(user_email, 'anon')) AS cnt
                   FROM ai_insights_feedback
                   WHERE enterprise_number = %s AND overall = 'down'""",
                (cbe,),
            )
            if row and row["cnt"] >= 3:
                execute(
                    "UPDATE company_enrichment SET ai_insights = NULL WHERE enterprise_number = %s",
                    (cbe,),
                )
                logger.info("Cleared cached ai_insights for %s after %s down votes", cbe, row["cnt"])

        return {"status": "ok"}
    except Exception as e:
        logger.error("Failed to submit insights feedback for %s: %s", cbe, e)
        raise HTTPException(status_code=500, detail="Failed to submit feedback")
