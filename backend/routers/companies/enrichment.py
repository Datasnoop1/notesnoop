"""Companies enrichment router — AI summaries, scraping, insights, feedback."""

import json
import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from db import fetch_all, fetch_one, execute
from auth import get_current_user, optional_user
from ai_client import ai_complete, ai_insights_pipeline
from utils import clean_cbe
from ._helpers import _serialize_row

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# POST /api/companies/{cbe}/summarize-publications
# ---------------------------------------------------------------------------

class SummarizePublicationsBody(BaseModel):
    refresh: bool = False


@router.post("/{cbe}/summarize-publications")
async def summarize_publications(cbe: str, body: Optional[SummarizePublicationsBody] = None, user=Depends(get_current_user)):
    """Generate structured AI analysis of last 5 Staatsblad publications."""
    cbe = clean_cbe(cbe)
    refresh = body.refresh if body else False

    # Ensure column exists (idempotent)
    try:
        execute("ALTER TABLE company_enrichment ADD COLUMN IF NOT EXISTS publication_summary TEXT")
    except Exception:
        pass

    # Check cache — return parsed JSON if valid (skip on refresh)
    if not refresh:
        cached = fetch_one(
            "SELECT publication_summary FROM company_enrichment WHERE enterprise_number = %s AND publication_summary IS NOT NULL",
            (cbe,),
        )
        if cached and cached.get("publication_summary"):
            raw = cached["publication_summary"]
            try:
                parsed = json.loads(raw)
                # Only return cache if it's the new structured format
                if isinstance(parsed, dict) and "events" in parsed:
                    return {"summary": parsed, "cached": True}
            except Exception:
                pass
            # Old format or invalid — fall through to regenerate

    # Fetch last 5 publications
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
        raw = await ai_complete(prompt, system=system_prompt, max_tokens=512, model="openai/gpt-4o-mini")
    except Exception as e:
        logger.error("Publication summary failed for %s: %s", cbe, e)
        return {"summary": None, "error": "Summary generation failed"}

    # Parse JSON with fallback
    parsed = None
    try:
        parsed = json.loads(raw)
    except Exception:
        # Strip markdown code fences and retry
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            parsed = json.loads(cleaned)
        except Exception:
            parsed = {"raw_text": raw, "parse_error": True}

    # Cache the JSON string
    cache_str = json.dumps(parsed, ensure_ascii=False)
    try:
        execute(
            "INSERT INTO company_enrichment (enterprise_number, publication_summary) VALUES (%s, %s) "
            "ON CONFLICT (enterprise_number) DO UPDATE SET publication_summary = EXCLUDED.publication_summary",
            (cbe, cache_str),
        )
    except Exception as e:
        logger.error("Failed to cache publication summary for %s: %s", cbe, e)

    return {"summary": parsed, "cached": False}


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
async def enrich_company(cbe: str, user=Depends(get_current_user)):
    """Generate an AI company profile summary via OpenRouter.

    Gathers existing company data (name, sector, city, financials) and asks
    the LLM to write a concise 2-3 sentence company profile.
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

    summary = await ai_complete(prompt, system=system)

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
async def get_enrichment(cbe: str, user=Depends(optional_user)):
    """Fetch existing AI-generated enrichment for a company."""
    _ensure_enrichment_table()

    cbe = clean_cbe(cbe)

    row = fetch_one("""
        SELECT summary, generated_at, website_summary, linkedin_summary, website_url, ai_insights
        FROM company_enrichment
        WHERE enterprise_number = %s
    """, (cbe,))

    if not row:
        return None

    return _serialize_row(row)


# ---------------------------------------------------------------------------
# POST /api/companies/{cbe}/scrape-website
# ---------------------------------------------------------------------------

@router.post("/{cbe}/scrape-website")
async def scrape_company_website(cbe: str, user=Depends(get_current_user)):
    """Scrape company website via Zenrows and extract structured data with AI.

    Looks up the company website from the contact table (contact_type='WEB'),
    scrapes it, then uses AI to extract a description, products/services,
    employee mentions, and key people.
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
            detail="Could not retrieve website data — check ZENROWS_API_KEY or try again later",
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
async def scrape_company_linkedin(cbe: str, user=Depends(get_current_user)):
    """Scrape company LinkedIn profile via Zenrows and extract data with AI.

    Constructs a LinkedIn company URL from the company name, scrapes it
    with JS rendering and premium proxies, then uses AI to extract
    description, employee count, industry, and specialties.
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
            detail="Could not retrieve LinkedIn data — check ZENROWS_API_KEY or try again later",
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
async def generate_ai_insights(cbe: str, user=Depends(optional_user)):
    """Generate structured AI company insights via a multi-step LLM pipeline.

    Step 1 (cheap): Discover website + LinkedIn URLs
    Step 2 (Grok):  Scrape & generate structured insights
    Step 3 (cheap): Review & validate output
    Step 4:         Store validated result in database
    """
    _ensure_enrichment_table()
    cbe = clean_cbe(cbe)

    conn_helpers = {
        "fetch_one": fetch_one,
        "fetch_all": fetch_all,
        "execute": execute,
    }

    try:
        insights = await ai_insights_pipeline(cbe, conn_helpers)
    except Exception as e:
        logger.exception("AI insights pipeline failed for %s", cbe)
        raise HTTPException(
            status_code=503,
            detail=f"AI insights generation failed: {str(e)}",
        )

    if insights.get("error"):
        raise HTTPException(status_code=404, detail=insights["error"])

    # Auto-generate embedding in background (non-blocking)
    try:
        from embeddings import embed_company
        await embed_company(cbe, force=True)
        logger.info("Auto-embedded company %s after AI insights generation", cbe)
    except Exception as e:
        logger.warning("Auto-embedding failed for %s (non-fatal): %s", cbe, e)

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
