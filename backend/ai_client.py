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
VALIDATION_MODEL = "x-ai/grok-3-mini"  # Better model for URL discovery + validation
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


def _summarize_feedback(fetch_all, cbe: str) -> dict:
    """Query ai_insights_feedback and build a summary for prompt injection.

    Returns a dict with:
        - ``text``: human-readable summary string (empty if no feedback)
        - ``website_flagged``: True if any user marked website as incorrect
        - ``linkedin_flagged``: True if any user marked LinkedIn as incorrect
        - ``old_website_url``: the website URL from the previous insight (if any)
    """
    rows = fetch_all(
        """SELECT overall, website_correct, linkedin_correct, insight_correct, comment
           FROM ai_insights_feedback
           WHERE enterprise_number = %s
           ORDER BY created_at DESC""",
        (cbe,),
    )
    if not rows:
        return {"text": "", "website_flagged": False, "linkedin_flagged": False, "old_website_url": ""}

    total = len(rows)
    down_count = sum(1 for r in rows if r.get("overall") == "down")
    up_count = total - down_count
    website_wrong = sum(1 for r in rows if r.get("website_correct") is False)
    website_right = sum(1 for r in rows if r.get("website_correct") is True)
    linkedin_wrong = sum(1 for r in rows if r.get("linkedin_correct") is False)
    linkedin_right = sum(1 for r in rows if r.get("linkedin_correct") is True)
    insight_wrong = sum(1 for r in rows if r.get("insight_correct") is False)
    insight_right = sum(1 for r in rows if r.get("insight_correct") is True)

    parts = []
    if down_count:
        parts.append(f"Previous AI insight was flagged as incorrect by {down_count} user(s) (and approved by {up_count}).")
    if website_wrong:
        parts.append(f"Website URL was marked wrong by {website_wrong} user(s), correct by {website_right}.")
    if linkedin_wrong:
        parts.append(f"LinkedIn URL was marked wrong by {linkedin_wrong} user(s), correct by {linkedin_right}.")
    if insight_wrong:
        parts.append(f"Insight content was marked wrong by {insight_wrong} user(s), correct by {insight_right}.")

    # Collect user comments (most recent first, max 3)
    comments = [r["comment"] for r in rows if r.get("comment")]
    if comments:
        parts.append("User comments: " + " | ".join(comments[:3]))

    return {
        "text": " ".join(parts),
        "website_flagged": website_wrong > 0,
        "linkedin_flagged": linkedin_wrong > 0,
        "old_website_url": "",
    }


def _build_corporate_graph(fetch_all, cbe: str) -> dict:
    """Query shareholder, participating_interest, and administrator tables once.

    Returns a dict with:
        - shareholders: list of dicts with name, type, ownership_pct
        - subsidiaries: list of dicts with name, country, ownership_pct
        - administrators: list of dicts with name, role_label
        - admin_names_str: comma-separated string for quick prompt embedding
    """
    shareholders = []
    try:
        rows = fetch_all(
            """SELECT name, shareholder_type, ownership_pct FROM shareholder
               WHERE enterprise_number = %s
               ORDER BY ownership_pct DESC NULLS LAST LIMIT 10""",
            (cbe,),
        )
        if rows:
            shareholders = [
                {
                    "name": r["name"],
                    "type": "individual" if r.get("shareholder_type") == "individual" else "entity",
                    "ownership_pct": r.get("ownership_pct"),
                }
                for r in rows if r.get("name")
            ]
    except Exception as e:
        logger.warning("Failed to fetch shareholders for %s: %s", cbe, e)

    subsidiaries = []
    try:
        rows = fetch_all(
            """SELECT name, country, ownership_pct FROM participating_interest
               WHERE enterprise_number = %s
               ORDER BY ownership_pct DESC NULLS LAST LIMIT 10""",
            (cbe,),
        )
        if rows:
            subsidiaries = [
                {
                    "name": r["name"],
                    "country": r.get("country"),
                    "ownership_pct": r.get("ownership_pct"),
                }
                for r in rows if r.get("name")
            ]
    except Exception as e:
        logger.warning("Failed to fetch subsidiaries for %s: %s", cbe, e)

    administrators = []
    try:
        rows = fetch_all(
            """SELECT DISTINCT name, role_label FROM administrator
               WHERE enterprise_number = %s AND mandate_end IS NULL
               LIMIT 10""",
            (cbe,),
        )
        if rows:
            administrators = [
                {"name": r["name"], "role_label": r.get("role_label", "")}
                for r in rows if r.get("name")
            ]
    except Exception as e:
        logger.warning("Failed to fetch administrators for %s: %s", cbe, e)

    admin_names_str = ", ".join(a["name"] for a in administrators) if administrators else ""

    return {
        "shareholders": shareholders,
        "subsidiaries": subsidiaries,
        "administrators": administrators,
        "admin_names_str": admin_names_str,
    }


def _format_corporate_graph_block(graph: dict) -> str:
    """Format the corporate graph as a <corporate_graph> XML block for prompts.

    Returns an empty string if the graph has no shareholders, subsidiaries, or
    administrators — avoids padding prompts with empty data for standalone SMEs.
    """
    if not graph["shareholders"] and not graph["subsidiaries"] and not graph["administrators"]:
        return ""

    parts = ["<corporate_graph>"]
    if graph["shareholders"]:
        sh_lines = []
        for s in graph["shareholders"]:
            pct = f" ({s['ownership_pct']}%)" if s.get("ownership_pct") else ""
            sh_lines.append(f"  - {s['name']} [{s['type']}]{pct}")
        parts.append("Shareholders:\n" + "\n".join(sh_lines))
    if graph["subsidiaries"]:
        sub_lines = []
        for s in graph["subsidiaries"]:
            pct = f" ({s['ownership_pct']}%)" if s.get("ownership_pct") else ""
            country = f", {s['country']}" if s.get("country") else ""
            sub_lines.append(f"  - {s['name']}{country}{pct}")
        parts.append("Subsidiaries:\n" + "\n".join(sub_lines))
    if graph["administrators"]:
        adm_lines = []
        for a in graph["administrators"]:
            role = f" — {a['role_label']}" if a.get("role_label") else ""
            adm_lines.append(f"  - {a['name']}{role}")
        parts.append("Administrators:\n" + "\n".join(adm_lines))
    parts.append("</corporate_graph>")
    return "\n".join(parts)


async def ai_insights_pipeline(cbe: str, conn_helpers: dict) -> dict:
    """Multi-step AI pipeline to generate structured company insights.

    Parameters
    ----------
    cbe : str
        The 10-digit enterprise number.
    conn_helpers : dict
        Must contain ``fetch_one``, ``fetch_all``, and ``execute`` callables.

    Returns a dict with structured insight fields, suitable for JSON storage.
    """
    from scraper import scrape_url, _strip_html, slugify_company_name

    fetch_one = conn_helpers["fetch_one"]
    fetch_all = conn_helpers.get("fetch_all", lambda q, p: [])
    execute = conn_helpers["execute"]

    # ── Gather company context from DB ──────────────────────────
    company = fetch_one("""
        SELECT ci.name, ci.city, ci.nace_code, ci.zipcode,
               a.street_nl AS street, a.house_number,
               COALESCE(nl.description, ci.nace_code) AS sector,
               fl.revenue, fl.ebitda, fl.fte_total, fl.fiscal_year
        FROM company_info ci
        LEFT JOIN address a ON a.entity_number = ci.enterprise_number AND a.type_of_address = 'REGO'
        LEFT JOIN financial_latest fl ON fl.enterprise_number = ci.enterprise_number
        LEFT JOIN nace_lookup nl ON nl.nace_code = ci.nace_code
        WHERE ci.enterprise_number = %s
    """, (cbe,))

    if not company or not company.get("name"):
        return {"error": "Company not found"}

    name = company["name"]
    city = company.get("city", "Belgium")
    zipcode = company.get("zipcode", "")
    street = company.get("street", "")
    house_number = company.get("house_number", "")
    sector = company.get("sector", "")
    revenue = company.get("revenue")
    ebitda = company.get("ebitda")
    fte = company.get("fte_total")
    fiscal_year = company.get("fiscal_year")
    kbo_address = " ".join(filter(None, [street, house_number, zipcode, city]))

    # Check for existing website in contact table
    contact_row = fetch_one("""
        SELECT value FROM contact
        WHERE entity_number = %s AND contact_type = 'WEB'
        LIMIT 1
    """, (cbe,))
    known_website = (contact_row.get("value", "").strip() if contact_row else "") or ""

    # ── Gather user feedback on previous attempts ──────────────
    feedback = _summarize_feedback(fetch_all, cbe)
    feedback_text = feedback["text"]

    # If users flagged the website, grab the old URL from the previous insight
    if feedback["website_flagged"]:
        prev_insight_row = fetch_one(
            "SELECT ai_insights FROM company_enrichment WHERE enterprise_number = %s",
            (cbe,),
        )
        if prev_insight_row and prev_insight_row.get("ai_insights"):
            try:
                prev = json.loads(prev_insight_row["ai_insights"]) if isinstance(prev_insight_row["ai_insights"], str) else prev_insight_row["ai_insights"]
                feedback["old_website_url"] = prev.get("website_url", "")
            except (json.JSONDecodeError, TypeError):
                pass

    # ── Build corporate graph ONCE, reuse everywhere ───────────
    graph = _build_corporate_graph(fetch_all, cbe)
    admin_names = graph["admin_names_str"]
    graph_block = _format_corporate_graph_block(graph)

    # ── STEP 1: URL Discovery ──────────────────────────────────
    website_url = known_website
    linkedin_url = ""

    if not website_url:
        url_prompt = (
            f"Given a Belgian company:\n"
            f"- Name: {name}\n"
            f"- City: {city}\n"
            f"- Sector: {sector}\n"
            f"- Registered address: {kbo_address}\n"
        )
        if admin_names:
            url_prompt += f"- Administrators: {admin_names}\n"
        if graph_block:
            url_prompt += f"\n{graph_block}\n\n"
        url_prompt += (
            "The target company may share a website or LinkedIn page with a parent, "
            "holding, or operating subsidiary. Consider brand names of parents and active "
            "subsidiaries. Prefer a URL that clearly covers the target entity's activity; "
            "if only a group-level URL exists, return it.\n\n"
            'Return ONLY JSON: {{"website_url": "...", "linkedin_url": "...", '
            '"confidence": "high"|"medium"|"low"}}\n'
            "If you cannot determine a URL, use empty strings."
        )
        url_resp = await ai_complete(
            url_prompt,
            system="You are a data lookup assistant. Return only valid JSON.",
            model=VALIDATION_MODEL,
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

    # ── STEP 2b: Validate website matches the company ───────────
    # If the website was LLM-guessed (not from KBO), verify it belongs
    # to this company by checking address, country, and activity match.
    website_verified = bool(known_website)  # Trust KBO-registered websites

    if website_text and not website_verified:
        verify_prompt = (
            f"I scraped the website {website_url} and need to verify it belongs to this Belgian company:\n"
            f"- Company name: {name}\n"
            f"- Registered address: {kbo_address}\n"
            f"- Sector/activity: {sector}\n"
            f"- Country: Belgium\n"
            f"- Known administrators: {admin_names}\n"
        )
        if graph_block:
            verify_prompt += f"\n{graph_block}\n"
        verify_prompt += (
            f"\nWebsite text (first 3000 chars):\n{website_text[:3000]}\n\n"
            "Does this website belong to THIS company or its corporate group? Check:\n"
            "1. Address/city match (target OR any parent/subsidiary address)\n"
            "2. Business activity match (target NACE OR parent/subsidiary NACE if group-level website)\n"
            "3. Country: at least one entity must be Belgian\n"
            "4. Company name match (target name, parent name, or subsidiary name)\n"
            "5. Administrator names appear on website (target admins, or individual shareholders >=25%)\n\n"
            "If at least 2 of these 5 checks match, return true. Otherwise false.\n"
            'Return ONLY JSON: {"match": true/false, "reason": "brief explanation"}'
        )
        # Inject feedback about previously wrong website
        if feedback["website_flagged"]:
            old_url = feedback.get("old_website_url", "")
            flag_note = "\n\nNote: A previous attempt"
            if old_url:
                flag_note += f" found website {old_url} but"
            flag_note += " users flagged the website as incorrect. Please be extra careful in verifying the website."
            verify_prompt += flag_note
        verify_resp = await ai_complete(
            verify_prompt,
            system="You are a data validation assistant. Be strict — if unsure, return false.",
            model=VALIDATION_MODEL,
            max_tokens=150,
        )
        if verify_resp:
            verify_parsed = _extract_json(verify_resp)
            if verify_parsed and not verify_parsed.get("match", True):
                logger.info(
                    "Website %s rejected for %s: %s",
                    website_url, name, verify_parsed.get("reason", "no match")
                )
                website_text = ""  # Don't use this website's content
                website_url = ""   # Clear the bad URL

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
    if admin_names:
        insight_prompt += f"Current administrators: {admin_names}\n"
    if graph_block:
        insight_prompt += f"\n{graph_block}\n"
        insight_prompt += (
            "\nIf the website/LinkedIn content describes group-level activity, "
            "distinguish what applies to the target entity vs. the broader group. "
            "Ownership structure may be mentioned factually (parent, subsidiaries) "
            "but do NOT include ownership percentages or transaction values.\n"
        )
    if website_text:
        insight_prompt += f"\n--- Company website text ---\n{website_text}\n"
    if linkedin_text:
        insight_prompt += f"\n--- LinkedIn page text ---\n{linkedin_text}\n"

    insight_prompt += (
        "\nBased on the above, create a company intelligence brief.\n\n"
        "CRITICAL RULES:\n"
        "- NEVER include revenue, EBITDA, margins, profit, employee count, or any "
        "financial numbers — the user already has those in their financial statements.\n"
        "- NEVER restate the NACE sector description — the user already sees that.\n"
        "- Focus ONLY on: what the company actually does day-to-day, what products/services "
        "they sell, who buys from them, what makes them different, and their history.\n"
        "- Use specific details from the website and LinkedIn content.\n\n"
        "Return a JSON object with exactly these fields:\n"
        '- "business_description": What the company does in 2-3 sentences (no financials!)\n'
        '- "products_services": Their main products/services (specific names, brands)\n'
        '- "target_customers": Who their customers are (industries, segments, B2B/B2C)\n'
        '- "competitive_position": Market position and key differentiators\n'
        '- "company_history": Brief history/milestones (founding, acquisitions, growth)\n'
        '- "key_management": Array of key people found, each as {"name": "...", "role": "...", "linkedin_url": "..."} — extract from LinkedIn page or website team page. If none found, use empty array []\n'
        '- "group_context": If this company is part of a group, describe the parent/subsidiary relationship in one sentence. If standalone, use empty string.\n'
        '- "website_url": The company website URL (or empty string if unknown)\n'
        '- "linkedin_url": The LinkedIn company page URL (or empty string if unknown)\n\n'
        "Return ONLY valid JSON, no markdown fences."
    )

    # Inject user feedback into insight prompt
    if feedback_text:
        insight_prompt += (
            f"\n--- User feedback on previous attempt ---\n"
            f"{feedback_text}\n"
            "Please take this feedback into account and avoid the same mistakes.\n"
        )

    insight_system = (
        "You are a private equity analyst creating a company intelligence brief. "
        "You must NEVER include financial figures (revenue, EBITDA, margins, profit, "
        "employee counts) — the user already has those. Focus exclusively on qualitative "
        "business insights: what the company does, their products, customers, and history. "
        "If website or LinkedIn text is available, extract specific details."
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
            "group_context": "",
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
        "3. Missing or empty fields that could be filled from context\n"
        "4. Any claim that conflates target-entity activity with parent/group activity without attribution\n\n"
        f"Company name: {name}\n"
        f"Sector: {sector}\n"
        f"Location: {city}, Belgium\n\n"
        f"Brief to review:\n{json.dumps(insights, indent=2)}\n\n"
        "Return the same JSON with any corrections, or return it unchanged if it looks good. "
        "Return ONLY valid JSON, no markdown fences."
    )

    # Inject user feedback into review prompt
    if feedback_text:
        review_prompt += (
            f"\n--- User feedback on previous attempt ---\n"
            f"{feedback_text}\n"
            "Pay special attention to the issues flagged by users.\n"
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
