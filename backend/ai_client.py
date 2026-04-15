"""OpenRouter AI client — uses cheapest model per use case."""

import json
import os
import logging
import re

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE = "https://openrouter.ai/api/v1/chat/completions"

# Model aliases
CHEAP_MODEL = "google/gemma-3-4b-it"
INSIGHT_MODEL = "x-ai/grok-3-mini"
INSIGHT_MODEL_FALLBACK = "x-ai/grok-2"


async def ai_complete(
    prompt: str,
    system: str = "",
    model: str = "google/gemma-3-4b-it",
    max_tokens: int = 500,
) -> str:
    """Call OpenRouter with the cheapest available model.

    Returns the model's text response, or empty string on failure / no API key.
    """
    if not OPENROUTER_API_KEY:
        return ""

    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                OPENROUTER_BASE,
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "HTTP-Referer": "https://datasnoop.be",
                    "X-Title": "Datasnoop",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                },
                timeout=60,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            logger.warning(
                "OpenRouter returned %s: %s", resp.status_code, resp.text[:200]
            )
    except Exception as e:
        logger.exception("OpenRouter request failed: %s", e)

    return ""


def _extract_json(text: str) -> dict | None:
    """Try to extract a JSON object from LLM text that may contain markdown fences."""
    # Strip markdown code fences
    cleaned = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`")
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # Try to find first { ... } block
    m = re.search(r"\{[\s\S]*\}", cleaned)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return None


async def ai_insights_pipeline(cbe: str, conn_helpers: dict) -> dict:
    """Multi-step AI pipeline to generate structured company insights.

    Parameters
    ----------
    cbe : str
        The 10-digit enterprise number.
    conn_helpers : dict
        Must contain ``fetch_one`` and ``execute`` callables.

    Returns a dict with structured insight fields, suitable for JSON storage.
    """
    from scraper import scrape_url, _strip_html, slugify_company_name

    fetch_one = conn_helpers["fetch_one"]
    execute = conn_helpers["execute"]

    # ── Gather company context from DB ──────────────────────────
    company = fetch_one("""
        SELECT ci.name, ci.city, ci.nace_code,
               COALESCE(nl.description, ci.nace_code) AS sector,
               fl.revenue, fl.ebitda, fl.fte_total, fl.fiscal_year
        FROM company_info ci
        LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
        LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
        WHERE ci.enterprise_number = %s
    """, (cbe,))

    if not company or not company.get("name"):
        return {"error": "Company not found"}

    name = company["name"]
    city = company.get("city", "Belgium")
    sector = company.get("sector", "")
    revenue = company.get("revenue")
    ebitda = company.get("ebitda")
    fte = company.get("fte_total")
    fiscal_year = company.get("fiscal_year")

    # Check for existing website in contact table
    contact_row = fetch_one("""
        SELECT value FROM contact
        WHERE entity_number = %s AND contact_type = 'WEB'
        LIMIT 1
    """, (cbe,))
    known_website = (contact_row.get("value", "").strip() if contact_row else "") or ""

    # ── STEP 1: URL Discovery (cheap model) ─────────────────────
    website_url = known_website
    linkedin_url = ""

    if not website_url:
        url_prompt = (
            f"Given a Belgian company:\n"
            f"- Name: {name}\n"
            f"- City: {city}\n"
            f"- Sector: {sector}\n\n"
            "What is the most likely company website URL? "
            "Also guess the LinkedIn company page URL.\n"
            'Return ONLY JSON: {{"website_url": "...", "linkedin_url": "..."}}\n'
            "If you cannot determine a URL, use an empty string."
        )
        url_resp = await ai_complete(
            url_prompt,
            system="You are a data lookup assistant. Return only valid JSON.",
            model=CHEAP_MODEL,
            max_tokens=200,
        )
        if url_resp:
            parsed = _extract_json(url_resp)
            if parsed:
                website_url = parsed.get("website_url", "") or ""
                linkedin_url = parsed.get("linkedin_url", "") or ""

    if not linkedin_url:
        # Build LinkedIn URL from company name slug
        slug = slugify_company_name(name)
        if slug:
            linkedin_url = f"https://www.linkedin.com/company/{slug}"

    # Ensure scheme on website URL
    if website_url and not website_url.startswith("http"):
        website_url = "https://" + website_url

    # ── STEP 2: Scrape & Generate Insights (Grok via OpenRouter) ─
    website_text = ""
    linkedin_text = ""

    if website_url:
        try:
            html = await scrape_url(website_url)
            if html:
                website_text = _strip_html(html, max_chars=8000)
        except Exception as e:
            logger.warning("Website scrape failed for %s: %s", website_url, e)

    if linkedin_url:
        try:
            html = await scrape_url(linkedin_url, js_render=True, premium_proxy=True)
            if html:
                linkedin_text = _strip_html(html, max_chars=8000)
        except Exception as e:
            logger.warning("LinkedIn scrape failed for %s: %s", linkedin_url, e)

    # Build financial summary for context
    fin_parts = []
    if revenue:
        fin_parts.append(f"Revenue: EUR {revenue:,.0f}")
    if ebitda:
        fin_parts.append(f"EBITDA: EUR {ebitda:,.0f}")
    if revenue and ebitda and revenue > 0:
        margin = round(ebitda / revenue * 100, 1)
        fin_parts.append(f"EBITDA margin: {margin}%")
    if fte:
        fin_parts.append(f"Employees (FTE): {fte:,.0f}")
    if fiscal_year:
        fin_parts.append(f"Fiscal year: {fiscal_year}")
    financial_summary = "; ".join(fin_parts) if fin_parts else "No financial data available."

    insight_prompt = (
        f"Company: {name}\n"
        f"Location: {city}, Belgium\n"
        f"Sector (NACE): {sector}\n"
        f"Financials: {financial_summary}\n"
    )
    if website_text:
        insight_prompt += f"\n--- Company website text ---\n{website_text}\n"
    if linkedin_text:
        insight_prompt += f"\n--- LinkedIn page text ---\n{linkedin_text}\n"

    insight_prompt += (
        "\nBased on the above, create a company intelligence brief. "
        "DO NOT just repeat the financial data or NACE description. "
        "Provide genuine business insights based on the website and LinkedIn content.\n\n"
        "Return a JSON object with exactly these fields:\n"
        '- "business_description": What the company does in 2-3 sentences\n'
        '- "products_services": Their main products/services\n'
        '- "target_customers": Who their customers are\n'
        '- "competitive_position": Market position and key differentiators\n'
        '- "company_history": Brief history/milestones\n'
        '- "website_url": The company website URL (or empty string if unknown)\n'
        '- "linkedin_url": The LinkedIn company page URL (or empty string if unknown)\n\n'
        "Return ONLY valid JSON, no markdown fences."
    )

    insight_system = (
        "You are a private equity analyst creating a company intelligence brief. "
        "DO NOT just repeat the financial data or NACE description - provide genuine "
        "business insights. If website or LinkedIn text is available, use it to give "
        "specific details about products, customers, and positioning."
    )

    # Try primary model, fall back if needed
    insight_resp = await ai_complete(
        insight_prompt,
        system=insight_system,
        model=INSIGHT_MODEL,
        max_tokens=1000,
    )

    if not insight_resp:
        # Fallback model
        insight_resp = await ai_complete(
            insight_prompt,
            system=insight_system,
            model=INSIGHT_MODEL_FALLBACK,
            max_tokens=1000,
        )

    if not insight_resp:
        # Last resort: use cheap model
        insight_resp = await ai_complete(
            insight_prompt,
            system=insight_system,
            model=CHEAP_MODEL,
            max_tokens=1000,
        )

    insights = _extract_json(insight_resp) if insight_resp else None

    if not insights:
        # Build a minimal fallback from whatever we have
        insights = {
            "business_description": insight_resp.strip() if insight_resp else "Unable to generate insights.",
            "products_services": "",
            "target_customers": "",
            "competitive_position": "",
            "company_history": "",
            "website_url": website_url,
            "linkedin_url": linkedin_url,
        }

    # Ensure URL fields are populated from our discovery
    if not insights.get("website_url"):
        insights["website_url"] = website_url
    if not insights.get("linkedin_url"):
        insights["linkedin_url"] = linkedin_url

    # ── STEP 3: Review / Validate (cheap model) ─────────────────
    review_prompt = (
        "Review this company intelligence brief about a Belgian company. "
        "Check for:\n"
        "1. Factual inconsistencies or hallucinated claims\n"
        "2. Content that just restates financial data without adding insight\n"
        "3. Missing or empty fields that could be filled from context\n\n"
        f"Company name: {name}\n"
        f"Sector: {sector}\n"
        f"Location: {city}, Belgium\n\n"
        f"Brief to review:\n{json.dumps(insights, indent=2)}\n\n"
        "Return the same JSON with any corrections, or return it unchanged if it looks good. "
        "Return ONLY valid JSON, no markdown fences."
    )

    review_resp = await ai_complete(
        review_prompt,
        system="You are a quality reviewer. Fix factual errors and improve weak content. Return only valid JSON.",
        model=CHEAP_MODEL,
        max_tokens=1000,
    )

    if review_resp:
        reviewed = _extract_json(review_resp)
        if reviewed:
            # Preserve URL fields from our discovery (reviewer might drop them)
            if not reviewed.get("website_url"):
                reviewed["website_url"] = website_url
            if not reviewed.get("linkedin_url"):
                reviewed["linkedin_url"] = linkedin_url
            insights = reviewed

    # ── STEP 4: Store in database ───────────────────────────────
    insights_json = json.dumps(insights, ensure_ascii=False)
    try:
        execute("""
            INSERT INTO company_enrichment (enterprise_number, ai_insights, generated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (enterprise_number)
            DO UPDATE SET ai_insights = EXCLUDED.ai_insights, generated_at = NOW()
        """, (cbe, insights_json))
    except Exception as e:
        logger.warning("Failed to store AI insights for %s: %s", cbe, e)

    return insights
